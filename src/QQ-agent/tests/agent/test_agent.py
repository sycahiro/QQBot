import asyncio
import copy
import json
import threading
import time

import httpx
import pytest
from qqbot.agent.config import DEFAULTS, SettingsStore
from qqbot.agent.llm import ChatClient, ModelError
from qqbot.agent.receiver import Receiver
from qqbot.agent.service import AgentService
from qqbot.qq.engine import EngineError
from qqbot.storage.database import Database
from qqbot.storage.messages import MessageStore
from qqbot.storage.sessions import SessionStore

ACCOUNT, PEER, OTHER = "12345678", "11223344", "87654321"


def packet(mid=1, kind="private", **fields):
    return {
        "post_type": "message",
        "self_id": ACCOUNT,
        "message_type": kind,
        "user_id": PEER,
        "sender": {"user_id": PEER, "nickname": "群友"},
        "group_id": "99887766",
        "message_id": mid,
        "time": time.time(),
        "message": [{"type": "text", "data": {"text": "你好"}}],
    } | fields


def result(*names, content=None):
    return {
        "model": "test",
        "usage": {"promptTokens": 10, "completionTokens": 2, "totalTokens": 12, "calls": 1},
        "message": {
            "role": "assistant",
            "content": content,
            **(
                {
                    "tool_calls": [
                        {
                            "id": f"call-{i}-{name}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(
                                    {"messages": "你好呀"}
                                    if name == "send_message"
                                    else {"summary": "处理结束"}
                                ),
                            },
                        }
                        for i, name in enumerate(names)
                    ]
                }
                if names
                else {}
            ),
        },
    }


class Connection:
    def __init__(self):
        self.calls, self.connected, self.account, self.error = [], True, ACCOUNT, None

    def status(self):
        return {"connected": self.connected, "account": {"uin": self.account}}

    def invoke(self, action, params, *, expected_account=None):
        assert self.account == expected_account
        self.calls.append((action, params))
        if self.error:
            raise self.error
        return {"status": "ok", "data": {"message_id": -len(self.calls)}}


class Model:
    def __init__(self, responses=None):
        self.media_calls = []
        self.calls, self.responses = [], responses or [result("send_message", "finish")]

    async def complete(self, api, messages, tools):
        if not tools and any(isinstance(m.get("content"), list) for m in messages):
            self.media_calls.append(copy.deepcopy(messages))
            return result(content="画面中是测试图片。")
        self.calls.append(copy.deepcopy(messages))
        return copy.deepcopy(self.responses[min(len(self.calls) - 1, len(self.responses) - 1)])


def wait(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


@pytest.fixture
def stack(tmp_path):
    database = Database(tmp_path / "agent.sqlite3")
    messages, settings, sessions, connection, model = (
        MessageStore(database),
        SettingsStore(database),
        SessionStore(database),
        Connection(),
        Model(),
    )
    settings.save(
        ACCOUNT,
        {
            "api": {"baseUrl": "http://model.test/v1", "model": "test", "apiKey": "secret"},
            "allow": {"private": [PEER], "groups": ["99887766"]},
        },
    )
    service = AgentService(settings, messages, sessions, connection, model=model, debounce=0.02)
    yield (
        service,
        Receiver(settings, messages, service),
        sessions,
        settings,
        messages,
        connection,
        model,
    )
    service.close()
    database.close()


def test_off_receives_without_model_or_replaying_backlog(stack):
    service, receiver, sessions, _, messages, connection, model = stack
    receiver.receive(ACCOUNT, packet())
    assert messages.list_chats(ACCOUNT)[0]["count"] == 1
    service.enable(ACCOUNT, True)
    time.sleep(0.08)
    assert not model.calls and not sessions.list(ACCOUNT) and not connection.calls


def test_explicit_manual_processing_while_off_does_not_enable_or_replay(stack):
    service, receiver, sessions, _, messages, connection, model = stack
    receiver.receive(ACCOUNT, packet(1))
    receiver.receive(ACCOUNT, packet(2, message=[{"type": "text", "data": {"text": "新的问题"}}]))
    assert service.process_once(ACCOUNT, f"private:{PEER}")["accepted"]
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] != "running")
    item = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert item["status"] == "done" and item["triggerText"] == "群友: 新的问题"
    assert not service.status()["enabled"] and len(model.calls) == 1 and len(connection.calls) == 1
    assert item["records"][0]["mode"] == "manual" and item["records"][0]["triggerIds"] == [2]
    receiver.receive(ACCOUNT, packet(3))
    time.sleep(0.05)
    assert len(model.calls) == 1


