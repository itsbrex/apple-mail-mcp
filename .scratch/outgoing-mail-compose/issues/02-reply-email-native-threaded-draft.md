# Add `reply_email`: native threaded reply (reply / reply-all) as a draft

Status: resolved
Blocked by: none

## Problem

There is no way to reply to an existing email. `send_email` composes a new
outgoing email only: no `In-Reply-To`/`References`, no quoted original, no
derived reply-all recipients. A reply built with it lands as a standalone
message in the recipient's client instead of inside the thread, even with a
matching `RE:` subject and identical recipients.

## Grounding

- `codedb search "In-Reply-To"` finds nothing in the write path.
- `_ensure_writable` (server.py L126-139) already lists "reply, forward" as
  anticipated write tools. The regression test in `tests/test_server.py`
  scans the module for write-implying tool names and asserts they call it
  first; `reply_email` will be caught, so `_ensure_writable()` must be its
  first line.
- The read side already has what a reply needs: `get_email` returns the
  Internet Message-ID as `message_id`; `MailCore.getMessageById()` exists
  (`src/apple_mail_mcp/jxa/mail_core.js` L144, `Mail.messages.byId`).
- Error mapping to reuse: "message not found with id" and "-1728" handling
  at server.py L1841-1850.

## Approach (recommended): Mail.app's native reply command

Ask Mail to build the reply so headers, quoting, and recipients match what
Mail itself produces. Do not forge headers.

    const src = MailCore.getMessageById(<id>);
    const msg = src.reply({openingWindow: false, replyToAll: <bool>});
    msg.content = <body> + <existing quoted content>;
    msg.visible = false;
    msg.save();   // or msg.send() when confirm=true

`OutgoingMessage` in the Mail JXA dictionary does not expose arbitrary
headers, so building the reply by hand and setting `In-Reply-To` is not a
viable fallback. Native reply is the path.

## Spike required before implementation

Verify live on the pinned platform (Mail 16.0 / macOS 26.6, per the comment
at server.py L1980-1983):

1. `message.reply({openingWindow:false})` returns an `OutgoingMessage`
   without opening a compose window.
2. `content` can be set on it and the quoted original survives (or must be
   re-appended; capture which).
3. `save()` lands it in the account's Drafts and the saved draft carries
   `In-Reply-To`.
4. `replyToAll:true` excludes the sending account's own address.
5. `Mail.messages.byId()` resolution across accounts; whether an email
   reference (account + mailbox, per ADR-0001) is needed to disambiguate.

Record findings under Comments before coding.

## Interface

    reply_email(
        message_id: int,             # numeric Mail message ID (glossary), NOT Internet Message-ID
        body: str,
        account: str | None = None,  # email reference scoping, per ADR-0001
        mailbox: str | None = None,
        reply_all: bool = False,
        confirm: bool = False,       # False = draft (default), True = send
    ) -> ReplyResult

`ReplyResult`: `status` (draft|sent), `account`, `to`, `cc`, `subject`,
`in_reply_to` (Internet Message-ID of the source), `threaded` (true when
the saved draft was read back and carries In-Reply-To; false or
"unconfirmed" otherwise). Do not add a `message_id` field to the result;
ADR-0001 already flags that spelling as ambiguous.

Whether the draft path lives inside `reply_email` via `confirm` or in a
separate `reply_draft` is decided once in ticket 03 and applied here.

## Tests

Mirror `tests/test_write_send.py`: read-only gate; hidden account; body and
account are JSON literals in the script; `replyToAll` reaches the script;
draft vs send selects `save()` vs `send()`; unknown id maps to "Message N
not found."; result exposes `in_reply_to` and `threaded`.

## Docs

`docs/tools.md` new section; CLAUDE.md "MCP Tools (11 total)" count and
table; CHANGELOG `[Unreleased]`; CONTEXT.md gains a `Reply` term (the
glossary has Draft, Send confirmation, and Sent status, but no Reply).

## Comments

### Implementation spike, 2026-09-16

- Mail 16.0's installed `Mail.sdef` and Apple's WWDC 2014 JXA example
  confirm `reply({openingWindow:false, replyToAll:true})` returns an outgoing
  message. Production lookups will use the account/mailbox reference;
  `Mail.messages` failed with `-1728` on this host.
- A disposable synthetic draft returned outgoing ID `0`; its saved mailbox
  message had a different positive ID. Never return the outgoing ID.
- The iCloud account is disabled. Mail silently substituted its active
  default sender during the fixture. Composition must reject disabled
  accounts before mutation and verify the selected sender before save/send.
- After moving the synthetic source to its dedicated test mailbox, Mail's
  account APIs stalled. The attempted native-reply spike timed out; quote
  preservation, reply-all and saved threading are not yet live-confirmed.
  No message was sent. Readback will report `threaded: "unconfirmed"` unless
  the saved MIME header verifies the source Internet Message-ID.
- Decision: add `reply_draft` without a send option; keep `reply_email`
  draft-by-default with explicit `confirm=True`, matching `send_email`.

### Completed native spike and implementation, 2026-09-16

The earlier unconfirmed results above were superseded by an imported,
synthetic inbound fixture in a dedicated mailbox on an enabled account.
Native invisible reply-all derived the external sender and Cc peer while
excluding the account's own address. A normal Mail quit/relaunch recovered
the earlier stalled Apple-event state; no force quit or account change was
used.

Mail 16 ignored JXA reply-content assignment. Reading uninitialized reply
rich text before the native setter also caused stale empty content. The
working path uses a constant AppleScript handler with typed descriptors,
sets content before reading it, and re-appends a plain-text source quote.
It verifies the applied body before save/send. Caller text never becomes
AppleScript source. The saved MIME body contained both requested Unicode
text and original content; the saved `In-Reply-To` matched the source
Internet Message-ID. Public `reply_draft` returned `threaded: true` and a
confirmed saved reference, and `get_email` verified body and To/Cc.

No message was sent. Send-mode script selection is covered with mocks;
native delivery is outside this verification. Regression coverage:
`tests/test_write_reply.py`, `tests/test_jxa_compose.py`, and
`tests/test_cli_compose.py`. Delivery checks tracked in `../spec.md`.
