"""Draft-only compose shares validation with the compatible send tool."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from apple_mail_mcp import server
from apple_mail_mcp.config import set_read_only_mode
from tests.test_write_send import JXA, _draft_result, _isolate  # noqa: F401


@pytest.mark.asyncio
async def test_create_draft_has_no_transmission_path():
    with patch(JXA, new_callable=AsyncMock) as jxa:
        jxa.return_value = _draft_result()
        result = await server.create_draft(["a@b.com"], "Hi", "Body")
    script = jxa.call_args.args[0]
    assert "msg.save()" in script
    assert ".send(" not in script
    assert result["status"] == "draft"


@pytest.mark.asyncio
async def test_create_draft_read_only_and_hidden_account(monkeypatch):
    with patch(JXA, new_callable=AsyncMock) as jxa:
        set_read_only_mode(True)
        with pytest.raises(PermissionError):
            await server.create_draft(["a@b.com"], "Hi", "Body")
        set_read_only_mode(False)
        monkeypatch.setenv("APPLE_MAIL_INDEX_EXCLUDE_ACCOUNTS", "PHI")
        with pytest.raises(ValueError, match="not found"):
            await server.create_draft(["a@b.com"], "Hi", "Body", account="PHI")
        jxa.assert_not_called()


@pytest.mark.parametrize("tool", ["send_email", "create_draft"])
@pytest.mark.parametrize(
    "recipients",
    [[], ["Name <a@@b>"], ["a@b\nBcc: x@y"], ["a@b"] * 11],
)
@pytest.mark.asyncio
async def test_compose_validation_before_jxa(tool, recipients):
    with patch(JXA, new_callable=AsyncMock) as jxa:
        with pytest.raises(ValueError):
            await getattr(server, tool)(recipients, "Hi", "Body")
        jxa.assert_not_called()


@pytest.mark.parametrize("tool", ["send_email", "create_draft"])
@pytest.mark.asyncio
async def test_compose_injection_and_sender_validation(tool):
    payload = 'x"); Mail.quit(); ("'
    with patch(JXA, new_callable=AsyncMock) as jxa:
        jxa.return_value = _draft_result()
        await getattr(server, tool)(
            ["Name <a@b.com>"], payload, payload, account=payload
        )
    script = jxa.call_args.args[0]
    assert json.dumps(payload) in script
    assert payload not in script
    assert script.index("acct.enabled()") < script.index("OutgoingMessage")


@pytest.mark.parametrize("tool", ["send_email", "create_draft"])
@pytest.mark.asyncio
async def test_saved_draft_reference_is_scoped_and_verified(tool):
    reference = {"account": "Work", "mailbox": "Drafts", "message_id": 42}
    with patch(JXA, new_callable=AsyncMock) as jxa:
        jxa.return_value = _draft_result(
            draft=reference, draft_status="confirmed"
        )
        result = await getattr(server, tool)(["a@b.com"], "Hi", "Body")
    assert result["draft"] == reference
    script = jxa.call_args.args[0]
    assert script.index("MailCore.snapshotDrafts") < script.index("msg.save()")
    assert script.index("msg.save()") < script.index("MailCore.findSavedDraft")
    assert "message_id: msg.id()" not in script


@pytest.mark.asyncio
async def test_send_has_no_draft_lookup():
    with patch(JXA, new_callable=AsyncMock) as jxa:
        jxa.return_value = _draft_result(
            status="sent", draft=None, draft_status="not_applicable"
        )
        result = await server.send_email(
            ["a@b.com"], "Hi", "Body", confirm=True
        )
    assert result["draft"] is None
    assert "MailCore.findSavedDraft" not in jxa.call_args.args[0]


@pytest.mark.asyncio
async def test_unconfirmed_save_is_reported_without_retry():
    with patch(JXA, new_callable=AsyncMock) as jxa:
        jxa.return_value = _draft_result(draft=None, draft_status="unconfirmed")
        result = await server.create_draft(["a@b.com"], "Hi", "Body")
    assert result["draft_status"] == "unconfirmed"
    jxa.assert_called_once()
