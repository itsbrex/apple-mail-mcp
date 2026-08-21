---
name: jxa-debug
description: Diagnose a failing JXA/osascript path (error -1728 "Can't get object", -1700, timeouts, empty results from a live tool) by isolating the script outside the server. Use when a Mail.app-backed tool or smoke step fails and unit tests (which mock JXA) are green.
---

# Debugging a JXA failure

**Entry:** a live tool/CLI/smoke step fails; `just check` is green.
**Exit:** root cause stated as *config / Mail.app state / script bug*
with the one-line evidence, and a fix or a documented limitation.

## Triage order (cheapest first)

1. **Is it config?** `uv run apple-mail-mcp accounts` — does the
   account in the error exist *exactly* (case, dashes, en-dash)?
   A stale `APPLE_MAIL_DEFAULT_ACCOUNT` in `~/.apple-mail-mcp/config.toml`
   produces `Can't get object (-1728)` and `Mailbox 'INBOX' not found`.
   Fix: `SMOKE_ACCOUNT=<real name>` / correct the config. Not a code bug.
2. **Is it the mailbox name?** `uv run apple-mail-mcp mailboxes
   --account "<name>"`. Gmail has no `INBOX` mailbox object under some
   configurations; Exchange uses `Inbox`. `MailCore.getMailbox` already
   tries aliases — if the name is not in that list, add it to the
   alias groups in `src/apple_mail_mcp/jxa/mail_core.js`.
3. **Run the script directly.** Dump what the builder generates and
   run it under osascript with the same core prelude:

   ```bash
   uv run python - <<'EOF'
   from apple_mail_mcp.builders import AccountsQueryBuilder
   from apple_mail_mcp.jxa import MAIL_CORE_JS
   script = AccountsQueryBuilder().list_mailboxes("iCloud")
   open("/tmp/probe.js", "w").write(MAIL_CORE_JS + "\n" + script)
   EOF
   osascript -l JavaScript /tmp/probe.js | head -c 600
   ```

   Error codes: `-1728` object doesn't exist (name/ID wrong);
   `-1700` type coercion (you passed a JS value where Mail expects an
   object); `-600`/`-609` Mail.app not running / no connection;
   hang → Mail.app has a modal dialog open.
4. **Timeouts:** per-message property access is the usual cause
   (87x slower than `MailCore.batchFetch`). Check the builder output
   for `.sender()` / `.subject()` inside a loop.
5. **Empty results from `get_emails`:** the Envelope Index fast path
   returns `[]` silently only for unknown-mailbox cases it should have
   raised `MailboxNotFoundError` for — see `index/envelope_direct.py`
   and #102 in CHANGELOG.

Report: `cause: <config|state|script> — <evidence line>` then the fix.
Do not add retries or broad `except Exception` to make a symptom go
away.