def test_manual_rerun_creates_new_record_preserves_receipts_and_requires_live_source(stack):
    service, receiver, sessions, _, messages, connection, model = stack
    key = f"private:{PEER}"
    receiver.receive(ACCOUNT, packet())
    service.process_once(ACCOUNT, key)
    wait(
        lambda: (
            sessions.list(ACCOUNT)
            and sessions.list(ACCOUNT)[0]["status"] != "running"
            and not service.status()["active"]
        )
    )
    original = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    service.process_once(ACCOUNT, key, retry_of=original["id"])
    wait(lambda: len(sessions.list(ACCOUNT)) == 2 and not service.status()["active"])
    items = sessions.list(ACCOUNT)
    retry = sessions.get(ACCOUNT, items[0]["id"])
    assert retry["id"] != original["id"] and retry["records"][0]["retryOf"] == original["id"]
    assert sessions.get(ACCOUNT, original["id"]) == original
    assert len(model.calls) == 2 and len(connection.calls) == 2
    assert retry["status"] == "done" and len(retry["sent"]) == 1
    assert retry["sent"][0]["messageId"] != original["sent"][0]["messageId"]
    messages.recall(ACCOUNT, key, "1")
    with pytest.raises(ValueError, match="撤回"):
        service.process_once(ACCOUNT, key, retry_of=original["id"])
    assert len(sessions.list(ACCOUNT)) == 2


def test_manual_processing_rejects_wrong_account_denied_and_empty_chats(stack):
    service, receiver, sessions, settings, messages, connection, model = stack
    key = f"private:{PEER}"
    with pytest.raises(ValueError, match="账号"):
        service.process_once(OTHER, key)
    with pytest.raises(ValueError, match="没有可处理"):
        service.process_once(ACCOUNT, key)
    receiver.receive(ACCOUNT, packet())
    settings.save(ACCOUNT, {"deny": {"private": [PEER]}})
    with pytest.raises(ValueError, match="白名单"):
        service.process_once(ACCOUNT, key)
    assert not sessions.list(ACCOUNT) and not model.calls


def test_stop_one_chat_cancels_model_keeps_other_chat_and_future_auto_messages(stack):
    service, receiver, sessions, settings, messages, connection, model = stack
    settings.save(ACCOUNT, {"allow": {"private": [PEER, OTHER]}})
    entered = {PEER: threading.Event(), OTHER: threading.Event()}
    release = threading.Event()
    cancelled = threading.Event()

    class Blocking:
        async def complete(self, api, history, tools):
            peer = PEER if f"private:{PEER}" in history[-1]["content"] else OTHER
            entered[peer].set()
            try:
                while not release.is_set():
                    await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return result("send_message", "finish")

    service._model = Blocking()
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet(1))
    receiver.receive(ACCOUNT, packet(2, user_id=OTHER))
    assert entered[PEER].wait(2) and entered[OTHER].wait(2)
    item = next(i for i in sessions.list(ACCOUNT) if i["chatKey"] == f"private:{PEER}")
    service.stop_session(ACCOUNT, item["id"])
    assert cancelled.wait(2)
    wait(lambda: sessions.get(ACCOUNT, item["id"])["status"] == "aborted")
    assert service.status()["enabled"]
    release.set()
    wait(lambda: not service.status()["active"])
    assert len(connection.calls) == 1 and connection.calls[0][1]["user_id"] == OTHER
    receiver.receive(ACCOUNT, packet(3))
    wait(lambda: len(connection.calls) == 2)
    assert service.status()["enabled"]


def test_stop_preserves_inflight_receipt_even_after_repeated_stop_and_pause(stack):
    service, receiver, sessions, settings, messages, connection, model = stack
    entered, release = threading.Event(), threading.Event()
    original = connection.invoke

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    connection.invoke = blocked
    receiver.receive(ACCOUNT, packet())
    service.process_once(ACCOUNT, f"private:{PEER}")
    try:
        assert entered.wait(2)
        item = sessions.list(ACCOUNT)[0]
        service.stop_session(ACCOUNT, item["id"])
        service.stop_session(ACCOUNT, item["id"])
        service.pause()
    finally:
        release.set()
    wait(lambda: not service.status()["active"])
    final = sessions.get(ACCOUNT, item["id"])
    assert (
        final["status"] == "aborted"
        and len(final["sent"]) == 1
        and final["sent"][0]["messageId"] == "-1"
    )
    assert len(connection.calls) == 1


