# `get_email` should return `to` and `cc` recipients

Status: resolved
Blocked by: none

## Problem

The full-email response carries `sender`, `reply_to`, and the Internet
Message-ID (`message_id`) but no `to` or `cc`. A client that wants to
reply-all, or just confirm who was on a thread, has to scrape the quoted
`To:`/`Cc:` lines out of the body. That is exactly what was required to
rebuild the recipient list for a reply-draft.

## Grounding

- JXA field map in `src/apple_mail_mcp/builders.py` L22-46 already includes
  `reply_to -> replyTo` and `message_id -> messageId`; `toRecipients` and
  `ccRecipients` are absent.
- Disk (Strategy 0) header parsing in `src/apple_mail_mcp/index/disk.py`
  L426-431 decodes `Reply-To`; `To` and `Cc` are not decoded.
- `docs/architecture.md` L141: all strategies must return an identical
  response schema. Any new field lands in every strategy.
- ADR-0001 records that `message_id` in this response is the Internet
  Message-ID. Keep that; do not add a second `message_id`.

## Approach

Add `to: list[Recipient]` and `cc: list[Recipient]` to the full-email
response, where `Recipient` is `{name: str, address: str}`. Structured
name+address here pairs with ticket 01's input format, so a client can
round-trip recipients without reformatting.

- JXA path: read `toRecipients.name()` / `.address()` and
  `ccRecipients.name()` / `.address()`; add both to the builders map.
- Disk path: decode `To` and `Cc` with `email.utils.getaddresses` after
  `make_header(decode_header(...))`, matching the `Reply-To` treatment.
- Consider `references` and `in_reply_to` (lists of Internet Message-IDs)
  in the same change; cheap once the headers are being read, and they let
  a client locate the parent of a thread.

Leave `bcc` out: it is absent on received mail, and adding it only for the
Sent mailbox is a separate decision.

## Tests

`tests/test_builders.py` (field map), `tests/test_disk.py` (header decode
including RFC 2047 names), `tests/test_server.py` (response shape),
`tests/test_strategy_equivalence.py` (both strategies agree).

## Docs

`docs/tools.md` L116 (`get_email` returns); CLAUDE.md L166; CHANGELOG.

## Comments

### Implementation, 2026-09-16

Added structured To/Cc recipients to disk parsing and every JXA full-email
strategy. RFC2047 names are decoded after address parsing so encoded commas
do not split recipients. Empty headers yield empty arrays. Strategy parity
and live saved-draft readback passed. Regression coverage:
`tests/test_disk.py`, `tests/test_builders.py`, and
`tests/test_strategy_equivalence.py`. Delivery checks tracked in `../spec.md`.
