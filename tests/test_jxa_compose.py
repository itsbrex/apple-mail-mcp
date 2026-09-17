"""Exercise compose helpers in JXA with fake Mail and Foundation objects.

No Apple Events or real mail access. macOS CI runs these with its built-in
JavaScript runtime; Linux still covers generated scripts in write tests.
"""

import json
import subprocess
import sys

import pytest

from apple_mail_mcp.jxa import MAIL_CORE_JS

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="Uses macOS's built-in JXA runtime"
)

FIXTURE = r"""
function recipients(values) {
    return {name: () => values.map(() => "Fixture"), address: () => values};
}
function message(id, body, headers) {
    return {
        id: () => id, subject: () => "Subject", content: () => body,
        sender: () => "Sender <sender@example.invalid>",
        source: () => headers,
        toRecipients: recipients(["to@example.invalid"]),
        ccRecipients: recipients([]), bccRecipients: recipients([]),
    };
}
const outgoing = message(0, "Body", "");
const saved = message(99, "\nBody \r\n",
    "In-Reply-To: <parent@invalid>\r\n\r\nBody");
let newIds = [99];
const snapshot = {
    account: "Work", ids: [1], mailbox: {
        name: () => "Drafts", messages: {
            whose: () => ({id: () => newIds}), byId: () => saved,
        },
    },
};
function check(value) { if (!value) throw new Error("Assertion failed"); }
"""


def run_js(test: str, setup: str = "") -> None:
    """Shadow application and bridge globals before loading the real core."""
    script = (
        "(function(Application, ObjC, $, Ref, delay) {\n"
        + MAIL_CORE_JS
        + FIXTURE
        + setup
        + test
        + "\nreturn JSON.stringify({ok:true});\n})("
        + "() => ({}), {}, {}, () => ({}), () => {});"
    )
    result = subprocess.run(
        ["osascript", "-l", "JavaScript"],
        input=script,
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )
    assert json.loads(result.stdout) == {"ok": True}


@pytest.mark.parametrize(
    "setup, expected",
    [
        ("", {"account": "Work", "mailbox": "Drafts", "message_id": 99}),
        ("newIds = [1];", None),
        ("newIds = [];", None),
        ("newIds = [99, 100];", None),
        ("newIds = [0];", None),
        ('saved.content = () => "Other body";', None),
        ('saved.sender = () => "other@example.invalid";', None),
        ('saved.toRecipients = recipients(["other@invalid"]);', None),
        ('saved.content = () => {throw Error("gone");};', None),
    ],
)
def test_saved_reference_requires_unique_matching_mailbox_message(
    setup, expected
):
    run_js(
        "const result = MailCore.findSavedDraft(snapshot, outgoing, null);"
        "check(JSON.stringify(result.reference) === JSON.stringify("
        + json.dumps(expected)
        + "));",
        setup,
    )


@pytest.mark.parametrize(
    "headers, expected",
    [
        ("In-Reply-To: <parent@invalid>\r\n\r\nBody", True),
        ("In-Reply-To:\r\n <parent@invalid>\r\n\r\nBody", True),
        ("In-Reply-To: <other@invalid>\r\n\r\nBody", False),
        ("Subject: Example\n\nIn-Reply-To: <parent@invalid>", False),
    ],
)
def test_threading_checks_only_saved_mime_headers(headers, expected):
    run_js(
        "const result = MailCore.findSavedDraft("
        'snapshot, outgoing, "parent@invalid");'
        f"check(result.threaded === {json.dumps(expected)});",
        f"saved.source = () => {json.dumps(headers)};",
    )


def test_missing_headers_keep_reference_without_claiming_threading():
    run_js(
        'saved.source = () => {throw Error("unavailable");};'
        "const result = MailCore.findSavedDraft("
        'snapshot, outgoing, "parent@invalid");'
        "check(result.reference.message_id === 99 && "
        'result.threaded === "unconfirmed");'
    )


BRIDGE = r"""
let sourceText, eventParams, values = [];
ObjC.import = () => {};
ObjC.unwrap = value => value;
$.NSAppleEventDescriptor = {
    currentProcessDescriptor: "local-target",
    appleEventWithEventClassEventIDTargetDescriptorReturnIDTransactionID:
        (eventClass, id, target) => {
            check(target === "local-target");
            eventParams = {};
            return {setParamDescriptorForKeyword: (value, key) => {
                eventParams[key] = value;
            }};
        },
    descriptorWithString: value => value,
    descriptorWithInt32: value => value,
    listDescriptor: {insertDescriptorAtIndex: (value, index) => {
        values[index - 1] = value;
    }},
};
let resultValue = () => ({stringValue: values[2]});
$.NSAppleScript = {alloc: {initWithSource: source => {
    sourceText = source;
    return {executeAppleEventError: () => resultValue()};
}}};
"""


def test_reply_body_travels_as_data_and_is_verified():
    run_js(
        r"""
const body = 'Unicode \u2713 " ); Mail.quit(); --';
outgoing.content = () => {throw Error("Uninitialized rich text read");};
MailCore.setReplyBody(outgoing, body, "Original");
check(sourceText.indexOf(body) === -1);
check(values[0] === 0 && values[1] === "Subject");
check(values[2] === body + "\n\nOriginal");
check(eventParams[0x736e616d] === "fillreply");
""",
        BRIDGE,
    )


@pytest.mark.parametrize(
    "result", ["null", '{stringValue: "Ignored body update"}']
)
def test_reply_body_failure_stops_before_save_or_send(result):
    run_js(
        f"resultValue = () => ({result});"
        "let failure;"
        'try {MailCore.setReplyBody(outgoing, "Body", "Original");}'
        "catch (error) {failure = String(error);}"
        'check(failure && failure.indexOf("nothing was sent") !== -1);',
        BRIDGE,
    )
