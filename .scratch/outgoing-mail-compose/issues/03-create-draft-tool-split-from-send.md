# Add `create_draft` so drafting is not classified as a destructive send

Status: needs-triage
Blocked by: none

## Problem

One tool name, `send_email`, covers both saving a draft (`confirm=false`)
and sending (`confirm=true`). A gateway that classifies tools by name
(Toolport, live) intercepts the harmless draft call as destructive and
forces a human confirmation on every draft. The `confirm` flag also misreads
easily: `confirm=false` sounds like "preview only", but it writes.

## Domain check

CONTEXT.md defines Draft as "an unsent outgoing email saved in Apple Mail;
creating a draft is a mail change even though delivery has not been
requested." So a draft is a write and must stay behind `_ensure_writable`
(read-only mode keeps blocking it). What it is not is destructive or
irreversible. The split is destructive-vs-write, not write-vs-read. Ticket
05 adds the machine-readable hint for the same distinction.

## Approach

Add `create_draft(to, subject, body, cc=None, bcc=None, account=None)`:

- No `confirm` parameter. Always `msg.save()`. The script contains no
  `send()` call, matching the guarantee stated at server.py L1975-1978.
- Returns `{"status": "draft", ...}` (extend with the email reference from
  ticket 06 when that lands).
- Factor the shared validate-and-build-script code out of `send_email` so
  both tools share one path and `TestInjection` covers both.

Keep `send_email` unchanged this release. `TestDraftVsSend` relies on
draft-by-default; do not break it now.

## Decision needed

Deprecation of the draft path inside `send_email`. Options: (a) leave it
and document `create_draft` as the preferred entry point; (b) mark
`confirm=false` on `send_email` deprecated in the docstring and remove it in
the next major, making `send_email` send-only. Recommend (a) now, (b) as a
follow-up ticket once `create_draft` has shipped.

Same shape for `reply_email` (ticket 02): draft by default via `confirm`,
or a separate `reply_draft`? Decide once, apply to both.

## Tests

- `create_draft` calls `_ensure_writable()` first; the write-name
  regression scan in `tests/test_server.py` must include it.
- Script contains `msg.save()` and never `msg.send()`.
- Reuse the validation and injection cases from `tests/test_write_send.py`
  against the shared builder.

## Docs

`docs/tools.md`, CLAUDE.md tool table and count, CHANGELOG `[Unreleased]`.

## Comments

### Implementation, 2026-09-16

Added `create_draft` and `reply_draft`, both without a `confirm` argument.
`send_email` and `reply_email` retain draft-by-default compatibility. Shared
validation/build helpers produce draft scripts without a send instruction.
CLI twins are `draft` and `reply-draft`; stdin bodies work through `-b -`.
Regression coverage: `tests/test_write_compose.py`, `tests/test_cli_compose.py`.
Delivery checks tracked in `../spec.md`.
