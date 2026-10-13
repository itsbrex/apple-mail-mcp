"""Nested mailbox resolution through search, identity, and upgrade paths."""

from __future__ import annotations

import unicodedata
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apple_mail_mcp.index.mailboxes import (
    AmbiguousMailboxError,
    resolve_for_identity,
    resolve_for_search,
)
from apple_mail_mcp.index.manager import IndexManager
from apple_mail_mcp.index.schema import init_database
from apple_mail_mcp.index.search import (
    count_matches,
    search_attachments,
    search_fts,
    search_fts_highlight,
)

CAFE = unicodedata.normalize("NFD", "Archive/Café")
PATHS = [
    "[Gmail]/All Mail",
    "[Gmail]/Spam",
    "[Gmailish]/Spam",
    "Ablage/Nebenkosten",
    "Archive/Nebenkosten",
    CAFE,
    "Archive/100%_done",
    'Archive/Quarter "one"',
    "Archive/Café/Child",
]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("[gmail]/spam", ["[Gmail]/Spam"]),
        ("ALL MAIL", ["[Gmail]/All Mail"]),
        ("[Gmail]", PATHS[:2]),
        ("CAFÉ", [CAFE]),
        ("archive/café", [CAFE]),
        ("100%_done", ["Archive/100%_done"]),
        ("100%", []),
        ("Gmail", []),
        ("absent' OR 1=1 --", []),
    ],
)
def test_search_resolution(value, expected):
    assert resolve_for_search(value, PATHS) == expected


def test_exact_parent_takes_precedence_over_descendants():
    paths = ["Archive", "Archive/Child"]
    assert resolve_for_search("archive", paths) == ["Archive"]
    assert resolve_for_identity("archive", paths) == ["Archive"]


def test_identity_never_expands_a_subtree():
    assert resolve_for_identity("[Gmail]", PATHS) == []
    assert resolve_for_identity("All Mail", PATHS) == ["[Gmail]/All Mail"]
    assert resolve_for_identity("CAFÉ", PATHS) == [CAFE]


@pytest.mark.parametrize("resolve", [resolve_for_search, resolve_for_identity])
def test_ambiguous_leaf_error_has_copyable_full_paths(resolve):
    with pytest.raises(AmbiguousMailboxError) as caught:
        resolve("Nebenkosten", PATHS)
    assert str(caught.value) == (
        'Ambiguous mailbox "Nebenkosten" — specify one of: '
        'mailbox="Ablage/Nebenkosten", mailbox="Archive/Nebenkosten"'
    )


def test_exclusions_union_ambiguous_leaves():
    assert resolve_for_search("Spam", PATHS, exclude=True) == [
        "[Gmail]/Spam",
        "[Gmailish]/Spam",
    ]


@pytest.mark.parametrize("resolve", [resolve_for_search, resolve_for_identity])
def test_normalization_collision_requires_an_exact_stored_path(resolve):
    paths = ["Straße", "Strasse"]
    with pytest.raises(AmbiguousMailboxError):
        resolve("STRASSE", paths)
    for mailbox in paths:
        assert resolve(mailbox, paths) == [mailbox]
    assert resolve_for_search("Straße", paths, exclude=True) == sorted(paths)


@pytest.fixture
def nested_db(temp_db):
    # Repeated message IDs reproduce the identity hazard in #107.
    for account, mailbox in [
        *(("A", name) for name in PATHS),
        ("B", "Other/Nebenkosten"),
    ]:
        row = temp_db.execute(
            "INSERT INTO emails "
            "(message_id, account, mailbox, subject, content, emlx_path) "
            "VALUES (42, ?, ?, 'invoice', 'invoice', ?)",
            (account, mailbox, f"/fixture/{account}/{mailbox}/42.emlx"),
        )
        temp_db.execute(
            "INSERT INTO attachments (email_rowid, filename) "
            "VALUES (?, 'invoice.pdf')",
            (row.lastrowid,),
        )
    temp_db.commit()
    return temp_db


