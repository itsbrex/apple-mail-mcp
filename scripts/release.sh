#!/usr/bin/env bash
# Cut a release: bump version in every file that carries it, verify the
# CHANGELOG has an entry, commit, tag. Push is explicit (--push) so the
# irreversible step (CI → PyPI → GitHub Release → MCP registry) is never
# a side effect.
#
#   scripts/release.sh 0.5.0          # bump + commit + tag, print push cmd
#   scripts/release.sh 0.5.0 --push   # ...and push main + tag
#
# Collapses the 4-step manual checklist in CLAUDE.md "Releasing".
set -euo pipefail

version="${1:-}"
push="${2:-}"

die() { printf 'release: %s\n' "$*" >&2; exit 1; }

[[ -n "$version" ]] || die "usage: scripts/release.sh X.Y.Z [--push]"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version must be X.Y.Z, got '$version'"

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

branch="$(git rev-parse --abbrev-ref HEAD)"
[[ "$branch" == "main" ]] || die "release from main (on '$branch')"
[[ -z "$(git status --porcelain)" ]] || die "working tree not clean"
git fetch -q origin main
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] \
    || die "main is not in sync with origin/main (pull or push first)"
git rev-parse -q --verify "refs/tags/v$version" >/dev/null \
    && die "tag v$version already exists"

grep -q "^## \[$version\]" CHANGELOG.md \
    || die "CHANGELOG.md has no '## [$version]' section — add it first"

current="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)"
[[ "$current" != "$version" ]] || die "pyproject.toml is already $version"

# Bump every version carrier. tests/test_release_metadata.py asserts
# these stay in lockstep, so a missed file fails `just check`.
sed -i '' "s/^version = \"$current\"/version = \"$version\"/" pyproject.toml
sed -i '' "s/\"version\": \"$current\"/\"version\": \"$version\"/g" server.json

uv lock -q

# Full local CI mirror (~5s). Includes the version/changelog lockstep
# guards in tests/test_release_metadata.py.
just check

git add pyproject.toml server.json uv.lock
git commit -q -m "Bump version to $version"
git tag "v$version"

printf 'release: committed + tagged v%s\n' "$version"
if [[ "$push" == "--push" ]]; then
    git push origin main "v$version"
    printf 'release: pushed — watch https://github.com/imdinu/apple-mail-mcp/actions\n'
else
    printf 'release: to publish, run:\n  git push origin main v%s\n' "$version"
fi
