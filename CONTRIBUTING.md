# Contributing to Apple Mail MCP

Thanks for your interest in contributing! This guide will help you get started.

## Development Setup

1. **Prerequisites**: macOS with Apple Mail configured, Python 3.11+, [uv](https://docs.astral.sh/uv/), [just](https://just.systems) (`brew install just`)

2. **Clone and install** (deps + git hooks):
   ```bash
   git clone https://github.com/imdinu/apple-mail-mcp.git
   cd apple-mail-mcp
   just setup
   ```

3. **Run the checks** — this is exactly what CI runs, in ~5s:
   ```bash
   just check
   ```

4. **Optional — build the index and smoke-test against your real Mail.app**
   (requires Full Disk Access for your terminal):
   ```bash
   just index
   just smoke
   ```

`just` (no args) lists every recipe. Each one is a one-line wrapper
over `uv run …`, so the raw commands stay visible in the `justfile`.

## Project Structure

```
src/apple_mail_mcp/
├── server.py           # MCP tools (the public API)
├── builders.py         # JXA script construction
├── executor.py         # osascript execution
├── index/
│   ├── disk.py         # .emlx file parsing
│   ├── manager.py      # IndexManager (SQLite index)
│   ├── search.py       # FTS5 search
│   ├── sync.py         # Disk-based state reconciliation
│   └── watcher.py      # Real-time file watcher
└── jxa/
    └── mail_core.js    # Shared JXA utilities
```

## Making Changes

### Branching

- Create a feature branch from `main`: `git checkout -b feat/your-feature`
- Keep branches short-lived and focused on a single change

### Code Style

- `just fmt` formats and auto-fixes; `just lint` checks (ruff, `src/` + `tests/`)
- Line length: 80 characters
- Type hints required (Python 3.11+ syntax)

The `pre-commit` hook installed by `just setup` runs ruff on the staged
files only (<1s); `pre-push` runs `just check`. Bypass once with
`--no-verify`; remove with `just unhook`.

### Testing

All changes should include tests.

```bash
just test tests/test_server.py -k "read_only"   # inner loop, <1s
just tf                                         # rerun last failures
just check                                      # lint + format + full suite (= CI)
```

Tests use `pytest` with `pytest-asyncio`. The suite mocks JXA and stubs
the real `~/Library/Mail`, so it runs in ~3s without Apple Mail. A test
that needs `find_mail_directory()` for real (against a sandboxed
`Path.home`) opts in with `@pytest.mark.real_mail_dir`.

`tests/test_release_metadata.py` fails when `pyproject.toml` /
`server.json` versions diverge, when `CHANGELOG.md` lacks a section for
the current version, or when the tool roster in `server.py` no longer
matches the counts and tables in README / CLAUDE.md / docs. Its
message names the files to fix.

### Adding a write tool

Mutating tools (mark read, flag, move, send, …) follow the contract in
`.claude/skills/write-tool/SKILL.md`: `_ensure_writable()` first
(enforced by an AST test), hidden-account gate, `json.dumps()` for
every string entering JXA, bounded batches, new state in the return
value, plus a CLI command, tests, docs rows, and a CHANGELOG entry.

### Architecture Notes

- **`server.py`** contains the 8 MCP tools and 1 resource (`index://status`) — this is the public API surface. Changes here affect what LLMs see and call.
- **`get_email()` uses a strategy cascade**: Strategy 0 (disk) → Strategy 1 (JXA specified mailbox) → Strategy 2 (index lookup) → Strategy 3 (iterate all). Each must return the same response schema.
- **`parse_emlx()`** in `disk.py` handles the `.emlx` format: byte count line, MIME content, plist footer. The plist footer contains Apple Mail metadata (flags bitmask, date-received timestamp).
- **JXA scripts must use batch property fetching** via `MailCore.batchFetch()` — never iterate messages individually (87x performance difference).

## Submitting a PR

1. Ensure `just check` passes (same commands as CI)
2. Write a clear PR description explaining *what* and *why*
3. Keep the diff focused — avoid unrelated changes in the same PR
4. PRs are typically squash-merged into `main`

## Reporting Issues

Open an issue on [GitHub](https://github.com/imdinu/apple-mail-mcp/issues) with:
- What you expected vs what happened
- macOS version and Mail.app configuration (number of accounts, rough mailbox sizes)
- Any error output or logs

## License

By contributing, you agree that your contributions will be licensed under the [GPL-3.0](LICENSE) license.
