---
status: accepted
---

# Scope indexed email identity by account and mailbox

Retrospective record of the existing identity model.

## Context

Mail message IDs are mailbox-local, so a numeric ID alone cannot distinguish
emails in different locations. Disk inventory identifies accounts by UUID,
while callers usually name accounts by their human-readable names.

## Decision

Identify an indexed email by `(account UUID, mailbox, Mail message ID)`.
Keep account UUIDs in the index so disk and index inventories use the same
identity for reconciliation; translate account names at the access boundary.
This accepts scoped lookups and name translation in exchange for preserving
distinct mailbox entries and avoiding repeated re-indexing caused by
incompatible account keys.

## Consequences

Copies in different mailboxes remain distinct even when they share an
Internet Message-ID. A mailbox move changes the location component of an
email reference, so the former reference can become stale. Changing this
model affects persisted identity, reconciliation, and lookup callers.

This records index identity, not a guarantee that every public lookup
requires full scope: account and mailbox remain optional in several tools.
The existing `message_id` spelling also has two meanings: a numeric Mail
message ID in tool inputs and index rows, but an Internet Message-ID in a
full-email response. Use the [glossary](../../CONTEXT.md) to distinguish
these fields.

## Evidence

- [Schema and composite identity](../../src/apple_mail_mcp/index/schema.py)
- [Duplicate-ID regression coverage](../../tests/test_schema.py)
- [Account-name translation](../../src/apple_mail_mcp/index/accounts.py)
- [Reconciliation rationale](../search.md#account-uuids-vs-friendly-names)
- [Tool inputs and full-email response](../../src/apple_mail_mcp/server.py)
