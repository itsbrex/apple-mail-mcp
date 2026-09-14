"""Drift guards for things that must move in lockstep but live in
different files: the release version, the MCP tool roster, and the
hand-written tool counts in the docs.

These are the checks a reviewer does by eye before every release. They
run in milliseconds, so they run on every `just check` / CI instead.
"""

from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER_PY = ROOT / "src" / "apple_mail_mcp" / "server.py"

# Every file that states the tool count as a literal number. Adding a
# tool means touching each of these — the test names the stragglers.
TOOL_COUNT_FILES = (
    "README.md",
    "CLAUDE.md",
    "docs/index.md",
    "docs/tools.md",
    "docs/getting-started.md",
    "docs/architecture.md",
    "src/apple_mail_mcp/server.py",
)

# Files that carry a per-tool reference table.
TOOL_TABLE_FILES = ("README.md", "CLAUDE.md", "docs/tools.md")

TOOL_COUNT_RE = re.compile(r"\b(\d+)\s+(?:MCP\s+)?tools\b", re.IGNORECASE)
# "TOOLS (8 total)" in the server.py module docstring.
TOOL_TOTAL_RE = re.compile(r"\bTOOLS\s*\((\d+)\s+total\)", re.IGNORECASE)


def _mcp_tool_names() -> list[str]:
    tree = ast.parse(SERVER_PY.read_text())
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "tool"
                and isinstance(target.value, ast.Name)
                and target.value.id == "mcp"
            ):
                names.append(node.name)
    assert names, "no @mcp.tool functions found — AST scan broke"
    return names


class TestVersionLockstep:
    def test_pyproject_and_server_json_agree(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
        version = pyproject["project"]["version"]
        server = json.loads((ROOT / "server.json").read_text())

        assert server["version"] == version, "server.json top-level version"
        assert server["packages"][0]["version"] == version, (
            "server.json packages[0].version"
        )

    @pytest.mark.parametrize(
        ("rel", "keys"),
        [
            ("plugin/.claude-plugin/plugin.json", ("version",)),
            (".claude-plugin/marketplace.json", ("plugins", 0, "version")),
            ("mcpb/manifest.json", ("version",)),
        ],
    )
    def test_distribution_versions_agree(
        self, rel: str, keys: tuple[str | int, ...]
    ) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
        version = pyproject["project"]["version"]
        actual = json.loads((ROOT / rel).read_text())
        for key in keys:
            actual = actual[key]
        assert actual == version, f"{rel}: release version differs"

    def test_lockfile_project_version_agrees(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
        lock = tomllib.loads((ROOT / "uv.lock").read_text())
        packages = [p for p in lock["package"] if p["name"] == "apple-mail-mcp"]
        assert len(packages) == 1
        assert packages[0]["version"] == pyproject["project"]["version"]

    def test_changelog_has_entry_for_current_version(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
        version = pyproject["project"]["version"]
        changelog = (ROOT / "CHANGELOG.md").read_text()

        assert f"## [{version}]" in changelog, (
            f"CHANGELOG.md has no '## [{version}]' section. "
            "Add it before cutting the release (scripts/release.sh "
            "refuses to tag without one)."
        )


class TestToolRosterMatchesDocs:
    def test_every_tool_is_in_each_reference_table(self):
        tools = _mcp_tool_names()
        missing: dict[str, list[str]] = {}
        for rel in TOOL_TABLE_FILES:
            text = (ROOT / rel).read_text()
            absent = [t for t in tools if f"`{t}(" not in text]
            if absent:
                missing[rel] = absent
        assert not missing, (
            "tool reference tables are missing entries "
            f"(expected a `name(...)` cell): {missing}"
        )

    @pytest.mark.parametrize("rel", TOOL_COUNT_FILES)
    def test_stated_tool_count_matches_server(self, rel):
        expected = len(_mcp_tool_names())
        text = (ROOT / rel).read_text()
        stated = [int(m) for m in TOOL_COUNT_RE.findall(text)]
        stated += [int(m) for m in TOOL_TOTAL_RE.findall(text)]
        assert stated, f"{rel}: no 'N tools' / 'TOOLS (N total)' phrase found"
        wrong = sorted({n for n in stated if n != expected})
        assert not wrong, (
            f"{rel} says {wrong} tools; server.py defines {expected}. "
            f"Update every count in {TOOL_COUNT_FILES}."
        )