SEARCHES = [search_fts, search_fts_highlight, count_matches, search_attachments]


def result_count(result):
    return result if isinstance(result, int) else len(result)


@pytest.mark.parametrize("search", SEARCHES)
def test_all_search_entrypoints_resolve_nested_paths(nested_db, search):
    assert result_count(search(nested_db, "invoice", mailbox="[Gmail]")) == 2
    assert result_count(search(nested_db, "invoice", mailbox="CAFÉ")) == 1
    assert result_count(search(nested_db, "invoice", mailbox="missing")) == 0
    assert result_count(search(nested_db, "invoice", mailbox="100%_done")) == 1
    with pytest.raises(AmbiguousMailboxError):
        search(nested_db, "invoice", mailbox="Nebenkosten")


@pytest.mark.parametrize("search", SEARCHES)
def test_resolution_is_scoped_to_the_requested_account(nested_db, search):
    assert (
        result_count(
            search(nested_db, "invoice", account="B", mailbox="Nebenkosten")
        )
        == 1
    )
    assert (
        result_count(
            search(
                nested_db, "invoice", account="unknown", mailbox="Nebenkosten"
            )
        )
        == 0
    )


@pytest.mark.parametrize(
    "search", [search_fts, search_fts_highlight, search_attachments]
)
def test_excluded_accounts_do_not_leak_candidates(nested_db, search):
    with pytest.raises(AmbiguousMailboxError) as caught:
        search(
            nested_db, "invoice", mailbox="Nebenkosten", exclude_accounts=["B"]
        )
    assert "Other/Nebenkosten" not in str(caught.value)
    assert (
        result_count(
            search(
                nested_db,
                "invoice",
                mailbox="Nebenkosten",
                exclude_accounts=["A"],
            )
        )
        == 1
    )


@pytest.mark.parametrize(
    "search", [search_fts, search_fts_highlight, search_attachments]
)
def test_search_exclusions_resolve_once_and_union(nested_db, search):
    queries = []
    nested_db.set_trace_callback(queries.append)
    rows = search(
        nested_db,
        "invoice",
        mailbox="[Gmail]",
        exclude_mailboxes=["Spam", "absent"],
    )
    assert len(rows) == 1
    row = rows[0]
    assert (row["mailbox"] if isinstance(row, dict) else row.mailbox) == (
        "[Gmail]/All Mail"
    )
    assert len([q for q in queries if "SELECT DISTINCT mailbox" in q]) == 1
    assert not search(
        nested_db,
        "invoice",
        mailbox="[Gmail]",
        exclude_mailboxes=["[gmail]"],
    )


@pytest.fixture
def manager(nested_db, tmp_path):
    manager = IndexManager(tmp_path / "index.db")
    manager._conn = nested_db
    return manager


def test_manager_identity_lookups_share_normalization(manager):
    assert manager.find_email_location(42, "A", "CAFÉ") == ("A", CAFE)
    assert manager.find_email_path(42, "A", "archive/café") == Path(
        f"/fixture/A/{CAFE}/42.emlx"
    )
    assert manager.get_indexed_message_ids("A", "Café") == {42}
    assert manager.get_email_attachments(42, "A", "CAFÉ")[0]["filename"] == (
        "invoice.pdf"
    )
    assert manager.find_email_path(42, "B", "Nebenkosten") == Path(
        "/fixture/B/Other/Nebenkosten/42.emlx"
    )


@pytest.mark.parametrize("method", ["find_email_path", "find_email_location"])
def test_identity_errors_respect_excluded_accounts(manager, method):
    lookup = getattr(manager, method)
    with pytest.raises(AmbiguousMailboxError) as caught:
        lookup(42, mailbox="Nebenkosten", exclude_accounts=["B"])
    assert "Other/Nebenkosten" not in str(caught.value)
    assert lookup(42, mailbox="Nebenkosten", exclude_accounts=["A"])
    assert lookup(42, account="B", exclude_accounts=["B"]) is None


