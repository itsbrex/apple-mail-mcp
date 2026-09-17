# Outgoing mail: threaded replies, recipient display names, draft/send separation

Created: 2026-09-16

## Problem

A client drafting a reply to an existing thread through a tool gateway hit
these gaps in the write path, in one sitting:

1. `send_email` rejects any recipient carrying a display name
   (`Name <addr>`), so drafts show bare addresses instead of names.
2. There is no reply tool. `send_email` composes a new outgoing email only:
   no `In-Reply-To`/`References`, no quoted original, no reply-all
   recipient derivation. A "reply" built with it lands as a standalone
   message in the recipient's client.
3. The single `send_email` name covers both saving a draft and sending. A
   gateway classifying tools by name (Toolport, live) intercepted the
   harmless draft path (`confirm=false`) as destructive and forced a human
   confirm.
4. The full-email response from `get_email` has no `to`/`cc`, so a client
   cannot derive reply-all recipients without scraping quoted headers out of
   the body.
5. A saved draft's email reference is not returned, so a repeated call
   silently creates a duplicate the caller cannot find or remove.

## Grounding (from the code, not memory)

- Validation boundary: `_validate_addresses`, `src/apple_mail_mcp/server.py`
  L1867-1909. A deliberate injection boundary; enforced by
  `tests/test_write_send.py::TestValidation::test_display_name_form_rejected`
  and `test_validate_addresses_helper`.
- Compose path: `send_email`, server.py L1912-2047. Recipients are structured
  `Mail.ToRecipient({address})` objects (L2006-2014); every value enters the
  JXA script via `json.dumps()` (verified by `TestInjection`). The draft/send
  decision is `msg.save()` vs `msg.send()` (L1985-1993).
- No threading anywhere in the write path: `codedb search "In-Reply-To"`
  returns nothing. `_ensure_writable` (server.py L126-139) already names
  "reply, forward" as anticipated write tools.
- Read side already exposes what a reply needs: `get_email` returns the
  Internet Message-ID as `message_id`; JXA has `MailCore.getMessageById()`
  (`src/apple_mail_mcp/jxa/mail_core.js` L144).
- 11 registered tools in server.py: get_attachment (deprecated), get_email,
  get_email_attachment, get_email_links, get_emails, list_accounts,
  list_mailboxes, move_email, search, send_email, update_email_status. No
  MCP tool annotations are set on any of them.
- Domain (CONTEXT.md): a Draft is a mail change (so read-only mode must
  keep blocking it); Send confirmation authorizes a newly composed email
  only. ADR-0001 records that `message_id` means a numeric Mail message ID
  in tool inputs and an Internet Message-ID in the full-email response.

## Scope

Six tickets under `issues/`. Each is independently shippable; none blocks
another. Suggested order: 05 (smallest, addresses the gateway interception
directly), 01, 03, 02, 04, 06.

## Non-goals

- Sending a previously saved draft (a new capability; 06 is the enabler).
- Forward. Same shape as reply; add after 02 lands.
- HTML bodies.

## Implementation decisions and verification

The six issues are implemented together: draft-only tools reuse the same
validation/composition paths as the compatible draft-by-default send tools.
`reply_draft` has no confirmation argument; `reply_email` sends only with
`confirm=True`. Names with commas require quoting. Recipient response fields
retain bare address lists and add structured names/addresses separately.

Native replies use an account/mailbox-scoped numeric source ID. Mail derives
headers and recipients; the original is re-quoted as plain text. Mail 16's
JXA rich-text setter was ineffective, so a constant AppleScript handler
receives typed Apple-event descriptors and verifies the applied body.
Draft references come only from a unique, matching saved mailbox message;
unknown references and threading stay explicitly unconfirmed.

Live synthetic fixtures verified a named draft, native reply-all, preserved
body/original text, recipient readback, saved numeric IDs, and matching
`In-Reply-To`. No transmission was attempted. Core helper regression tests
use fake Mail/Foundation objects in macOS's built-in JXA runtime; Linux
retains the mocked Python and generated-script coverage.

Delivery checklist (authoritative for these six issues):

- [x] Implement issues 01–06 and targeted regression coverage.
- [x] Verify native behavior using disposable synthetic messages.
- [x] Run full `just check` (712 tests) and all six read-only live smoke steps.
- [ ] Complete separate standards/spec reviews and address findings.
- [ ] Commit local issue-tracker conventions and completed issue records.
- [ ] Commit compose/readback implementation, tests, and public documentation.
- [ ] Build distribution and refresh/verify `just dev-link`.

The unrelated `docs/plans/index.html` timestamp and existing stash remain
outside this work. No release, tag, push, or registry install is requested.
