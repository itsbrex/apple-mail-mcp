"""Native reply scripts are scoped, draft-safe, and preserve quoted content."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from apple_mail_mcp import server
from apple_mail_mcp.config import set_read_only_mode
from tests.test_write_send import JXA, _draft_result, _isolate  # noqa: F401


@pytest.mark.parametrize("tool", ["reply_email", "reply_draft"])
@pytest.mark.asyncio
async def test_native_reply_is_scoped_and_draft_by_default(tool):
    with patch(JXA, new_callable=AsyncMock) as jxa:
        jxa.return_value = _draft_result(
            in_reply_to="parent@example.com",
            threaded=True,
            draft={"account": "Work", "mailbox": "Drafts", "message_id": 99},
        )
        result = await getattr(server, tool)(
            42, "Reply", account="Work", mailbox="Archive", reply_all=True
        )
    script = jxa.call_args.args[0]
    assert 'MailCore.getAccount("Work")' in script
    assert 'MailCore.getMailbox(acct, "Archive")' in script
    assert "sourceMailbox.messages" in script
    assert "Mail.messages" not in script
    assert "src.reply({openingWindow: false, replyToAll: true})" in " ".join(
        script.split()
    )
    assert 'MailCore.setReplyBody(msg, "Reply", fallbackQuote)' in script
    assert "src.content()" in script
    assert script.index("MailCore.setReplyBody") < script.index("msg.save()")
    assert "msg.save()" in script
    assert ".send(" not in script
    assert "MailCore.findSavedDraft(beforeDrafts, msg, inReplyTo)" in script
    assert result["in_reply_to"] == "parent@example.com"
    assert result["threaded"] is True
    assert "message_id" not in result


@pytest.mark.parametrize("tool", ["reply_email", "reply_draft"])
@pytest.mark.asyncio
async def test_reply_safety_gates(tool, monkeypatch):
    operation = getattr(server, tool)
    with patch(JXA, new_callable=AsyncMock) as jxa:
        set_read_only_mode(True)
        with pytest.raises(PermissionError):
            await operation(42, "Reply")
        set_read_only_mode(False)
        monkeypatch.setenv("APPLE_MAIL_INDEX_EXCLUDE_ACCOUNTS", "PHI")
        with pytest.raises(ValueError, match="Message 42 not found"):
            await operation(42, "Reply", account="PHI")
        jxa.assert_not_called()


@pytest.mark.parametrize("tool", ["reply_email", "reply_draft"])
@pytest.mark.asyncio
async def test_reply_inputs_are_json_literals(tool):
    payload = 'x"); Mail.quit(); ("\n'
    with patch(JXA, new_callable=AsyncMock) as jxa:
        jxa.return_value = _draft_result()
        await getattr(server, tool)(
            42, payload, account=payload, mailbox=payload
        )
    script = jxa.call_args.args[0]
    assert script.count(json.dumps(payload)) == 3
    assert payload not in script
    assert "Mail.quit()" not in script.replace(json.dumps(payload), "")


@pytest.mark.asyncio
async def test_confirm_is_only_reply_transmission_path():
    with patch(JXA, new_callable=AsyncMock) as jxa:
        jxa.return_value = _draft_result(status="sent", draft=None)
        await server.reply_email(42, "Reply", confirm=True)
    script = jxa.call_args.args[0]
    assert "msg.send()" in script
    assert "msg.save()" not in script
    assert "MailCore.findSavedDraft" not in script
    assert "Too many recipients" in script
    assert script.index("MailCore.assertSenderAccount") < script.index(
        "msg.send()"
    )


@pytest.mark.parametrize("error", ["Message not found with ID: 42", "-1728"])
@pytest.mark.asyncio
async def test_missing_source_maps_to_clear_error(error):
    with patch(JXA, new_callable=AsyncMock, side_effect=RuntimeError(error)):
        with pytest.raises(ValueError, match="Message 42 not found"):
            await server.reply_email(42, "Reply")


@pytest.mark.asyncio
async def test_reply_timeout_warns_about_ambiguous_mutation():
    with patch(JXA, new_callable=AsyncMock, side_effect=TimeoutError()) as jxa:
        with pytest.raises(RuntimeError, match="check Sent and Drafts"):
            await server.reply_email(42, "Reply")
    jxa.assert_called_once()


@pytest.mark.parametrize("message_id", [0, -1, True, "42); Mail.quit()"])
@pytest.mark.asyncio
async def test_reply_rejects_invalid_ids_before_jxa(message_id):
    with patch(JXA, new_callable=AsyncMock) as jxa:
        with pytest.raises(ValueError, match="message_id"):
            await server.reply_email(message_id, "Reply")
        jxa.assert_not_called()
