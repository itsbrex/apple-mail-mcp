#!/usr/bin/env bash
# Smoke test against the REAL Mail.app + index on this machine.
#
# The unit suite mocks every JXA call and never touches ~/Library/Mail,
# so it cannot tell you that a change broke the live path. This runs
# each read tool once through the CLI (same code as the MCP tools),
# checks for valid JSON + a sane shape, and prints timings.
#
#   just smoke              # all read tools
#   just smoke search       # one step (accounts|mailboxes|emails|search|read|status)
#   SMOKE_QUERY=invoice just smoke
#
# Needs: Full Disk Access for the terminal, Mail.app configured, an
# index (`just index`). Exit 1 on the first failing step.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
only="${1:-}"
query="${SMOKE_QUERY:-the}"
fail=0

run() {
    # run <name> <jq-assertion> <cmd...>
    local name="$1" assert="$2"; shift 2
    if [[ -n "$only" && "$only" != "$name" ]]; then return; fi
    local start end ms out
    start=$(python3 -c 'import time;print(int(time.time()*1000))')
    if ! out="$("$@" 2>&1)"; then
        printf '✗ %-10s command failed\n%s\n' "$name" "$out" >&2
        fail=1; return
    fi
    end=$(python3 -c 'import time;print(int(time.time()*1000))')
    ms=$((end - start))
    if ! jq -e "$assert" >/dev/null 2>&1 <<<"$out"; then
        printf '✗ %-10s %5dms  assertion failed: %s\n%s\n' \
            "$name" "$ms" "$assert" "$(head -c 400 <<<"$out")" >&2
        fail=1; return
    fi
    printf '✓ %-10s %5dms  %s\n' "$name" "$ms" "$(jq -c 'if type=="array" then length else (keys|join(",")) end' <<<"$out")"
}

cli() { uv run --frozen apple-mail-mcp "$@"; }

# `status` is human-formatted, not JSON: exit code + "Emails:" line only.
if [[ -z "$only" || "$only" == "status" ]]; then
    if out="$(cli status 2>&1)" && grep -q -i "email" <<<"$out"; then
        printf '✓ %-10s        %s\n' status "$(grep -i -m1 'email' <<<"$out" | tr -s ' ')"
    else
        printf '✗ %-10s no index? run `just index`\n%s\n' status "$out" >&2
        fail=1
    fi
fi

run accounts 'type=="array" and length>0 and .[0].name' cli accounts

# Target an explicit account so a stale APPLE_MAIL_DEFAULT_ACCOUNT in
# the local config can't masquerade as a code failure.
account="${SMOKE_ACCOUNT:-$(cli accounts | jq -r '.[0].name')}"
printf '  account: %s  (override: SMOKE_ACCOUNT=...)\n' "$account"

run mailboxes 'type=="array" and length>0 and .[0].name' \
    cli mailboxes --account "$account"
run emails   'type=="array" and length>0 and .[0].id' \
    cli emails --account "$account" --limit 3
run search   '(type=="array" and length>0) or (type=="object" and has("hint"))' \
    cli search "$query" --limit 3

# read: take the first id from `emails` and fetch it fully.
if [[ -z "$only" || "$only" == "read" ]]; then
    id="$(cli emails --account "$account" --limit 1 | jq -r '.[0].id // empty')"
    if [[ -n "$id" ]]; then
        run read 'has("subject") and has("content")' \
            cli read "$id" --account "$account" --mailbox INBOX
    else
        printf '✗ %-10s no message id available from `emails`\n' read >&2
        fail=1
    fi
fi

exit "$fail"
