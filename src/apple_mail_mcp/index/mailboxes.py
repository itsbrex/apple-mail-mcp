"""Resolve mailbox filters to stored paths before building exact SQL filters.

Search may expand a parent to its subtree. Identity lookups must never do so:
an ambiguous or unknown mailbox must not widen a lookup or deletion.
"""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from collections.abc import Iterable


class AmbiguousMailboxError(ValueError):
    """The caller must retry with one of the stored full mailbox paths."""

    def __init__(self, mailbox: str, candidates: list[str]) -> None:
        choices = ", ".join(
            f"mailbox={json.dumps(name, ensure_ascii=False)}"
            for name in candidates
        )
        super().__init__(
            f"Ambiguous mailbox {json.dumps(mailbox, ensure_ascii=False)}"
            f" — specify one of: {choices}"
        )


def indexed_mailboxes(
    conn: sqlite3.Connection,
    account: str | None = None,
    exclude_accounts: Iterable[str] | None = None,
) -> list[str]:
    """Read candidates only from the accounts visible to this query."""
    sql = "SELECT DISTINCT mailbox FROM emails WHERE 1=1"
    params: list[str] = []
    if account:
        sql += " AND account = ?"
        params.append(account)
    excluded = list(exclude_accounts or ())
    if excluded:
        sql += " AND account NOT IN (" + ", ".join("?" for _ in excluded) + ")"
        params.extend(excluded)
    return [row[0] for row in conn.execute(sql, params)]


def _normalize(value: str) -> str:
    """Compare Unicode names equally; retain original strings for SQL."""
    return unicodedata.normalize("NFC", value.casefold())


def _resolve(
    mailbox: str,
    paths: Iterable[str],
    *,
    subtree: bool,
    exclude: bool = False,
) -> list[str]:
    candidates = sorted(set(paths))
    # Preserve a copyable escape hatch when two distinct stored paths fold
    # to the same spelling. Identity operations must not silently union them.
    if mailbox in candidates and not exclude:
        return [mailbox]
    key = _normalize(mailbox)
    normalized = [(name, _normalize(name)) for name in candidates]
    exact = [name for name, value in normalized if value == key]
    if exact:
        if len(exact) > 1 and not exclude:
            raise AmbiguousMailboxError(mailbox, exact)
        return exact
    if subtree:
        children = [
            name for name, value in normalized if value.startswith(key + "/")
        ]
        if children:
            return children
    leaves = [
        name for name, value in normalized if value.rsplit("/", 1)[-1] == key
    ]
    if len(leaves) > 1 and not exclude:
        raise AmbiguousMailboxError(mailbox, leaves)
    return leaves


def resolve_for_search(
    mailbox: str, paths: Iterable[str], *, exclude: bool = False
) -> list[str]:
    """Exact path, then subtree, then unique leaf (union for exclusions)."""
    return _resolve(mailbox, paths, subtree=True, exclude=exclude)


def resolve_for_identity(mailbox: str, paths: Iterable[str]) -> list[str]:
    """Exact path or unique leaf only; never expand a parent to its subtree."""
    return _resolve(mailbox, paths, subtree=False)


def mailbox_predicate(
    column: str, paths: list[str], params: list, *, exclude: bool = False
) -> str:
    """Bind stored paths verbatim. No match is false, never an absent filter."""
    if not paths:
        return "1=1" if exclude else "1=0"
    params.extend(paths)
    placeholders = ", ".join("?" for _ in paths)
    operator = "NOT IN" if exclude else "IN"
    return f"{column} {operator} ({placeholders})"