def test_duplicate_manual_start_rejected_and_disconnect_blocks_delivery(stack):
    service, receiver, sessions, settings, messages, connection, model = stack
    entered, release = threading.Event(), threading.Event()

    class Blocking:
        async def complete(self, *args):
            entered.set()
            while not release.is_set():
                await asyncio.sleep(0.01)
            return result("send_message", "finish")

    service._model = Blocking()
    receiver.receive(ACCOUNT, packet())
    key = f"private:{PEER}"
    service.process_once(ACCOUNT, key)
    assert entered.wait(2)
    with pytest.raises(ValueError, match="已有处理任务"):
        service.process_once(ACCOUNT, key)
    connection.connected = False
    release.set()
    wait(lambda: not service.status()["active"])
    assert not connection.calls and len(sessions.list(ACCOUNT)) == 1


def test_tool_only_reply_and_finish_have_structured_records_without_null(stack):
    service, receiver, sessions, _, messages, connection, model = stack
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] != "running")
    item = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert item["status"] == "done" and len(connection.calls) == 1 and len(model.calls) == 1
    assert item["usage"]["totalTokens"] == 12 and item["sent"][0]["messageId"] == "-1"
    assert [r["kind"] for r in item["records"]] == ["prompt", "model_request", "tool", "tool"]
    assert connection.calls[0][1]["user_id"] == PEER
    assert sessions.list(OTHER) == [] and sessions.get(OTHER, item["id"]) is None
    assert messages.list_chats(ACCOUNT)[0]["count"] == 2
    receiver.receive(
        ACCOUNT,
        packet(-1, post_type="message_sent", user_id=ACCOUNT, target_id=PEER, message_seq=9),
    )
    assert messages.list_chats(ACCOUNT)[0]["count"] == 2


def test_plain_assistant_analysis_is_not_sent_and_is_an_explicit_error_without_retry(stack):
    service, receiver, sessions, _, _, connection, model = stack
    model.responses = [result(content="我应该回复一句你好，或者保持沉默。")]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "error")
    item = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert not connection.calls and len(model.calls) == 1 and not item["sent"]
    assert "未调用工具" in item["reason"] and item["records"][-1]["kind"] == "error"
    assert any(
        record.get("text") == "我应该回复一句你好，或者保持沉默。" for record in item["records"]
    )


def test_explicit_finish_without_sending_remains_valid_silence(stack):
    service, receiver, sessions, _, _, connection, model = stack
    model.responses = [result("finish")]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] != "running")
    assert (
        sessions.list(ACCOUNT)[0]["status"] == "noreply"
        and not connection.calls
        and len(model.calls) == 1
    )


def test_plain_response_after_confirmed_send_preserves_receipt_and_never_resends(stack):
    service, receiver, sessions, _, _, connection, model = stack
    model.responses = [result("send_message"), result(content="我已经发送了。")]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "error")
    item = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert len(connection.calls) == 1 and len(model.calls) == 2 and len(item["sent"]) == 1
    assert item["sent"][0]["messageId"] == "-1" and "未调用工具" in item["reason"]


def test_round_limit_without_finish_reports_incomplete_processing(stack):
    service, receiver, sessions, settings, _, connection, model = stack
    settings.save(ACCOUNT, {"api": {"maxRounds": 1}})
    model.responses = [result("send_message")]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "error")
    assert (
        "轮数上限" in sessions.list(ACCOUNT)[0]["reason"]
        and len(connection.calls) == 1
        and len(model.calls) == 1
    )


@pytest.mark.parametrize("protocol", ["chat", "responses", "anthropic"])
def test_provider_returning_only_text_never_sends_or_retries_even_when_tools_were_requested(
    stack, protocol
):
    service, receiver, sessions, settings, _, connection, _ = stack
    settings.save(ACCOUNT, {"api": {"protocol": protocol}})
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["tool_choice"] == ({"type": "auto"} if protocol == "anthropic" else "auto")
        if protocol == "chat":
            data = {
                "choices": [
                    {"message": {"role": "assistant", "content": "仅供管理端查看的模型文字"}}
                ]
            }
        elif protocol == "responses":
            data = {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "仅供管理端查看的模型文字"}],
                    }
                ],
            }
        else:
            data = {
                "type": "message",
                "role": "assistant",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "仅供管理端查看的模型文字"}],
            }
        return httpx.Response(200, json=data)

    service._model = ChatClient(transport=httpx.MockTransport(handler))
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "error")
    item = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert len(requests) == 1 and not connection.calls and not item["sent"]
    assert item["records"][-2] == {"kind": "assistant", "text": "仅供管理端查看的模型文字"}


