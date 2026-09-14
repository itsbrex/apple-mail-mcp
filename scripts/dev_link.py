"""Install a reversible, checkout-bound launcher in uv's executable dir."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

MARKER = "# apple-mail-mcp development launcher v1\n"


def launcher(repo: Path, uv: str) -> str:
    """Keep source editable and sync locked dependencies on every launch."""
    return (
        "#!/bin/sh\n"
        f"{MARKER}"
        "set -eu\n"
        f"cd {shlex.quote(str(repo))}\n"
        "export UV_PROJECT_ENVIRONMENT="
        f"{shlex.quote(str(repo / '.venv'))}\n"
        f"exec {shlex.quote(uv)} run --locked --quiet --extra watch "
        f"--project {shlex.quote(str(repo))} -- "
        f'{shlex.quote(str(repo / ".venv/bin/apple-mail-mcp"))} "$@"\n'
    )


def exists(path: Path) -> bool:
    """Include dangling symlinks when preserving a previous install."""
    return path.exists() or path.is_symlink()


def managed(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    with path.open("rb") as stream:
        return stream.read(128).startswith(f"#!/bin/sh\n{MARKER}".encode())


def linked_to_checkout(target: Path, repo: Path) -> bool:
    """Check the installed contract using its pinned uv, not today's PATH."""
    if not managed(target) or not os.access(target, os.X_OK):
        return False
    content = target.read_text()
    try:
        command = shlex.split(content.splitlines()[-1])
    except (IndexError, ValueError):
        return False
    if len(command) < 2 or command[0] != "exec":
        return False
    pinned_uv = command[1]
    return (
        Path(pinned_uv).is_absolute()
        and Path(pinned_uv).is_file()
        and os.access(pinned_uv, os.X_OK)
        and content == launcher(repo, pinned_uv)
    )


def install(target: Path, backup: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if exists(target) and not managed(target):
        if exists(backup):
            raise OSError(
                f"Refusing to overwrite {target}: backup already exists "
                f"at {backup}. Inspect both before relinking."
            )
        if target.is_dir():
            raise OSError(f"Refusing to replace directory: {target}")
        shutil.copy2(target, backup, follow_symlinks=False)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=target.parent, prefix=".apple-mail-mcp-", delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    try:
        temporary.chmod(0o755)
        # Replace the directory entry, never write through the old symlink.
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "uninstall"))
    parser.add_argument("--bin-dir", type=Path, help="Override uv's bin dir")
    parser.add_argument("--uv", default=shutil.which("uv"))
    args = parser.parse_args()
    if not args.uv:
        parser.exit(1, "uv is required; install it before linking.\n")
    # Preserve a shim's invocation name instead of resolving its symlink.
    uv = os.path.abspath(args.uv)
    repo = Path(__file__).resolve().parents[1]
    try:
        bin_dir = args.bin_dir
        if bin_dir is None:
            result = subprocess.run(
                [uv, "tool", "dir", "--bin"],
                check=True,
                capture_output=True,
                text=True,
            )
            bin_dir = Path(result.stdout.rstrip("\n"))
        target = bin_dir.expanduser().absolute() / "apple-mail-mcp"
        backup = target.with_name(".apple-mail-mcp.before-dev")
        content = launcher(repo, uv)
        if args.action == "install":
            install(target, backup, content)
            print(f"Linked: {target}\nCheckout: {repo}")
            if exists(backup):
                print(f"Previous executable preserved: {backup}")
        elif args.action == "status":
            if not linked_to_checkout(target, repo):
                parser.exit(1, f"Not linked to this checkout: {target}\n")
            print(f"Linked: {target}\nCheckout: {repo}")
            print(f"Editable environment: {repo / '.venv'}")
        else:
            if not managed(target):
                parser.exit(1, f"Refusing to remove unmanaged {target}\n")
            if exists(backup):
                backup.replace(target)
                print(f"Restored previous executable: {target}")
            else:
                target.unlink()
                print(f"Removed development launcher: {target}")
    except (OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"dev-link: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
