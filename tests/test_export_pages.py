"""Read-only ingestion pages: public MCP seam, real SQLite and MIME files."""

from __future__ import annotations

import base64
import hashlib
import json
import plistlib
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apple_mail_mcp import server
from apple_mail_mcp.index.accounts import AccountMap
from apple_mail_mcp.index.schema import INSERT_EMAIL_SQL, init_database

AFTER = "2026-09-01"
BEFORE = "2026-10-01"
DATE = "2026-09-05T12:00:00+00:00"


@pytest.fixture
def mailbox(tmp_path, monkeypatch):
    db_path = tmp_path / "index.db"
    conn = init_database(db_path)
    mail_dir = tmp_path / "Mail" / "V10"
    mail_dir.mkdir(parents=True)
    account_map = AccountMap()
    account_map.load_from_jxa(
        [
            {"id": "account-work", "name": "Work"},
            {"id": "account-secret", "name": "Secret"},
        ]
    )
    manager = SimpleNamespace(db_path=db_path, has_index=db_path.exists)
    monkeypatch.setattr(server, "_get_index_manager", lambda: manager)
    monkeypatch.setattr(server, "_get_account_map", lambda: account_map)
    monkeypatch.setattr(
        "apple_mail_mcp.index.disk.find_mail_directory", lambda: mail_dir
    )
    jxa = AsyncMock(side_effect=AssertionError("export must not use JXA"))
    monkeypatch.setattr(server, "execute_with_core_async", jxa)
    monkeypatch.setattr("apple_mail_mcp.executor.execute_with_core_async", jxa)

    def add(
        message_id=1,
        folder="INBOX",
        *,
        account="account-work",
        date=DATE,
        body="Readable body",
        attachment=False,
        path=None,
        headers=None,
    ):
        if path is None:
            path = mail_dir / account
            for segment in folder.split("/"):
                path /= segment + ".mbox"
            path /= f"Data/Messages/{message_id}.emlx"
            path.parent.mkdir(parents=True, exist_ok=True)
            msg = EmailMessage()
            msg["Subject"] = f"Message {message_id} in {folder}"
            msg["From"] = "Sender <sender@example.test>"
            msg["To"] = '"Recipient, Name" <recipient@example.test>'
            msg["Cc"] = "Other <other@example.test>"
            msg["Date"] = "Sat, 05 Sep 2026 12:00:00 +0000"
            msg["Message-ID"] = "<copy@example.test>"
            msg["In-Reply-To"] = "<parent@example.test>"
            msg["References"] = "<root@example.test> <parent@example.test>"
            for name, value in (headers or {}).items():
                msg[name] = value
            msg.set_content(body)
            if attachment:
                msg.add_attachment(
                    b"attachment payload must not appear",
                    maintype="application",
                    subtype="octet-stream",
                    filename="notes.bin",
                )
            raw = msg.as_bytes()
            path.write_bytes(
                str(len(raw)).encode()
                + b"\n"
                + raw
                + plistlib.dumps({"flags": 17})
            )
        conn.execute(
            INSERT_EMAIL_SQL,
            (
                message_id,
                account,
                folder,
                "Indexed subject",
                "indexed sender",
                "Indexed body",
                date,
                str(path),
                0,
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO sync_state VALUES (?, ?, ?, 1)",
            (account, folder, "2026-09-06T00:00:00+00:00"),
        )
        conn.commit()
        return path

    yield SimpleNamespace(
        add=add,
        conn=conn,
        db_path=db_path,
        mail_dir=mail_dir,
        account_map=account_map,
        jxa=jxa,
    )
    conn.close()


async def page(**kwargs):
    return await server.export_emails_page(
        **{"account": "Work", "after": AFTER, "before": BEFORE, **kwargs}
    )


async def test_scoped_identity_mime_headers_metadata_and_no_writes(mailbox):
    first = mailbox.add(7, "INBOX", body="Incoming body", attachment=True)
    second = mailbox.add(7, "Archive", body="Archived copy")
    mailbox.add(7, account="account-secret", body="Hidden data")
    digests = [
        hashlib.sha256(p.read_bytes()).hexdigest() for p in (first, second)
    ]
    result = await page(account="account-work")
    assert result["account"] == {"id": "account-work", "name": "Work"}
    assert [(m["id"], m["mailbox"]) for m in result["messages"]] == [
        (7, "INBOX"),
        (7, "Archive"),
    ]
    one, two = result["messages"]
    assert one["content"].strip() == "Incoming body"
    assert two["content"].strip() == "Archived copy"
    assert one["to"] == [
        {"name": "Recipient, Name", "address": "recipient@example.test"}
    ]
    assert one["cc"] == [{"name": "Other", "address": "other@example.test"}]
    assert one["message_id"] == "<copy@example.test>"
    assert one["in_reply_to"] == "<parent@example.test>"
    assert one["references"] == ["<root@example.test>", "<parent@example.test>"]
    assert one["read"] is True and one["flagged"] is True
    assert one["date_received"] == DATE and one["date_sent"] == DATE
    assert one["attachments"][0]["filename"] == "notes.bin"
    assert "attachment payload" not in json.dumps(result)
    assert result["next_cursor"] is None
    assert result["coverage"]["archive_complete"] is False
    assert digests == [
        hashlib.sha256(p.read_bytes()).hexdigest() for p in (first, second)
    ]
    mailbox.jxa.assert_not_called()


async def test_keyset_resume_ties_replay_and_new_rows(mailbox):
    for mid in range(1, 4):
        mailbox.add(mid)
    first = await page(limit=1)
    cursor = first["next_cursor"]
    raw = base64.urlsafe_b64decode(cursor).decode()
    assert not any(
        s in raw for s in ("Work", "account-work", "sender", "Mail/")
    )
    mailbox.add(4)  # Same date, inserted after snapshot high-water mark.
    second = await page(limit=1, cursor=cursor)
    replay = await page(limit=1, cursor=cursor)
    assert second["messages"] == replay["messages"]
    assert second["next_cursor"] == replay["next_cursor"]
    third = await page(limit=1, cursor=second["next_cursor"])
    assert [p["messages"][0]["id"] for p in (first, second, third)] == [1, 2, 3]
    assert third["next_cursor"] is None
    assert third["coverage"]["eligible_count"] == 3
    assert len((await page())["messages"]) == 4


async def test_cursor_binds_scope_bounds_exclusions_and_index(
    mailbox, monkeypatch
):
    mailbox.add(1)
    mailbox.add(2)
    cursor = (await page(limit=1))["next_cursor"]
    for changed in (
        {"account": "Secret"},
        {"after": "2026-09-02"},
        {"before": "2026-09-30"},
        {"cursor": "bad cursor"},
    ):
        with pytest.raises(ValueError, match="Invalid export cursor"):
            await page(**{"cursor": cursor, **changed})
    monkeypatch.setenv("APPLE_MAIL_INDEX_EXCLUDE_MAILBOXES", "Drafts,Archive")
    with pytest.raises(ValueError, match="Invalid export cursor"):
        await page(cursor=cursor)
    monkeypatch.delenv("APPLE_MAIL_INDEX_EXCLUDE_MAILBOXES")
    replacement = mailbox.db_path.with_name("replacement.db")
    other = init_database(replacement)
    other.close()
    replacement.replace(mailbox.db_path)
    with pytest.raises(ValueError, match="Invalid export cursor"):
        await page(cursor=cursor)


async def test_unreadable_missing_and_cross_account_files_are_errors(
    mailbox, monkeypatch
):
    missing = mailbox.add(1)
    missing.unlink()
    unreadable = mailbox.add(2)
    unreadable.write_bytes(b"invalid emlx")
    secret = mailbox.add(3, account="account-secret")
    mailbox.add(3, path=secret)
    good = mailbox.add(4)
    monkeypatch.setenv("APPLE_MAIL_INDEX_EXCLUDE_ACCOUNTS", "Secret")
    result = await page(limit=3)
    assert result["messages"] == []
    assert [e["code"] for e in result["errors"]] == [
        "missing_emlx",
        "unreadable_emlx",
        "unavailable_emlx",
    ]
    assert result["coverage"]["failed_count"] == 3
    assert result["coverage"]["scanned_count"] == 3
    resumed = await page(cursor=result["next_cursor"])
    assert [m["id"] for m in resumed["messages"]] == [4]
    assert str(good) not in json.dumps(result)


async def test_hidden_account_by_name_uuid_and_mid_traversal(
    mailbox, monkeypatch
):
    mailbox.add(1)
    mailbox.add(2)
    cursor = (await page(limit=1))["next_cursor"]
    monkeypatch.setenv("APPLE_MAIL_INDEX_EXCLUDE_ACCOUNTS", "Work")
    for account in ("Work", "account-work"):
        with pytest.raises(ValueError, match="Account not found"):
            await page(account=account, cursor=cursor)
    mailbox.jxa.assert_not_called()


async def test_stale_row_cannot_read_excluded_nested_path(mailbox):
    path = mailbox.add(1, "[Gmail]/Trash")
    mailbox.add(1, "INBOX", path=path)
    result = await page()
    assert result["messages"] == []
    assert result["errors"][0]["code"] == "unavailable_emlx"


async def test_account_scope_never_widens(mailbox):
    mailbox.add()
    for account in ("", "Unknown", "work"):
        with pytest.raises(ValueError, match="Account not found"):
            await page(account=account)


async def test_nested_exclusions_and_archived_sent_are_included(
    mailbox, monkeypatch
):
    excluded = [
        "Drafts",
        "[Gmail]/Trash",
        "Folder/JUNK",
        "Trash/Older",
        "Folder/Deleted Items",
        "[Gmail]/Spam",
        "Folder/Junk%20E-mail",
        "Custom/Excluded",
        "Custom/Excluded/Subfolder",
    ]
    included = ["INBOX", "Sent", "Archive", "Draftsmanship"]
    for folder in excluded + included:
        mailbox.add(folder=folder)
    monkeypatch.setenv("APPLE_MAIL_INDEX_EXCLUDE_MAILBOXES", "Custom/Excluded")
    result = await page()
    assert [m["mailbox"] for m in result["messages"]] == included
    assert result["coverage"]["eligible_count"] == len(included)


async def test_dates_are_inclusive_exclusive_and_timezone_aware(mailbox):
    mailbox.add(1, date="2026-09-01T00:00:00Z")
    mailbox.add(2, date="2026-08-31T23:00:00-01:00")
    mailbox.add(3, date="2026-10-01T00:00:00Z")
    mailbox.add(4, date="2026-08-31T23:59:59Z")
    result = await page()
    assert [m["id"] for m in result["messages"]] == [1, 2]
    assert result["after"] == "2026-09-01T00:00:00+00:00"
    for args in ({"after": "bad"}, {"before": AFTER}, {"after": BEFORE}):
        with pytest.raises(ValueError):
            await page(**args)


async def test_coverage_scoped_stale_capped_failed_and_invalid_dates(
    mailbox, monkeypatch
):
    mailbox.add()
    mailbox.add(2, date="undated")
    mailbox.add(3, account="account-secret")
    mailbox.conn.execute(
        "INSERT INTO failed_index_jobs "
        "(emlx_path, account, mailbox, error_type, error_message) "
        "VALUES ('private/path', 'account-work', 'INBOX', "
        "'Error', 'private body')"
    )
    mailbox.conn.execute(
        "INSERT INTO failed_index_jobs "
        "(emlx_path, account, mailbox, error_type, error_message) "
        "VALUES ('secret/path', 'account-secret', 'INBOX', "
        "'Error', 'private body')"
    )
    mailbox.conn.execute(
        "UPDATE sync_state SET last_sync='2020-01-01T00:00:00Z'"
    )
    mailbox.conn.execute(
        "INSERT INTO sync_state VALUES "
        "('_global', '_sync', '2020-01-01T00:00:00Z', 0)"
    )
    mailbox.conn.commit()
    monkeypatch.setenv("APPLE_MAIL_INDEX_MAX_EMAILS", "1")
    result = await page()
    coverage = result["coverage"]
    assert coverage["failed_jobs_count"] == 1
    assert coverage["invalid_date_count"] == 1
    assert coverage["capped_mailboxes"] == 1
    assert coverage["indexed_mailboxes"] == 1
    assert coverage["staleness_hours"] > 24
    assert "private" not in json.dumps(coverage)


async def test_noop_sync_global_marker_refreshes_unchanged_mailbox(mailbox):
    from apple_mail_mcp.index.sync import sync_from_disk

    mailbox.add()
    original = await page()
    assert original["coverage"]["last_sync"] is None
    assert original["coverage"]["staleness_hours"] is None
    assert original["coverage"]["freshness_basis"] == "unknown"
    checkpoint = original["coverage"]["mailbox_oldest_checkpoint"]
    assert checkpoint == "2026-09-06T00:00:00+00:00"

    result = sync_from_disk(mailbox.conn, mailbox.mail_dir)
    assert result.total_changes == 0
    refreshed = (await page())["coverage"]
    assert refreshed["last_sync"] is not None
    assert refreshed["staleness_hours"] < 0.1
    assert refreshed["freshness_basis"] == "global_sync_checkpoint"
    assert refreshed["mailbox_oldest_checkpoint"] == checkpoint
    assert refreshed["mailbox_latest_checkpoint"] == checkpoint
    assert not any("is stale" in w for w in refreshed["warnings"])


async def test_sync_with_changes_still_records_global_freshness(mailbox):
    """A busy mailbox changes on nearly every sync; freshness must not
    stay "unknown" just because the last full rescan found changes."""
    from apple_mail_mcp.index.sync import sync_from_disk

    mailbox.add(1)
    mailbox.add(2).unlink()  # Deleted on disk: the next sync must change.
    result = sync_from_disk(mailbox.conn, mailbox.mail_dir)
    assert result.total_changes > 0
    coverage = (await page())["coverage"]
    assert coverage["freshness_basis"] == "global_sync_checkpoint"
    assert coverage["last_sync"] is not None
    assert coverage["staleness_hours"] < 0.1
    assert not any("freshness is unknown" in w for w in coverage["warnings"])


async def test_changed_index_reports_gap_and_empty_never_means_complete(
    mailbox,
):
    mailbox.add(1)
    mailbox.add(2)
    first = await page(limit=1)
    mailbox.add(2, body="Reindexed content")  # REPLACE receives a new rowid.
    last = await page(cursor=first["next_cursor"])
    assert last["messages"] == []
    assert last["next_cursor"] is None
    assert last["coverage"]["archive_complete"] is False
    assert any(
        "changed during traversal" in w for w in last["coverage"]["warnings"]
    )


async def test_limit_is_bounded_and_missing_index_fails(mailbox):
    for mid in range(1, 103):
        mailbox.add(mid)
    assert len((await page(limit=10000))["messages"]) == 100
    assert len((await page(limit=-1))["messages"]) == 1
    mailbox.db_path.unlink()
    with pytest.raises(ValueError, match="No index found"):
        await page()


async def test_unreadable_file_has_explicit_error(mailbox, monkeypatch):
    target = mailbox.add()
    read_bytes = Path.read_bytes

    def refused(path):
        if path == target:
            raise PermissionError("private path must not leak")
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", refused)
    result = await page()
    assert result["errors"][0]["code"] == "unreadable_emlx"
    assert "private path" not in json.dumps(result)


async def test_read_only_mode_allows_export(mailbox, monkeypatch):
    mailbox.add()
    monkeypatch.setenv("APPLE_MAIL_READ_ONLY", "1")
    assert len((await page())["messages"]) == 1
    mailbox.jxa.assert_not_called()


async def test_truncated_mime_is_not_reported_as_success(mailbox):
    target = mailbox.add()
    target.write_bytes(b"999999\nFrom: sender@example.test\n\nPartial body")
    result = await page()
    assert result["messages"] == []
    assert result["errors"][0]["code"] == "unreadable_emlx"


@pytest.mark.parametrize(
    ("headers", "automated"),
    [
        ({"List-Id": "Newsletter <news.example.test>"}, True),
        ({"Auto-Submitted": "auto-replied"}, True),
        ({"Auto-Submitted": "no"}, False),
        ({"Auto-Submitted": "no; extension=yes"}, False),
        ({"Precedence": "bulk"}, True),
        ({"Precedence": "LIST"}, True),
        ({"Precedence": "junk"}, True),
        ({"Precedence": "normal"}, False),
        ({}, False),
    ],
)
async def test_automated_mail_flag(mailbox, headers, automated):
    mailbox.add(headers=headers)
    result = await page()
    assert result["messages"][0]["automated"] is automated