def test_identity_parent_or_unknown_cannot_select_or_delete_children(manager):
    for mailbox in ["[Gmail]", "unknown"]:
        assert manager.find_email_location(42, mailbox=mailbox) is None
        assert manager.find_email_path(42, mailbox=mailbox) is None
        assert manager.get_indexed_message_ids(mailbox=mailbox) == set()
        assert manager.get_email_attachments(42, mailbox=mailbox) is None
        assert manager.delete_email(42, mailbox=mailbox) == 0
    assert (
        manager._get_conn().execute("SELECT COUNT(*) FROM emails").fetchone()[0]
        == 10
    )


def test_ambiguous_identity_never_deletes_rows(manager):
    for method in [
        manager.find_email_path,
        manager.find_email_location,
        manager.get_email_attachments,
        manager.delete_email,
    ]:
        with pytest.raises(AmbiguousMailboxError):
            method(42, mailbox="Nebenkosten")
    with pytest.raises(AmbiguousMailboxError):
        manager.get_indexed_message_ids(mailbox="Nebenkosten")
    with pytest.raises(AmbiguousMailboxError):
        manager.rebuild(mailbox="Nebenkosten")
    assert (
        manager._get_conn().execute("SELECT COUNT(*) FROM emails").fetchone()[0]
        == 10
    )


def test_delete_resolves_one_mailbox_and_preserves_same_id_elsewhere(manager):
    assert manager.delete_email(42, "B", "NEBENKOSTEN") == 1
    assert manager.find_email_location(42, "A", "Archive/Nebenkosten")
    assert manager.delete_email(42, "A", "CAFÉ") == 1
    assert manager.find_email_location(42, "A", "Archive/Café/Child")
    assert (
        manager._get_conn()
        .execute("SELECT COUNT(*) FROM attachments")
        .fetchone()[0]
        == 8
    )


def test_passive_manager_does_not_resolve_or_delete(manager):
    manager.index_writer = False
    assert manager.delete_email(42, mailbox="Nebenkosten") == 0
    with pytest.raises(RuntimeError, match="index-passive"):
        manager.rebuild(mailbox="Nebenkosten")


def make_mail_store(root, content):
    paths = []
    for mailbox in ["Projects.mbox/Alpha.mbox", "Other.mbox/Alpha.mbox"]:
        file = root / "A" / mailbox / "Data" / "Messages" / "42.emlx"
        file.parent.mkdir(parents=True)
        file.write_bytes(content)
        paths.append(file)
    return paths


def test_scoped_rebuild_keeps_other_mailbox_rows(tmp_path, sample_emlx_content):
    mail_dir = tmp_path / "V10"
    make_mail_store(mail_dir, sample_emlx_content)
    manager = IndexManager(tmp_path / "index.db")
    try:
        with patch(
            "apple_mail_mcp.index.disk.find_mail_directory",
            return_value=mail_dir,
        ):
            assert manager.sync_updates() == 2
            conn = manager._get_conn()
            before = dict(conn.execute("SELECT mailbox, rowid FROM emails"))
            assert manager.rebuild("A", "projects/alpha") == 1
            after = dict(conn.execute("SELECT mailbox, rowid FROM emails"))
            assert after["Projects/Alpha"] != before["Projects/Alpha"]
            assert after["Other/Alpha"] == before["Other/Alpha"]
    finally:
        manager.close()