def test_assistant_explanation_alongside_tools_is_never_forwarded_as_reply(stack):
    service, receiver, sessions, _, _, connection, model = stack
    model.responses = [result("send_message", "finish", content="这是内部处理说明。")]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "done")
    item = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert len(connection.calls) == 1 and len(item["sent"]) == 1
    assert item["sent"][0]["text"] == "你好呀" and "内部处理说明" not in json.dumps(
        connection.calls, ensure_ascii=False
    )


def test_group_requires_actual_at_or_reply_to_bot(stack):
    service, receiver, sessions, _, _, connection, model = stack
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet(kind="group"))
    time.sleep(0.08)
    assert not model.calls
    receiver.receive(
        ACCOUNT,
        packet(
            2,
            kind="group",
            message=[
                {"type": "at", "data": {"qq": ACCOUNT}},
                {"type": "text", "data": {"text": "你好"}},
            ],
        ),
    )
    wait(lambda: len(connection.calls) == 1)
    assert connection.calls[0][0] == "send_group_msg"


def test_pause_cancels_inflight_model_and_queued_messages(stack):
    service, receiver, sessions, _, _, connection, _ = stack
    started, cancelled = threading.Event(), threading.Event()

    class Slow:
        async def complete(self, *args):
            started.set()
            try:
                await asyncio.sleep(100)
            finally:
                cancelled.set()

    service._model = Slow()
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    assert started.wait(2)
    receiver.receive(ACCOUNT, packet(2))
    service.enable(ACCOUNT, False)
    assert cancelled.wait(2)
    wait(lambda: service.status()["active"] == 0)
    assert sessions.list(ACCOUNT)[0]["status"] == "aborted" and not connection.calls
    service.enable(ACCOUNT, True)
    time.sleep(0.08)
    assert len(sessions.list(ACCOUNT)) == 1


def test_whitelist_is_checked_again_before_send(stack):
    service, receiver, sessions, settings, _, connection, _ = stack
    entered, release = threading.Event(), threading.Event()

    class Delayed:
        async def complete(self, *args):
            entered.set()
            while not release.is_set():
                await asyncio.sleep(0.01)
            return result("send_message")

    service._model = Delayed()
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    assert entered.wait(2)
    settings.save(ACCOUNT, {"deny": {"private": [PEER]}})
    release.set()
    wait(lambda: sessions.list(ACCOUNT)[0]["status"] == "aborted")
    assert not connection.calls


def test_unconfirmed_send_stops_run_without_retry(stack):
    service, receiver, sessions, _, _, connection, model = stack
    connection.error = EngineError("REQUEST_TIMEOUT", "unknown")
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "error")
    assert len(connection.calls) == 1 and len(model.calls) == 1
    assert not sessions.list(ACCOUNT)[0]["sent"] and "未确认" in sessions.list(ACCOUNT)[0]["reason"]


def test_account_change_never_sends_to_new_account(stack):
    service, receiver, sessions, _, _, connection, model = stack
    connection.account = OTHER
    with pytest.raises(ValueError):
        service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    time.sleep(0.05)
    assert not model.calls and not connection.calls


@pytest.mark.parametrize("withdraw", [True, False])
def test_withdrawn_or_newly_blocked_trigger_cannot_produce_reply(stack, withdraw):
    service, receiver, sessions, settings, _, connection, _ = stack
    entered, release = threading.Event(), threading.Event()

    class Delayed:
        async def complete(self, *args):
            entered.set()
            while not release.is_set():
                await asyncio.sleep(0.01)
            return result("send_message")

    service._model = Delayed()
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    assert entered.wait(2)
    if withdraw:
        receiver.receive(
            ACCOUNT,
            {
                "post_type": "notice",
                "notice_type": "friend_recall",
                "self_id": ACCOUNT,
                "user_id": PEER,
                "message_id": 1,
            },
        )
    else:
        settings.save(ACCOUNT, {"blockedUsers": [PEER]})
    release.set()
    wait(lambda: service.status()["active"] == 0)
    assert sessions.list(ACCOUNT)[0]["status"] == "aborted" and not connection.calls


