import asyncio
import copy
import json
import threading

import httpx
import pytest
from test_agent import ACCOUNT, packet, result, wait

from QQBot.agent.config import DEFAULTS
from QQBot.agent.llm import ChatClient, ModelError
from QQBot.agent.prompt import TOOLS
from QQBot.storage.database import Database
from QQBot.storage.sessions import SessionStore


@pytest.mark.parametrize("problem", ["duplicate", "unavailable", "finish-first", "bad-json"])
def test_invalid_later_call_rejects_whole_batch_without_an_earlier_send(stack, problem):
    service, receiver, sessions, _, _, connection, model = stack
    response = result("send_message", "finish")
    calls = response["message"]["tool_calls"]
    if problem == "duplicate":
        calls[1]["id"] = calls[0]["id"]
    elif problem == "unavailable":
        calls[1]["function"]["name"] = "send_image"
    elif problem == "finish-first":
        calls.reverse()
    else:
        calls[1]["function"]["arguments"] = '{"summary":'
    model.responses = [response]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] != "running")
    assert not connection.calls and len(model.calls) == 1
    assert "整批" in sessions.list(ACCOUNT)[0]["reason"]


def test_http_rejection_records_a_failed_model_attempt_without_usage_or_qq_retry(stack):
    service, receiver, sessions, _, _, connection, _ = stack

    def handler(request):
        assert json.loads(request.content)["tool_choice"] == "auto"
        return httpx.Response(400, text="private provider response")

    service._model = ChatClient(transport=httpx.MockTransport(handler))
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] != "running")
    item = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    attempts = [r for r in item["records"] if r["kind"] == "model_request"]
    assert len(attempts) == 1 and attempts[0]["status"] == "error"
    assert attempts[0]["ended"] >= attempts[0]["started"]
    assert item["usage"]["totalTokens"] == 0 and not connection.calls
    assert "private provider" not in json.dumps(item)


def test_ongoing_tool_is_visible_and_cancellation_retains_its_final_status(stack):
    service, receiver, sessions, _, _, connection, _ = stack
    entered, release = threading.Event(), threading.Event()
    original = connection.invoke

    def blocked(*args, **kwargs):
        entered.set()
        release.wait(3)
        return original(*args, **kwargs)

    connection.invoke = blocked
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    assert entered.wait(2)
    item = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert any(r["kind"] == "tool" and r["status"] == "running" for r in item["records"])
    service.pause("test")
    release.set()
    wait(lambda: sessions.list(ACCOUNT)[0]["status"] != "running")
    item = sessions.get(ACCOUNT, item["id"])
    tools = [r for r in item["records"] if r["kind"] == "tool"]
    assert tools[0]["status"] == "aborted" and tools[0]["ended"] is not None
    assert len(item["sent"]) == 1, "already-dispatched receipt must survive cancellation"


def test_chat_thinking_content_round_trips_with_tools_without_becoming_reply_text():
    api = copy.deepcopy(DEFAULTS["api"])
    api.update(baseUrl="https://model.test/v1", model="thinking-model", protocol="chat")
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if len(seen) == 2:
            assert body["messages"][-2]["reasoning_content"] == "continuation-only reasoning"
        name = "get_recent_messages" if len(seen) == 1 else "finish"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning_content": "continuation-only reasoning",
                            "tool_calls": [
                                {
                                    "id": name,
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": "{}"
                                        if name == "get_recent_messages"
                                        else '{"summary":"done"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    async def run():
        client = ChatClient(transport=httpx.MockTransport(handler))
        messages = [{"role": "user", "content": "test"}]
        first = await client.complete(api, messages, TOOLS)
        assert first["message"]["content"] is None
        messages += [
            first["message"],
            {"role": "tool", "tool_call_id": "get_recent_messages", "content": '{"messages":[]}'},
        ]
        await client.complete(api, messages, TOOLS)

    asyncio.run(run())


@pytest.mark.parametrize("tools", [None, TOOLS])
def test_provider_cannot_invent_unadvertised_functions(tools):
    api = copy.deepcopy(DEFAULTS["api"])
    api.update(baseUrl="https://model.test/v1", model="test")
    payload = result("not_an_available_tool")["message"]
    client = ChatClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"choices": [{"message": payload}]})
        )
    )
    with pytest.raises(ModelError):
        asyncio.run(client.complete(api, [], tools))


def test_startup_finalizes_interrupted_tool_and_request_records_without_losing_receipts(tmp_path):
    db = Database(tmp_path / "interrupted.sqlite3")
    try:
        store = SessionStore(db)
        session = store.start(ACCOUNT, "private:11223344", "测试", "test", "test")
        session["records"] = [
            {
                "kind": "model_request",
                "status": "running",
                "started": session["started"],
                "ended": None,
            },
            {"kind": "tool", "name": "send_message", "status": "running", "result": {}},
        ]
        session["sent"] = [{"messageId": "-1", "text": "已发出的消息", "ts": session["started"]}]
        store.save(session)
        restored = SessionStore(db).get(ACCOUNT, session["id"])
        assert restored["status"] == "aborted"
        assert restored["sent"] == session["sent"]
        assert all(r["status"] == "aborted" and r["ended"] for r in restored["records"])
    finally:
        db.close()


def test_startup_preserves_damaged_nested_records_without_blocking_other_sessions(tmp_path):
    db = Database(tmp_path / "damaged.sqlite3")
    try:
        store = SessionStore(db)
        item = store.start(ACCOUNT, "private:11223344", "测试", "test", "test")
        damaged = '[{"kind":"tool"'
        with db.lock, db.connection as connection:
            connection.execute("UPDATE sessions SET records=? WHERE id=?", (damaged, item["id"]))
        SessionStore(db)
        row = db.connection.execute(
            "SELECT status,records FROM sessions WHERE id=?", (item["id"],)
        ).fetchone()
        assert row["status"] == "aborted" and row["records"] == damaged
    finally:
        db.close()
