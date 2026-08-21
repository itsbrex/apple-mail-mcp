---
name: write-tool
description: Add a mutating MCP tool (mark read/unread, flag, move/archive/trash, send, reply, forward, create draft) to server.py following the repo's safety and doc contracts. Use whenever the task adds or changes a tool that writes to Apple Mail.
---

# Adding a write tool

**Entry:** the task adds/changes an MCP tool that mutates mail state.
**Exit:** `just check` green and the checklist below fully ticked.
Upstream specs: issues #22 (send), #64 (`update_email_status`), #65
(`move_email`) on imdinu/apple-mail-mcp — consolidated tools over one
tool per verb.

## Contract (each item is enforced by a test or a hook)

1. **Name** starts with a write prefix (`mark_`, `move_`, `send_`,
   `reply_`, `forward_`, `delete_`, `create_`, `update_`, `set_`,
   `archive_`, `trash_`, `flag_`, `unflag_`). The AST test
   `TestWriteImplyingToolsHaveGuard` keys off this.
2. **First statement** is `_ensure_writable()` (read-only mode, #80).
3. **Hidden-account gate** before any JXA: `if _hidden_account(account):
   raise ValueError(...)` — never fall through to `Mail.accounts()[0]`;
   resolve with `await _resolve_visible_account(account)` (#90).
4. **JXA via `execute_with_core_async(script)`**; every string reaches
   the script through `json.dumps()`; use `MailCore.getAccount` /
   `MailCore.getMailbox` (alias-aware) and `MailCore.batchFetch` for
   reads. Never loop `msg.prop()` per message.
5. **Bounded batch**: list params capped (`MAX_WRITE_BATCH = 10`),
   clamp-don't-raise like `_validate_pagination`.
6. **Return the new state**, not `{"success": true}` — e.g. `{"id",
   "read", "flagged"}` or `{"id", "mailbox"}` — so the model can verify.
7. **Index coherence**: if the tool moves/deletes a message, the watcher
   picks up the `.emlx` move; if it changes read/flagged only, no index
   write is needed (flags live in the plist footer / Envelope Index).
   Say which in the docstring.
8. **Send/draft**: default to creating a draft and returning its id;
   actual send requires an explicit `confirm=True` param (#22 safety).

## Files to touch (the drift test names stragglers)

- `src/apple_mail_mcp/server.py` — the tool. Module docstring
  `TOOLS (N total)` count.
- `tests/test_server.py` — (a) read-only raises `PermissionError`,
  (b) hidden account never calls JXA, (c) happy path with
  `execute_with_core_async` mocked, asserting the script text contains
  the json-dumped args, (d) batch clamp.
- `src/apple_mail_mcp/cli.py` — matching CLI command (all tools have one).
- `README.md`, `CLAUDE.md`, `docs/tools.md` — tool table row + count;
  `docs/index.md`, `docs/getting-started.md`, `docs/architecture.md` —
  count only. `tests/test_release_metadata.py` fails until all agree.
- `CHANGELOG.md` — entry under `## [Unreleased]` (what + why + issue #).

## Verify

```bash
just check                       # lint + format + 500+ tests, ~5s
SMOKE_ACCOUNT=iCloud just smoke  # read tools still work live (optional)
```

For a live check of the new tool, run its CLI command against a
throwaway message in a test mailbox — never against INBOX defaults.
Stop when `just check` is green and the CHANGELOG entry is written; do
not refactor neighbouring tools.