def test_v6_migration_clears_cache_and_next_sync_restores_distinct_paths(
    tmp_path, sample_emlx_content
):
    db_path = tmp_path / "index.db"
    conn = init_database(db_path)
    conn.execute("UPDATE schema_version SET version = 5")
    row = conn.execute(
        "INSERT INTO emails (message_id, account, mailbox, content) "
        "VALUES (42, 'A', 'Alpha', 'collapsed')"
    )
    conn.execute(
        "INSERT INTO attachments (email_rowid, filename) VALUES (?, 'old.pdf')",
        (row.lastrowid,),
    )
    conn.execute(
        "INSERT INTO sync_state (account, mailbox, last_sync) "
        "VALUES ('A', 'Alpha', datetime('now'))"
    )
    conn.execute(
        "INSERT INTO failed_index_jobs "
        "(emlx_path, account, mailbox, error_type, error_message) "
        "VALUES ('/old.emlx', 'A', 'Alpha', 'ValueError', 'preserve history')"
    )
    conn.commit()
    conn.close()

    manager = IndexManager(db_path)
    try:
        migrated = manager._get_conn()
        for table in ["emails", "attachments", "sync_state"]:
            assert (
                migrated.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                == 0
            )
        assert not migrated.execute(
            "SELECT rowid FROM emails_fts WHERE emails_fts MATCH 'collapsed'"
        ).fetchall()
        assert (
            migrated.execute(
                "SELECT COUNT(*) FROM failed_index_jobs"
            ).fetchone()[0]
            == 1
        )
        assert (
            migrated.execute("SELECT version FROM schema_version").fetchone()[0]
            == 6
        )
        mail_dir = tmp_path / "V10"
        make_mail_store(mail_dir, sample_emlx_content)
        with patch(
            "apple_mail_mcp.index.disk.find_mail_directory",
            return_value=mail_dir,
        ):
            assert manager.sync_updates() == 2
        assert {
            r[0] for r in migrated.execute("SELECT mailbox FROM emails")
        } == {"Projects/Alpha", "Other/Alpha"}
    finally:
        manager.close()
    # Reopening an already-migrated database must not clear it again.
    conn = init_database(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0] == 2
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_mcp_search_reports_ambiguity_without_rebuild_advice():
    from apple_mail_mcp import server

    error = AmbiguousMailboxError("Spam", ["One/Spam", "Two/Spam"])
    manager = MagicMock()
    manager.has_index.return_value = True
    manager.search.side_effect = error
    accounts = MagicMock()
    accounts.ensure_loaded = AsyncMock()
    accounts.names_to_uuids.return_value = set()
    with (
        patch.object(server, "_get_index_manager", return_value=manager),
        patch.object(server, "_get_account_map", return_value=accounts),
        patch.object(
            server, "_resolve_visible_account", new=AsyncMock(return_value=None)
        ),
    ):
        with pytest.raises(AmbiguousMailboxError) as caught:
            await server.search("invoice", mailbox="Spam")
    assert caught.value is error


@pytest.mark.asyncio
async def test_mcp_get_email_does_not_fall_back_after_ambiguous_identity():
    from apple_mail_mcp import server

    manager = MagicMock()
    manager.has_index.return_value = True
    manager.find_email_path.side_effect = AmbiguousMailboxError(
        "Spam", ["One/Spam", "Two/Spam"]
    )
    accounts = MagicMock()
    accounts.ensure_loaded = AsyncMock()
    accounts.names_to_uuids.return_value = {"HIDDEN"}
    accounts.name_to_uuid.return_value = None
    with (
        patch.object(server, "_get_index_manager", return_value=manager),
        patch.object(server, "_get_account_map", return_value=accounts),
        patch.object(
            server,
            "_resolve_visible_account",
            new=AsyncMock(return_value="Visible"),
        ),
        patch.object(server, "execute_with_core_async", new=AsyncMock()) as jxa,
    ):
        with pytest.raises(AmbiguousMailboxError):
            await server.get_email(42, account="UNKNOWN", mailbox="Spam")
    jxa.assert_not_called()
    manager.find_email_path.assert_called_once_with(
        42, account="UNKNOWN", mailbox="Spam", exclude_accounts=["HIDDEN"]
    )
