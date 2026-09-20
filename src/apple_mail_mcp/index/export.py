"""Bounded, read-only pages for ingestion of locally indexed email.

The cursor freezes a rowid high-water mark, not a Mail.app snapshot. Index
upserts can replace rows and files can change; coverage says so explicitly.
No cursor includes mail content, addresses, account names, or disk paths.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .disk import extract_message_id, parse_emlx

MAX_PAGE_SIZE = 100
MAX_CURSOR_LENGTH = 2048
# Parsing is already limited to 25 MiB per .emlx. Bound returned text too.
MAX_CONTENT_LENGTH = 1_000_000
EXCLUDED_MAILBOXES = frozenset(
    {
        "Drafts",
        "Junk",
        "Trash",
        "Spam",
        "Bin",
        "Deleted Items",
        "Deleted Messages",
        "Junk E-mail",
        "Junk Email",
    }
)


def _mailbox_parts(value: str) -> list[str]:
    return [
        part.removesuffix(".mbox").strip().casefold()
        for part in re.split(r"[/\\]+", unquote(value))
        if part
    ]


def _mailbox_excluded(value: str, excluded: set[str]) -> bool:
    parts = _mailbox_parts(value)
    for name in excluded:
        target = _mailbox_parts(name)
        if target and any(
            parts[i : i + len(target)] == target for i in range(len(parts))
        ):
            return True
    return False


def normalize_bounds(after: str, before: str) -> tuple[str, str]:
    """Normalize ISO dates/timestamps to UTC, [after, before)."""
    values = []
    for name, value in (("after", after), ("before", before)):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            values.append(parsed.astimezone(UTC).isoformat())
        except (ValueError, TypeError, AttributeError):
            raise ValueError(
                f"{name} must be an ISO 8601 date or timestamp."
            ) from None
    if values[0] >= values[1]:
        raise ValueError("after must precede before.")
    return values[0], values[1]


def _cursor_decode(value: str, scope: str) -> dict[str, Any]:
    try:
        if len(value) > MAX_CURSOR_LENGTH:
            raise ValueError
        raw = base64.b64decode(value, altchars=b"-_", validate=True)
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {
            "v",
            "scope",
            "highwater",
            "position",
            "count",
        }:
            raise ValueError
        if data["v"] != 1 or data["scope"] != scope:
            raise ValueError
        for key in ("highwater", "position", "count"):
            if type(data[key]) is not int or not 0 <= data[key] < 2**63:
                raise ValueError
        if data["position"] > data["highwater"]:
            raise ValueError
        return data
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError):
        raise ValueError(
            "Invalid export cursor or changed account, dates, exclusions, "
            "or index. Restart this bounded export."
        ) from None


def _cursor_encode(data: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).decode()


def _coverage(
    conn: sqlite3.Connection,
    account_id: str,
    max_emails: int | None,
    stale_hours: float,
    excluded: set[str],
) -> dict[str, Any]:
    """Account-scoped health; never expose counts from hidden accounts."""
    rows = conn.execute(
        "SELECT mailbox, COUNT(*) AS count FROM emails "
        "WHERE account = ? AND export_visible(mailbox) GROUP BY mailbox",
        (account_id,),
    ).fetchall()
    syncs = {
        row["mailbox"]: row["last_sync"]
        for row in conn.execute(
            "SELECT mailbox, last_sync FROM sync_state "
            "WHERE account = ? AND export_visible(mailbox)",
            (account_id,),
        )
    }
    stamps = []
    for row in rows:
        value = syncs.get(row["mailbox"])
        try:
            if not isinstance(value, str):
                raise ValueError
            stamp = datetime.fromisoformat(value)
            # Index sync writes local, naive timestamps.
            stamps.append(stamp.astimezone(UTC))
        except (TypeError, ValueError):
            pass
    # Per-mailbox last_sync changes only when that mailbox has changes.
    # Unchanged mailboxes can retain old checkpoints after a full scan.
    # Only the explicit global scan marker establishes global freshness;
    # absent markers must not be inferred from insertion/change timestamps.
    global_row = conn.execute(
        "SELECT last_sync FROM sync_state "
        "WHERE account = '_global' AND mailbox = '_sync'"
    ).fetchone()
    last_sync = None
    if global_row and isinstance(global_row["last_sync"], str):
        try:
            last_sync = datetime.fromisoformat(
                global_row["last_sync"]
            ).astimezone(UTC)
        except ValueError:
            pass
    age = (
        max(0.0, (datetime.now(UTC) - last_sync).total_seconds() / 3600)
        if last_sync
        else None
    )
    failed_jobs = conn.execute(
        "SELECT COUNT(*) FROM failed_index_jobs "
        "WHERE account = ? AND export_visible(mailbox)",
        (account_id,),
    ).fetchone()[0]
    invalid_dates = conn.execute(
        "SELECT COUNT(*) FROM emails WHERE account = ? "
        "AND export_visible(mailbox) AND julianday(date_received) IS NULL",
        (account_id,),
    ).fetchone()[0]
    capped = sum(1 for row in rows if max_emails and row["count"] >= max_emails)
    warnings = [
        "Indexed local mail only; remote archive completeness is unverified.",
        "Rowid high-water mark is not an immutable mailbox snapshot. "
        "Rows and files can change; rerun an overlapping window after sync.",
    ]
    if age is None:
        warnings.append(
            "No completed global inventory sync timestamp is recorded; "
            "index freshness is unknown."
        )
    elif age > stale_hours:
        warnings.append(
            "Last recorded global inventory sync is stale; watcher updates "
            "do not prove a complete rescan."
        )
    if capped:
        warnings.append("One or more indexed mailboxes may be capped.")
    if failed_jobs:
        warnings.append("Index has failed parse jobs; some mail is absent.")
    if invalid_dates:
        warnings.append(
            "Rows with invalid dates cannot enter this date window."
        )
    return {
        "scope": "indexed",
        "archive_complete": False,
        "snapshot_kind": "rowid_highwater",
        "freshness_basis": "global_sync_checkpoint" if last_sync else "unknown",
        "last_sync": last_sync.isoformat() if last_sync else None,
        "staleness_hours": round(age, 2) if age is not None else None,
        "mailbox_oldest_checkpoint": min(stamps).isoformat()
        if stamps
        else None,
        "mailbox_latest_checkpoint": max(stamps).isoformat()
        if stamps
        else None,
        "mailbox_unknown_checkpoints": len(rows) - len(stamps),
        "indexed_mailboxes": len(rows),
        "capped_mailboxes": capped,
        "failed_jobs_count": failed_jobs,
        "invalid_date_count": invalid_dates,
        "excluded_mailboxes": sorted(excluded),
        "warnings": warnings,
    }


def _read_message(
    row: sqlite3.Row,
    account_id: str,
    account_name: str,
    mail_dir: Path,
    hidden_path: Callable[[Path], bool],
    excluded_mailboxes: set[str],
) -> tuple[dict[str, Any] | None, str | None]:
    if not row["emlx_path"]:
        return None, "missing_emlx"
    path = Path(row["emlx_path"])
    try:
        resolved = path.resolve()
        if hidden_path(path) or hidden_path(resolved):
            return None, "unavailable_emlx"
        if not resolved.is_relative_to(mail_dir.resolve() / account_id):
            return None, "unavailable_emlx"
        relative = resolved.relative_to(mail_dir.resolve() / account_id)
        if _mailbox_excluded(str(relative.parent), excluded_mailboxes):
            return None, "unavailable_emlx"
        if resolved.suffix != ".emlx":
            return None, "unavailable_emlx"
        if not resolved.is_file():
            return None, "missing_emlx"
        if extract_message_id(resolved) != row["message_id"]:
            return None, "identity_mismatch"
        parsed = parse_emlx(resolved, require_complete=True)
    except (OSError, ValueError):
        return None, "unreadable_emlx"
    if parsed is None:
        return None, "unreadable_emlx"
    if len(parsed.content) > MAX_CONTENT_LENGTH:
        return None, "content_too_large"
    return {
        "id": row["message_id"],
        "account_id": account_id,
        "account": account_name,
        "mailbox": row["mailbox"],
        "subject": parsed.subject,
        "sender": parsed.sender,
        "to": parsed.to,
        "cc": parsed.cc,
        "content": parsed.content,
        "date_received": row["date_received"],
        "date_sent": parsed.date_sent,
        "message_id": parsed.message_id_header,
        "in_reply_to": parsed.in_reply_to,
        "references": parsed.references,
        "automated": parsed.automated,
        "read": parsed.read,
        "flagged": parsed.flagged,
        "partial": ".partial." in resolved.name,
        "attachments": [
            {
                "filename": att.filename,
                "mime_type": att.mime_type,
                "size": att.file_size,
                "content_id": att.content_id,
            }
            for att in parsed.attachments or []
        ],
    }, None


def export_page(
    db_path: Path,
    mail_dir: Path,
    *,
    account_id: str,
    account_name: str,
    after: str,
    before: str,
    limit: int,
    cursor: str | None,
    excluded_mailboxes: set[str],
    hidden_path: Callable[[Path], bool],
    max_emails: int | None,
    stale_hours: float,
) -> dict[str, Any]:
    """Read one index page. Opening SQLite in mode=ro never creates an index."""
    after, before = normalize_bounds(after, before)
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    excluded = set(EXCLUDED_MAILBOXES) | excluded_mailboxes
    stat = db_path.stat()
    scope = hashlib.sha256(
        json.dumps(
            [
                stat.st_dev,
                stat.st_ino,
                account_id,
                after,
                before,
                sorted(excluded),
            ]
        ).encode()
    ).hexdigest()
    state = _cursor_decode(cursor, scope) if cursor else None
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.create_function(
            "export_visible",
            1,
            lambda mailbox: not _mailbox_excluded(mailbox or "", excluded),
            deterministic=True,
        )
        conn.execute("BEGIN")
        highwater = (
            state["highwater"]
            if state
            else conn.execute(
                "SELECT COALESCE(MAX(rowid), 0) FROM emails WHERE account = ?",
                (account_id,),
            ).fetchone()[0]
        )
        where = (
            "account = ? AND rowid <= ? AND export_visible(mailbox) "
            "AND julianday(date_received) >= julianday(?) "
            "AND julianday(date_received) < julianday(?)"
        )
        params = (account_id, highwater, after, before)
        count = conn.execute(
            f"SELECT COUNT(*) FROM emails WHERE {where}", params
        ).fetchone()[0]
        state = state or {
            "v": 1,
            "scope": scope,
            "highwater": highwater,
            "position": 0,
            "count": count,
        }
        rows = conn.execute(
            f"SELECT * FROM emails WHERE {where} "
            "AND rowid > ? ORDER BY rowid LIMIT ?",
            (*params, state["position"], limit + 1),
        ).fetchall()
        coverage = _coverage(
            conn, account_id, max_emails, stale_hours, excluded
        )
    finally:
        conn.close()
    has_more = len(rows) > limit
    rows = rows[:limit]
    messages = []
    errors = []
    for row in rows:
        message, error = _read_message(
            row, account_id, account_name, mail_dir, hidden_path, excluded
        )
        if message is not None:
            messages.append(message)
        else:
            errors.append(
                {
                    "id": row["message_id"],
                    "account_id": account_id,
                    "mailbox": row["mailbox"],
                    "code": error,
                }
            )
    if count != state["count"]:
        coverage["warnings"].append(
            "Indexed rows changed during traversal; restart an overlapping "
            "window to reconcile moved, deleted, or replaced entries."
        )
    if errors:
        coverage["warnings"].append(
            "Some page messages could not be read; retain errors for retry."
        )
    if any(message["partial"] for message in messages):
        coverage["warnings"].append(
            "Partial .emlx files may have incomplete attachment metadata."
        )
    coverage.update(
        snapshot_highwater=highwater,
        eligible_count=state["count"],
        scanned_count=len(rows),
        returned_count=len(messages),
        failed_count=len(errors),
        has_more=has_more,
    )
    if rows:
        state["position"] = rows[-1]["rowid"]
    return {
        "schema_version": 1,
        "account": {"id": account_id, "name": account_name},
        "after": after,
        "before": before,
        "messages": messages,
        "errors": errors,
        "next_cursor": _cursor_encode(state) if has_more else None,
        "coverage": coverage,
    }
