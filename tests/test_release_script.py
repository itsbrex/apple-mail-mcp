"""Exercise release commits against temporary repositories and local remotes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASE_FILES = (
    "pyproject.toml",
    "server.json",
    "uv.lock",
    "plugin/.claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    "mcpb/manifest.json",
)


@pytest.fixture
def release_repo(tmp_path: Path):
    repo = tmp_path / "checkout with spaces"
    repo.mkdir()
    for file in (
        *RELEASE_FILES,
        "scripts/release.sh",
        "plugin/start.sh",
        "mcpb/build.sh",
    ):
        target = repo / file
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / file, target)
    current = tomllib.loads((repo / "pyproject.toml").read_text())["project"][
        "version"
    ]
    major, minor, patch = current.split(".")
    version = f"{major}.{minor}.{int(patch) + 1}"
    (repo / "CHANGELOG.md").write_text(f"# Changelog\n\n## [{version}]\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"
    # Dependency resolution and the full suite have their own real gates.
    # Here, record that the release invokes both and commits the lock update.
    for command, body in {
        "uv": 'printf "\\n# lock refreshed\\n" >> uv.lock\n',
        "just": "",
    }.items():
        target = bin_dir / command
        target.write_text(
            f'#!/bin/sh\nprintf "{command} %s\\n" "$*" '
            '>> "$RELEASE_TEST_LOG"\n' + body
        )
        target.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        PATH=f"{bin_dir}{os.pathsep}{env['PATH']}",
        RELEASE_TEST_LOG=str(log),
    )

    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", *args], cwd=repo, env=env, text=True, stderr=subprocess.PIPE
        ).strip()

    git("init", "-b", "main")
    git("config", "user.name", "Release Test")
    git("config", "user.email", "release-test@example.com")
    git("init", "--bare", str(tmp_path / "origin.git"))
    git("remote", "add", "origin", str(tmp_path / "origin.git"))

    def seed() -> None:
        git("add", ".")
        git("commit", "-m", "test: seed release fixture")
        git("push", "-u", "origin", "main")

    def release() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "scripts/release.sh", version],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )

    return repo, version, log, git, seed, release


def test_release_commits_all_versions_without_pushing(release_repo):
    repo, version, log, git, seed, release = release_repo
    marketplace = repo / ".claude-plugin/marketplace.json"
    before = json.loads(marketplace.read_text())["metadata"]
    seed()
    original = git("rev-parse", "HEAD")

    result = release()

    assert result.returncode == 0, result.stdout + result.stderr
    for file in ("server.json", "plugin/.claude-plugin/plugin.json"):
        assert json.loads((repo / file).read_text())["version"] == version
    assert (
        json.loads((repo / "server.json").read_text())["packages"][0]["version"]
        == version
    )
    assert (
        tomllib.loads((repo / "pyproject.toml").read_text())["project"][
            "version"
        ]
        == version
    )
    assert json.loads(marketplace.read_text())["plugins"][0]["version"] == (
        version
    )
    assert json.loads(marketplace.read_text())["metadata"] == before
    assert json.loads((repo / "mcpb/manifest.json").read_text())["version"] == (
        version
    )
    assert set(git("diff", "--name-only", "HEAD^", "HEAD").splitlines()) == (
        set(RELEASE_FILES)
    )
    assert git("status", "--porcelain") == ""
    assert git("rev-parse", f"v{version}") == git("rev-parse", "HEAD")
    assert git("rev-parse", "origin/main") == original
    assert git("ls-remote", "--tags", "origin") == ""
    assert log.read_text().splitlines() == ["uv lock -q", "just check"]

    subprocess.run(["bash", "mcpb/build.sh"], cwd=repo, check=True)
    assert (repo / f"dist/apple-mail-mcp-{version}.mcpb").is_file()


def test_release_rejects_version_drift_before_changing_files(release_repo):
    repo, _, log, git, seed, release = release_repo
    manifest = repo / "plugin/.claude-plugin/plugin.json"
    data = json.loads(manifest.read_text())
    data["version"] = "0.0.0"
    manifest.write_text(json.dumps(data, indent=2) + "\n")
    seed()
    original = git("rev-parse", "HEAD")
    before = {file: (repo / file).read_bytes() for file in RELEASE_FILES}

    result = release()

    assert result.returncode != 0
    assert "plugin/.claude-plugin/plugin.json" in result.stderr
    assert "version" in result.stderr
    after = {file: (repo / file).read_bytes() for file in RELEASE_FILES}
    assert after == before
    assert git("rev-parse", "HEAD") == original
    assert git("status", "--porcelain") == ""
    assert git("tag", "--list") == ""
    assert not log.exists()
