#!/usr/bin/env bash
# PostToolUse hook (Edit|Write): format + auto-fix the one Python file
# that was just touched. ~100ms. Silent when clean; unfixable findings
# go back to the agent via exit 2 so they are handled now, not at
# `just check` time.
set -uo pipefail

payload="$(cat)"
file="$(jq -r '.tool_input.file_path // empty' <<<"$payload")"

case "$file" in
    */src/apple_mail_mcp/*.py|*/tests/*.py) ;;
    *) exit 0 ;;
esac
[[ -f "$file" ]] || exit 0

cd "$(git -C "$(dirname "$file")" rev-parse --show-toplevel)" || exit 0

uv run --frozen ruff format --quiet "$file" 2>/dev/null
if ! out="$(uv run --frozen ruff check --fix --quiet --output-format=concise "$file" 2>&1)"; then
    printf 'ruff (unfixable) in %s:\n%s\n' "${file#"$PWD"/}" "$out" >&2
    exit 2
fi
exit 0
