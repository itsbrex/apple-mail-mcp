# Installation

**Using this fork:** plugin, bundle, and PyPI installs run the upstream
release, which does not include this fork's write tools or development
launcher. Use [From Source](#from-source) and the checkout-bound launcher
for those features.

## Claude Code Plugin

```bash
claude plugin marketplace add imdinu/apple-mail-mcp
claude plugin install apple-mail@imdinu
```

The plugin registers the MCP server automatically via a thin launcher that runs the released PyPI package (uvx → pipx → private venv, whichever is available on your machine).

## Claude Desktop Bundle

Download `apple-mail-mcp-<version>.mcpb` from the [latest release](https://github.com/imdinu/apple-mail-mcp/releases/latest) and double-click it. Claude Desktop installs and registers the server; the bundle uses the same launcher as the Claude Code plugin.

Both surfaces launch the server with `--watch`, so the index is kept current as mail arrives. That background sync reads `~/Library/Mail/`, which needs Full Disk Access on the app that launches the server (Claude Code or Claude Desktop): **System Settings → Privacy & Security → Full Disk Access**. Then run `apple-mail-mcp index` once from a terminal that also has Full Disk Access to enable body search — see [Getting Started](getting-started.md).

## With pipx

```bash
pipx install apple-mail-mcp
```

The FTS5 search index (`~/.apple-mail-mcp/index.db`) is keyed to your home directory, not the install method — every install surface above shares the same index. A persistent install just avoids the small per-launch resolution overhead of ephemeral runners like `pipx run` or `uvx`.

## With uv

```bash
uv tool install apple-mail-mcp
```

## With pip

```bash
pip install apple-mail-mcp
```

## From Source

For development or to run the latest unreleased version:

```bash
git clone https://github.com/itsbrex/apple-mail-mcp
cd apple-mail-mcp
just setup
```

This installs locked dependencies, Git hooks, and a global `apple-mail-mcp`
launcher bound to this checkout. Every new launch uses editable source and
syncs this repo's `uv.lock`; source edits need no reinstall. Dependency or
metadata changes require `uv lock` first. Restart an existing MCP session
when you want it to load changed code.

```bash
just dev-status  # inspect the global link
apple-mail-mcp --help
just dev-unlink  # restore the previous executable
```

Use the absolute launcher path printed by `just dev-status` in MCP clients.
Commands using `uvx`, `pipx run`, or another environment bypass this link.
See the [development workflow](https://github.com/itsbrex/apple-mail-mcp/blob/main/CONTRIBUTING.md#global-development-command)
for relinking, worktrees, and backup behavior.

To run directly from a checkout without installing a global launcher:

```bash
uv run --locked --extra watch apple-mail-mcp
```

## Prerelease Versions

To install a prerelease (e.g., `v0.2.0a1`):

```bash
pipx install apple-mail-mcp --pip-args='--pre'
# or
uv tool install apple-mail-mcp --prerelease=allow
```

## Verify Installation

```bash
apple-mail-mcp status
```

This prints the index status. If you see output (even "no index found"), the installation is working.

## Requirements

| Requirement | Version |
|-------------|---------|
| **macOS** | Ventura or later |
| **Python** | 3.11+ |
| **Apple Mail** | Configured with ≥1 account |

!!! note
    Apple Mail MCP is macOS-only. It requires Apple Mail and the `osascript` runtime for JXA execution.
