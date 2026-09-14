# Developer entry points. `just` lists them. Every recipe is a thin
# wrapper over uv/ruff/pytest so the underlying commands stay
# discoverable — no recipe hides behaviour.
#
# Inner loop:   just test tests/test_server.py      (one file, <1s)
#               just tf                             (rerun failures)
# Before push:  just check                          (= CI, ~6s)
# Release:      just release 0.5.0 [--push]

set shell := ["bash", "-euo", "pipefail", "-c"]

py_dirs := "src/ tests/"

_default:
    @just --list --unsorted

# One-time: locked deps + git hooks + global command bound to this checkout
setup: && hooks dev-link
    uv sync --locked --group dev --extra watch

# Install/relink the global development command (preserves the old executable)
dev-link:
    uv run --frozen python scripts/dev_link.py install

# Check that uv's global command is bound to this checkout
dev-status:
    uv run --frozen python scripts/dev_link.py status

# Restore the executable that preceded the development link
dev-unlink:
    uv run --frozen python scripts/dev_link.py uninstall

# ---- verify ---------------------------------------------------------

# ruff lint (src + tests)
lint:
    uv run --frozen ruff check {{py_dirs}}

# Auto-format + auto-fix lint
fmt:
    uv run --frozen ruff format {{py_dirs}}
    uv run --frozen ruff check --fix {{py_dirs}}

# Format check only (no writes) — what CI runs
fmt-check:
    uv run --frozen ruff format --check {{py_dirs}}

# Run tests; pass pytest args through (`just test tests/test_x.py -k foo`)
test *ARGS:
    uv run --frozen pytest -q {{ARGS}}

# Rerun only last failures, stop at first
tf:
    uv run --frozen pytest -q --lf -x

# Everything CI checks, in CI order. Green here == green CI.
check: lint fmt-check typecheck test

# Type check (ty, pinned in the dev group). Gate since 0.5.0.
# Pass paths to scope it: `just typecheck src/apple_mail_mcp/server.py`.
typecheck *PATHS="src/":
    uv run --frozen ty check {{PATHS}}

# Exercise the CLI against the real Mail.app (needs Full Disk Access)
smoke *ARGS:
    scripts/smoke.sh {{ARGS}}

# ---- run ------------------------------------------------------------

# Run the MCP server (args pass through: `just serve --watch`)
serve *ARGS:
    uv run --frozen apple-mail-mcp serve {{ARGS}}

# Build / refresh the search index
index *ARGS:
    uv run --frozen apple-mail-mcp index {{ARGS}}

# Index health
status:
    uv run --frozen apple-mail-mcp status

# Serve the docs site locally
docs:
    uv run --group docs zensical serve

# Competitive benchmarks (see benchmarks/)
bench *ARGS:
    uv run --group bench python -m benchmarks.run {{ARGS}}

# ---- ship -----------------------------------------------------------

# Bump versions, verify, commit, tag. `--push` to publish.
release VERSION *FLAGS:
    scripts/release.sh {{VERSION}} {{FLAGS}}

# Install repo git hooks (pre-commit: staged ruff; pre-push: just check)
hooks:
    git config core.hooksPath .githooks
    @echo "hooks: core.hooksPath=.githooks (undo: just unhook)"

# Remove repo git hooks
unhook:
    git config --unset core.hooksPath || true
