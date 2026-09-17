# Return the saved draft's email reference from every compose tool

Status: resolved
Blocked by: none

## Problem

A successful draft returns only `{status, account, to, cc, bcc, subject}`.
There is no handle to the email that was just created. Consequences seen
live:

- Calling the same draft twice creates two identical drafts in Drafts and
  the caller has no way to find or remove the duplicate.
- A client cannot follow up on the draft it made: no update, no delete, no
  "send this one now". CONTEXT.md is explicit that Send confirmation "does
  not select or send a previously saved draft", so today the only path
  from draft to sent is the user doing it by hand in Mail.app.
- For ticket 02, `threaded` can only be confirmed by reading the saved
  draft back, which requires locating it.

## Grounding

- `SendResult` TypedDict, server.py L1598-1606.
- `msg.save()` in the compose script (L1993) returns nothing today; the
  JXA `OutgoingMessage` created via `Mail.OutgoingMessage({...})` and
  pushed to `Mail.outgoingMessages` (L1999-2005) can be queried for its
  id after save.
- ADR-0001: an email reference is `(account, mailbox, Mail message ID)`.
  A bare numeric id is not a complete identity.

## Approach

After `save()`, resolve the draft's email reference and return it:

    "draft": {"account": "...", "mailbox": "Drafts", "message_id": 12345}

using the numeric Mail message ID (matching every other tool input and
ADR-0001's spelling for inputs). Nest it under a `draft` key rather than
adding a top-level `message_id`, which ADR-0001 already flags as ambiguous
in responses.

Verify live how the id becomes available: whether `msg.id()` is populated
immediately after `save()`, or whether the saved message must be located
in the account's Drafts mailbox (the existing "server-stored Drafts can take
a few seconds to list" caveat at L1929-1930 suggests a short poll or an
`"unconfirmed"` value may be needed, as ticket 02 already proposes for
`threaded`).

Apply to `send_email` (draft path), `create_draft` (ticket 03), and
`reply_email` (ticket 02). On `status: "sent"` return `draft: null`; a sent
message's reference is a separate concern.

## Enables (future, not in scope)

A `send_draft(account, mailbox, message_id)` tool that sends a previously
saved draft. That would require a new glossary term and a fresh
Send-confirmation model in CONTEXT.md, so it is its own spec.

## Tests

`tests/test_write_send.py`: draft result carries `draft.account`,
`draft.mailbox == "Drafts"`, and an int `draft.message_id`; sent result
carries `draft: null`; the mocked JXA return shape is updated in
`_draft_result` (L27).

## Docs

`docs/tools.md` return shapes for the three compose tools; CHANGELOG.

## Comments

### Implementation, 2026-09-16

Draft composition snapshots scoped Drafts IDs before creating mail, then
polls for one new message matching subject, body, sender and recipients.
Positive saved IDs are returned with account and mailbox. Outgoing IDs
(observed as `0` in the spike) are never used as handles. Ambiguous/missing
readback stays null/unconfirmed; sends return null/not_applicable. Live
named-draft and reply references both worked with `get_email`. Regression
coverage: `tests/test_write_compose.py`, `tests/test_jxa_compose.py`.
Delivery checks tracked in `../spec.md`.