def test_sent_receipt_is_preserved_when_paused_during_native_send(stack):
    service, receiver, sessions, _, _, connection, model = stack
    entered, release = threading.Event(), threading.Event()
    invoke = connection.invoke

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return invoke(*args, **kwargs)

    connection.invoke = slow
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    assert entered.wait(2)
    service.enable(ACCOUNT, False)
    release.set()
    wait(lambda: service.status()["active"] == 0)
    item = sessions.list(ACCOUNT)[0]
    assert item["status"] == "aborted" and len(item["sent"]) == 1 and len(connection.calls) == 1


def test_sessions_recover_running_and_delete_only_selected_account(stack):
    _, _, sessions, _, _, _, _ = stack
    a = sessions.start(ACCOUNT, f"private:{PEER}", "昵称", "test", "hello")
    b = sessions.start(OTHER, f"private:{PEER}", "昵称", "test", "hello")
    with pytest.raises(ValueError):
        sessions.delete(ACCOUNT, a["id"])
    assert sessions.delete(ACCOUNT) == 0
    SessionStore(sessions._database)
    assert sessions.get(ACCOUNT, a["id"])["status"] == "aborted"
    assert sessions.delete(ACCOUNT) == 1 and sessions.get(OTHER, b["id"]) is not None


def test_model_request_contract_usage_and_safe_provider_errors():
    api = copy.deepcopy(DEFAULTS["api"]) | {
        "baseUrl": "https://model.test/v1",
        "apiKey": "private-key",
        "model": "test",
    }

    def handler(request):
        assert str(request.url) == "https://model.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer private-key"
        body = json.loads(request.content)
        assert body["stream"] is False and body["messages"][0]["content"] == "hi"
        return httpx.Response(
            200,
            json={
                "model": "actual",
                "choices": [{"message": {"content": None, "tool_calls": []}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            },
        )

    response = asyncio.run(
        ChatClient(transport=httpx.MockTransport(handler)).complete(
            api, [{"role": "user", "content": "hi"}], []
        )
    )
    assert response["usage"]["totalTokens"] == 7 and response["model"] == "actual"
    bad = ChatClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, text="private-key: secret")
        )
    )
    with pytest.raises(ModelError) as error:
        asyncio.run(bad.complete(api, [], []))
    assert "401" in str(error.value) and "private-key" not in str(error.value)


@pytest.mark.parametrize("protocol", ["chat", "responses", "anthropic"])
def test_real_protocol_adapter_round_trip_through_agent_preserves_receipts_not_wire_state(
    stack, protocol
):
    service, receiver, sessions, settings, _, connection, _ = stack
    settings.save(ACCOUNT, {"api": {"protocol": protocol}})
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["tool_choice"] == ({"type": "auto"} if protocol == "anthropic" else "auto")
        first = len(requests) == 1
        name = "send_message" if first else "finish"
        args = {"messages": "协议验收"} if first else {"summary": "已完成"}
        if protocol == "chat":
            data = {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": name,
                                    "type": "function",
                                    "function": {"name": name, "arguments": json.dumps(args)},
                                }
                            ],
                        }
                    }
                ]
            }
        elif protocol == "responses":
            if not first:
                assert any(i.get("type") == "function_call_output" for i in body["input"])
            data = {
                "status": "completed",
                "output": [
                    {"type": "reasoning", "summary": [], "encrypted_content": "run-only-secret"},
                    {
                        "type": "function_call",
                        "call_id": name,
                        "name": name,
                        "arguments": json.dumps(args),
                    },
                ],
            }
        else:
            if not first:
                assert body["messages"][-1]["content"][0]["type"] == "tool_result"
            data = {
                "type": "message",
                "role": "assistant",
                "stop_reason": "tool_use",
                "content": [
                    {"type": "thinking", "thinking": "plan", "signature": "run-only-secret"},
                    {"type": "tool_use", "id": name, "name": name, "input": args},
                ],
            }
        return httpx.Response(200, json=data)

    service._model = ChatClient(transport=httpx.MockTransport(handler))
    receiver.receive(ACCOUNT, packet())
    service.process_once(ACCOUNT, f"private:{PEER}")
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] != "running")
    item = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert item["status"] == "done" and len(requests) == 2 and len(connection.calls) == 1
    assert item["sent"][0]["text"] == "协议验收"
    assert "run-only-secret" not in json.dumps(item) and "_wire" not in json.dumps(item)


