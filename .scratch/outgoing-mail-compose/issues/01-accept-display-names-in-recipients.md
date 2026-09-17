# Accept recipient display names in `send_email` (`Name <addr>`)

Status: resolved
Blocked by: none

## Problem

`send_email(to=["Light, Juliana @ San Diego <Juliana.Light@cbre.com>"])`
fails with `to: invalid address ... (expected a bare local@domain, no
display name)`. Drafts therefore show bare addresses; the caller cannot make
To/Cc/Bcc carry names.

## Root cause

`_validate_addresses` (`src/apple_mail_mcp/server.py` L1867-1909) forbids
whitespace and angle brackets on purpose: its docstring calls it the
injection boundary because addresses "end up in a header". Enforced by
`tests/test_write_send.py::TestValidation::test_display_name_form_rejected`
and `test_validate_addresses_helper`.

## Why it is safe to support now

Recipients are not concatenated into a header string. They are built as
structured JXA objects, `Mail.ToRecipient({address: a})` (server.py
L2006-2014), and every value reaches the script through `json.dumps()`
(`TestInjection` proves this). A `name` property encoded the same way keeps
the identical guarantee. The bare-address rule predates structured
recipients and can be narrowed to the address part only.

## Approach

1. Parse each entry with `email.utils.parseaddr` (or
   `email.headerregistry.Address` for stricter RFC 5322) into `(name, addr)`.
2. Run `addr` through the existing bare-address rules unchanged (`@` count,
   forbidden chars, control chars, non-empty local and domain).
3. Validate `name`: strip; reject CR/LF and control chars; reject `<` and
   `>`. Empty name means bare address.
4. Emit `Mail.ToRecipient({name: n, address: a})` (same for Cc/Bcc), with
   `name` omitted when empty.
5. Names containing a comma must be quoted by the caller
   (`"Light, Juliana @ San Diego" <a@b>`). An unquoted comma is an address
   separator in RFC 5322 and must be rejected, not guessed. Document this.

## Decision needed

Return shape. `SendResult.to/cc/bcc` are `list[str]` of bare addresses and
existing tests assert `result["cc"] == cc`. Options: (a) keep bare
addresses in `to/cc/bcc` (backward compatible) and add a `recipients`
field of `{name, address}`; (b) return the normalized `Name <addr>` string.
Recommend (a).

## Tests

- Flip `test_display_name_form_rejected` to an accepted case; every other
  rejection test stays green.
- New: quoted name containing a comma and an `@`; name with CR/LF rejected;
  address part still validated (`Name <a@@b>` rejected); script contains
  `Mail.ToRecipient({` with a `name` key; injection case where the name is
  `x"); Mail.quit(); ("` appears only as a JSON literal.

## Docs

Docstring, `docs/tools.md` (`send_email` at L319), CLAUDE.md tool table,
CHANGELOG `[Unreleased]`.

## Comments

### Implementation, 2026-09-16

Added strict structured recipient parsing shared by compose tools. Quoted
commas are accepted; malformed forms and raw/decoded control characters are
rejected. Bare-address validation remains unchanged. Live saved-draft and
`get_email` readback preserved `Fixture, Recipient`. Regression coverage:
`tests/test_write_send.py`. Delivery checks tracked in `../spec.md`.
