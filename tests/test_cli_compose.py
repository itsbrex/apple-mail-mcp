"""CLI command parsing and routing for draft-only and native reply tools."""

import io
import json
from unittest.mock import AsyncMock, patch

import pytest

from apple_mail_mcp.cli import app


@pytest.mark.parametrize(
    "command, tool, args",
    [
        ("draft", "create_draft", ["--to", "Name <a@b.com>", "-s", "Hi"]),
        ("send", "send_email", ["--to", "a@b.com", "-s", "Hi", "--confirm"]),
        ("reply-draft", "reply_draft", ["42", "--reply-all", "-m", "Archive"]),
        ("reply", "reply_email", ["42", "--confirm"]),
    ],
)
def test_cli_compose_routes_arguments_and_stdin(command, tool, args, capsys):
    with (
        patch(f"apple_mail_mcp.server.{tool}", new_callable=AsyncMock) as op,
        patch("sys.stdin", io.StringIO("Body from stdin")),
    ):
        op.return_value = {"status": "draft"}
        with pytest.raises(SystemExit) as exit_result:
            app([command, *args, "-b", "-", "-a", "Work"], exit_on_error=False)
        assert exit_result.value.code == 0
    assert json.loads(capsys.readouterr().out) == {"status": "draft"}
    assert "Body from stdin" in op.call_args.args
    assert op.call_args.kwargs["account"] == "Work"
    if command in ("reply", "send"):
        assert op.call_args.kwargs["confirm"] is True
    else:
        assert "confirm" not in op.call_args.kwargs


@pytest.mark.parametrize("command", ["draft", "reply-draft"])
def test_draft_only_commands_reject_confirm(command):
    from cyclopts import UnknownOptionError

    with pytest.raises(UnknownOptionError):
        app([command, "--confirm"], exit_on_error=False, print_error=False)
