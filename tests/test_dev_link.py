"""Exercise the developer launcher in temporary repos and bin directories."""

from __future__ import annotations

import json
import os
import runpy
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dev_link.py"


@pytest.fixture
def dev_link(tmp_path, monkeypatch):
    repo = tmp_path / "checkout with 'quotes'"
    (repo / "scripts").mkdir(parents=True)
    script = repo / "scripts" / SCRIPT.name
    shutil.copyfile(SCRIPT, script)
    (repo / "pyproject.toml").write_text('[project]\nname="apple-mail-mcp"\n')
    bin_dir = tmp_path / "global bin"
    bin_dir.mkdir()
    uv = tmp_path / "uv with 'quotes'"
    code = """
import json, os, sys
if sys.argv[1:] == ['tool', 'dir', '--bin']:
    print(os.environ['DEV_TEST_BIN'])
else:
    print(json.dumps({'args': sys.argv[1:], 'cwd': os.getcwd(),
                     'environment': os.environ['UV_PROJECT_ENVIRONMENT']}))
    print('uv diagnostic', file=sys.stderr)
    sys.exit(23 if '--fail' in sys.argv else 0)
"""
    uv.write_text(
        f"#!/bin/sh\nexec {shlex.quote(sys.executable)} "
        f'-c {shlex.quote(code)} "$@"\n'
    )
    uv.chmod(0o755)
    entrypoint = runpy.run_path(str(script))["main"]

    def command(action, *, discover=False, uv_path=None):
        args = [str(script), action, "--uv", str(uv_path or uv)]
        if not discover:
            args += ["--bin-dir", str(bin_dir)]
        with monkeypatch.context() as patch:
            patch.setattr(sys, "argv", args)
            patch.setenv("DEV_TEST_BIN", str(bin_dir))
            try:
                code = entrypoint()
            except SystemExit as exc:
                code = exc.code
        return subprocess.CompletedProcess(args, code)

    return repo, bin_dir / "apple-mail-mcp", command


def test_launcher_uses_checkout_and_preserves_arguments(dev_link, tmp_path):
    repo, target, command = dev_link
    assert command("install", discover=True).returncode == 0
    args = ["search", "a 'quoted' phrase", "", "$(touch never-created)"]
    result = subprocess.run(
        [str(target), *args],
        cwd=tmp_path,
        env={**os.environ, "UV_PROJECT_ENVIRONMENT": "/wrong/environment"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["cwd"] == str(repo)
    assert data["environment"] == str(repo / ".venv")
    assert data["args"] == [
        "run",
        "--locked",
        "--quiet",
        "--extra",
        "watch",
        "--project",
        str(repo),
        "--",
        str(repo / ".venv/bin/apple-mail-mcp"),
        *args,
    ]
    assert result.stderr == "uv diagnostic\n"
    assert not (repo / "never-created").exists()
    failed = subprocess.run([str(target), "--fail"], capture_output=True)
    assert failed.returncode == 23


@pytest.mark.parametrize("missing_original", [False, True])
def test_relink_and_unlink_preserve_original_symlink(
    dev_link, tmp_path, missing_original
):
    _, target, command = dev_link
    original = tmp_path / "old tool"
    if not missing_original:
        original.write_text("original launcher\n")
    target.symlink_to(original)
    assert command("install").returncode == 0
    installed = target.read_bytes()
    assert command("install").returncode == 0
    assert target.read_bytes() == installed
    assert command("status").returncode == 0
    assert command("uninstall").returncode == 0
    assert target.is_symlink()
    assert target.readlink() == original
    if not missing_original:
        assert original.read_text() == "original launcher\n"


def test_clean_install_can_be_removed(dev_link):
    _, target, command = dev_link
    assert command("status").returncode == 1
    assert command("install").returncode == 0
    assert command("uninstall").returncode == 0
    assert not target.exists()


def test_external_replacement_is_not_overwritten_or_removed(dev_link):
    _, target, command = dev_link
    target.write_text("original launcher\n")
    assert command("install").returncode == 0
    target.write_text("externally replaced launcher\n")
    assert command("status").returncode == 1
    assert command("install").returncode == 1
    assert command("uninstall").returncode == 1
    assert target.read_text() == "externally replaced launcher\n"


def test_status_accepts_pinned_uv_after_path_changes(dev_link, tmp_path):
    _, target, command = dev_link
    assert command("install").returncode == 0
    installed = target.read_bytes()
    current_uv = tmp_path / "different uv shim"
    current_uv.write_text("#!/bin/sh\nexit 0\n")
    current_uv.chmod(0o755)

    assert command("status", uv_path=current_uv).returncode == 0
    assert target.read_bytes() == installed


@pytest.mark.parametrize("missing", [False, True])
def test_status_rejects_unavailable_pinned_uv(dev_link, missing):
    _, target, command = dev_link
    assert command("install").returncode == 0
    pinned_uv = Path(shlex.split(target.read_text().splitlines()[-1])[1])
    if missing:
        pinned_uv.unlink()
    else:
        pinned_uv.chmod(0o644)

    assert command("status").returncode == 1


def test_status_rejects_changed_launcher_contract(dev_link):
    _, target, command = dev_link
    assert command("install").returncode == 0
    target.write_text(target.read_text().replace("--locked ", "", 1))

    assert command("status").returncode == 1