def test_same_chat_batches_and_different_chats_concurrency_is_bounded(stack):
    service, receiver, sessions, settings, _, _, _ = stack
    peers = [PEER, "22334455", "33445566"]
    settings.save(ACCOUNT, {"allow": {"private": peers}})
    entered, peak, count = [], [0], [0]

    class Parallel:
        async def complete(self, api, messages, tools):
            count[0] += 1
            peak[0] = max(peak[0], count[0])
            entered.append(messages)
            try:
                await asyncio.sleep(0.08)
                return result("finish")
            finally:
                count[0] -= 1

    service._model = Parallel()
    service.enable(ACCOUNT, True)
    for i, peer in enumerate(peers):
        for j in range(2):
            receiver.receive(
                ACCOUNT,
                packet(
                    10 * i + j + 1,
                    user_id=peer,
                    sender={"user_id": peer, "nickname": "友"},
                    message=[{"type": "text", "data": {"text": f"消息{j + 1}"}}],
                ),
            )
    wait(lambda: len(sessions.list(ACCOUNT)) == 3 and service.status()["active"] == 0)
    assert peak[0] == 2 and len(entered) == 3
    assert all(s["triggerText"] == "友: 消息2" for s in sessions.list(ACCOUNT))
    assert all(
        len(messages[1]["content"].split("【本次新消息】\n")[1].splitlines()) == 2
        for messages in entered
    )


@pytest.mark.parametrize("intervening", [1, 205])
def test_batch_keeps_trigger_rows_when_other_messages_intervene(stack, intervening):
    service, _, sessions, settings, messages, _, _ = stack
    settings.save(ACCOUNT, {"contextLimit": 1})
    service.enable(ACCOUNT, True)
    first = messages.ingest(ACCOUNT, packet(1))
    for mid in range(2, intervening + 2):
        messages.ingest(ACCOUNT, packet(mid))
    last = messages.ingest(ACCOUNT, packet(intervening + 2))
    epoch = (service._epoch, 0, False)
    future = asyncio.run_coroutine_threadsafe(
        service._run(ACCOUNT, f"private:{PEER}", [first, last], epoch), service._loop
    )
    future.result(timeout=5)
    session = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert session["records"][0]["triggerIds"] == [first["id"], last["id"]]
    service.process_once(ACCOUNT, f"private:{PEER}", retry_of=session["id"])
    wait(lambda: len(sessions.list(ACCOUNT)) == 2 and not service.status()["active"])
    retry = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert retry["records"][0]["triggerIds"] == [first["id"], last["id"]]


def test_late_message_after_drain_completion_is_rescheduled(stack, monkeypatch):
    service, _, _, _, messages, _, _ = stack
    service.enable(ACCOUNT, True)
    item = messages.ingest(ACCOUNT, packet())
    key = item["chatKey"]
    processed = []

    async def run(_account, _key, batch, _epoch):
        processed.extend(batch)

    monkeypatch.setattr(service, "_run", run)

    async def finish_with_late_message():
        old = asyncio.create_task(asyncio.sleep(0))
        await old
        epoch = (service._epoch, 0, False)
        service._tasks[key] = old
        service._drain_args[key] = (ACCOUNT, epoch)
        service._pending[key] = [item]
        service._done(key, old)
        await asyncio.sleep(0.1)
        assert processed == [item]
        assert key not in service._tasks and key not in service._pending

    asyncio.run_coroutine_threadsafe(finish_with_late_message(), service._loop).result(timeout=5)


def test_parallel_chat_replies_wait_for_serial_native_actions(stack):
    service, receiver, sessions, settings, _, connection, _ = stack
    second = "22334455"
    settings.save(ACCOUNT, {"allow": {"private": [PEER, second]}})
    native_busy = threading.Lock()
    invoke = connection.invoke

    def serial_only(*args, **kwargs):
        if not native_busy.acquire(blocking=False):
            raise EngineError("BUSY", "overlapping action")
        try:
            time.sleep(0.05)
            return invoke(*args, **kwargs)
        finally:
            native_busy.release()

    connection.invoke = serial_only
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    receiver.receive(
        ACCOUNT, packet(2, user_id=second, sender={"user_id": second, "nickname": "好友乙"})
    )
    wait(lambda: len(sessions.list(ACCOUNT)) == 2 and service.status()["active"] == 0)
    assert len(connection.calls) == 2 and all(
        item["status"] == "done" for item in sessions.list(ACCOUNT)
    )
