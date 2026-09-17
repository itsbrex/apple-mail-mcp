# Add MCP tool annotations (`destructiveHint`, `readOnlyHint`) to every tool

Status: resolved
Blocked by: none

## Problem

Gateways and agents currently guess a tool's risk from its name. Toolport
classified `send_email` as destructive from the name and intercepted the
draft path. The MCP spec provides tool annotations for exactly this:
`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`. None
are set on this server's tools (`grep annotations server.py` finds only the
`__future__` import).

## Approach

FastMCP (`fastmcp>=3.4.7`, pyproject L43) accepts `annotations=` on
`@mcp.tool`. Set them on all 11 registered tools (live list from
`grep "^@mcp.tool" src/apple_mail_mcp/server.py`):

| Tool | readOnly | destructive | idempotent |
| --- | --- | --- | --- |
| list_accounts, list_mailboxes, search, get_emails, get_email, get_email_links, get_email_attachment, get_attachment (deprecated) | true | false | true |
| update_email_status | false | false | true |
| move_email | false | false | false |
| send_email | false | true | false |
| create_draft (ticket 03), reply draft path (ticket 02) | false | false | false |

`move_email` to Trash is a mailbox move, not a permanent deletion, per the
CONTEXT.md glossary; `destructiveHint` stays false. Reconsider if a
permanent-delete tool is ever added. `get_attachment` writes to the
attachment cache on disk but not to mail state; treat as read-only for
mail purposes and note it.

This is the smallest ticket in the batch and directly removes the need for
name-based guessing; ship it first.

## Tests

Extend `tests/test_mcp_registration.py` to assert every registered tool has
annotations, and that every tool calling `_ensure_writable` has
`readOnlyHint=false` (ties into the existing write-name regression scan in
`tests/test_server.py`).

## Docs

One paragraph in `docs/tools.md` explaining the hints; CHANGELOG.

## Comments

### Implementation, 2026-09-16

All 14 tools now declare read-only, destructive, idempotent, and open-world
hints. Lazy registration forwards annotations without importing FastMCP
early. Draft-only tools remain writes but are marked non-destructive; send
capabilities remain destructive. Hints are advisory and do not bypass
read-only or hidden-account gates. Regression coverage:
`tests/test_mcp_registration.py`. Delivery checks tracked in `../spec.md`.
