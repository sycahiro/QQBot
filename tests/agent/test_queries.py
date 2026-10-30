import asyncio
import json
import threading

import pytest
from test_agent import ACCOUNT, OTHER, PEER, packet, result, wait

from QQBot.agent.prompt import TOOLS
from QQBot.agent.queries import MessageQueries, expand_nodes
from QQBot.desktop.bridge import DesktopBridge
from QQBot.desktop.paths import DesktopPaths
from QQBot.qq.engine import EngineError
from QQBot.storage.accounts import AccountStorage

KEY = f"private:{PEER}"
GROUP = "group:99887766"


def forward(mid=-10, **fields):
    return packet(
        mid, **({"message": [{"type": "forward", "data": {"id": "old-resource"}}]} | fields)
    )


def nodes(count=2):
    return [
        {
            "sender": {"nickname": f"转发用户{i}", "user_id": str(22000000 + i)},
            "content": [
                {"type": "text", "data": {"text": f"转发正文{i}"}},
                {"type": "image", "data": {"url": "https://private.test/ticket"}},
            ],
        }
        for i in range(count)
    ]


def reader(store, *, native=None, permit=lambda: True, admitted=lambda user: True):
    calls = []

    async def read(action, params):
        calls.append((action, params))
        if native:
            return await native(action, params)
        return {
            "status": "ok",
            "data": forward(-10, message=[{"type": "forward", "data": {"id": "fresh-resource"}}])
            if action == "get_msg"
            else {"messages": nodes()},
        }

    tracked = []
    query = MessageQueries(store, read, tracked.append, permit, admitted)
    return query, calls, tracked


def execute(query, name, args=None, key=KEY, account=ACCOUNT):
    return asyncio.run(query.execute(name, account, key, {} if args is None else args))


def call(name, args, identity="query"):
    value = result()
    value["message"]["tool_calls"] = [
        {
            "id": identity,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        }
    ]
    return value


def test_forward_uses_fresh_verified_resource_for_negative_message_id_and_caches(stack):
    _, receiver, _, _, store, _, _ = stack
    receiver.receive(ACCOUNT, forward())
    query, calls, tracked = reader(store)
    value = execute(query, "read_forward", {"messageId": -10})
    assert calls == [
        ("get_msg", {"message_id": "-10"}),
        ("get_forward_msg", {"id": "fresh-resource"}),
    ]
    assert value["shown"] == 2 and "[图片]" in value["text"] and "转发正文0" in value["text"]
    assert "private.test" not in json.dumps(value) and "resource" not in json.dumps(value)
    assert store.messages(ACCOUNT, KEY)["items"][0]["hasForward"]
    assert store.message_detail(ACCOUNT, KEY, -10)["text"] == value["text"]
    assert tracked[0]["mid"] == "-10"
    assert execute(query, "read_forward", {"messageId": "-10"})["cached"] and len(calls) == 2
    query2, calls2, _ = reader(store)
    assert execute(query2, "read_forward", {"messageId": -10})["cached"] and not calls2


def test_detail_is_local_scoped_bounded_and_preserves_reply_id(stack):
    _, receiver, _, _, store, _, _ = stack
    receiver.receive(
        ACCOUNT,
        packet(
            1,
            message=[
                {"type": "text", "data": {"text": "长" * 18000}},
                {"type": "reply", "data": {"id": "-9"}},
                {"type": "image", "data": {"url": "secret-url"}},
            ],
        ),
    )
    query, calls, _ = reader(store)
    detail = execute(query, "get_message_detail", {"messageId": 1})
    assert (
        detail["senderId"] == PEER
        and detail["reply"] == "-9"
        and len(detail["text"]) == 16000
        and detail["truncated"]
    )
    assert "segments" not in detail and "secret-url" not in json.dumps(detail) and not calls
    for key, account in [(f"private:{OTHER}", ACCOUNT), (KEY, OTHER)]:
        with pytest.raises(ValueError):
            execute(query, "get_message_detail", {"messageId": 1}, key, account)
    store.recall(ACCOUNT, KEY, 1)
    with pytest.raises(ValueError, match="撤回"):
        execute(query, "get_message_detail", {"messageId": 1})


def test_ambiguous_mid_and_blocked_sender_are_rejected(stack):
    _, receiver, _, _, store, _, _ = stack
    receiver.receive(ACCOUNT, packet(1, message_seq=1))
    receiver.receive(ACCOUNT, packet(1, message_seq=2))
    query, calls, _ = reader(store)
    with pytest.raises(ValueError, match="歧义"):
        execute(query, "get_message_detail", {"messageId": 1})
    receiver.receive(ACCOUNT, packet(2))
    query, _, _ = reader(store, admitted=lambda _: False)
    with pytest.raises(ValueError, match="屏蔽"):
        execute(query, "get_message_detail", {"messageId": 2})
    assert not calls


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"messageId": True},
        {"messageId": 0},
        {"messageId": "resource"},
        {"messageId": 1, "id": "evil"},
    ],
)
def test_query_rejects_model_resource_ids_and_extra_fields(stack, args):
    query, calls, _ = reader(stack[4])
    with pytest.raises(ValueError):
        execute(query, "read_forward", args)
    assert not calls


def test_active_members_uses_current_chat_recent_messages_not_forward_identities(stack):
    store = stack[4]
    for mid, sender, stamp in [
        (1, PEER, 1000),
        (2, OTHER, 1002),
        (3, PEER, 1003),
        (4, "33445566", 1004),
    ]:
        store.ingest(
            ACCOUNT,
            packet(
                mid,
                kind="group",
                user_id=sender,
                sender={"nickname": f"名字{mid}", "user_id": sender},
                time=stamp,
            ),
        )
    store.ingest(ACCOUNT, packet(5, kind="group", user_id=ACCOUNT, post_type="message_sent"))
    store.ingest(ACCOUNT, forward(6, message_type="group", user_id="55667788"))
    store.recall(ACCOUNT, GROUP, 6)
    query, calls, _ = reader(store, admitted=lambda user: user != "33445566")
    value = execute(query, "get_active_members", {"limit": 2}, GROUP)
    assert value["members"] == [
        {"userId": PEER, "name": "名字3", "lastSeen": 1003000, "recentCount": 2},
        {"userId": OTHER, "name": "名字2", "lastSeen": 1002000, "recentCount": 1},
    ]
    assert not calls
    assert not execute(query, "get_active_members", {}, KEY)["members"]


@pytest.mark.parametrize("limit", [0, 21, True, "5", 1.5])
def test_member_limit_is_strict(stack, limit):
    query, _, _ = reader(stack[4])
    with pytest.raises(ValueError):
        execute(query, "get_active_members", {"limit": limit})


def test_active_member_tracks_all_count_sources_but_not_members_outside_limit(stack):
    store = stack[4]
    for mid, user, stamp in [(1, PEER, 1000), (2, OTHER, 1002), (None, PEER, 1003)]:
        store.ingest(ACCOUNT, packet(mid, kind="group", user_id=user, time=stamp))
    query, calls, tracked = reader(store)
    value = execute(query, "get_active_members", {"limit": 1}, GROUP)
    assert value["members"][0]["userId"] == PEER and value["members"][0]["recentCount"] == 2
    assert [item["mid"] for item in tracked] == ["1", None]
    assert len({item["id"] for item in tracked}) == 2 and not calls


@pytest.mark.parametrize("change", ["recall", "delete"])
@pytest.mark.parametrize("target", ["returned", "excluded"])
def test_active_member_source_invalidation_stops_only_affected_returned_members(
    stack, change, target
):
    service, receiver, sessions, _, store, connection, _ = stack
    receiver.receive(ACCOUNT, packet(1, kind="group", time=1000))
    receiver.receive(ACCOUNT, packet(2, kind="group", time=2000, user_id=OTHER))
    receiver.receive(ACCOUNT, packet(3, kind="group", time=3000))

    class Model:
        calls = 0

        async def complete(self, *args):
            self.calls += 1
            if self.calls == 1:
                return call("get_active_members", {"limit": 1})
            mid = 1 if target == "returned" else 2
            if change == "recall":
                store.recall(ACCOUNT, GROUP, mid)
            else:
                identity = store.message_detail(ACCOUNT, GROUP, mid)["id"]
                with store._database.lock, store._database.connection as db:
                    db.execute("DELETE FROM messages WHERE id=?", (identity,))
            return result("send_message", "finish")

    service._model = Model()
    service.process_once(ACCOUNT, GROUP)
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] != "running")
    item = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert item["status"] == ("aborted" if target == "returned" else "done")
    assert len(connection.calls) == (0 if target == "returned" else 1)
    assert not service._query_sources


def test_forward_expansion_bounds_nodes_text_nested_and_cq_segments():
    value = expand_nodes(nodes(100))
    assert value["omitted"] > 0 and value["shown"] <= 30 and len(value["text"]) < 3300
    assert "private.test" not in value["text"]
    value = expand_nodes(
        [
            {"sender": {"nickname": "name"}, "message": "hello[CQ:image,file=private-path]"},
            {"content": [{"type": "forward", "data": {"id": "nested-secret"}}]},
        ]
    )
    assert (
        "hello" in value["text"]
        and "[合并转发聊天记录]" in value["text"]
        and "secret" not in value["text"]
    )
    for bad in [None, [], {}, [None], [{"content": None}]]:
        with pytest.raises(ValueError):
            expand_nodes(bad)


@pytest.mark.parametrize(
    "field,value",
    [
        ("group_id", "88776655"),
        ("user_id", OTHER),
        ("message_id", -11),
        ("message_seq", 8),
        ("self_id", OTHER),
    ],
)
def test_native_identity_must_match_before_forward_request(stack, field, value):
    store = stack[4]
    store.ingest(ACCOUNT, forward(message_type="group", message_seq=7))

    async def native(action, params):
        assert action == "get_msg"
        data = forward(message_type="group", message_seq=7)
        data[field] = value
        return {"status": "ok", "data": data}

    query, calls, _ = reader(store, native=native)
    with pytest.raises(ValueError, match="不一致"):
        execute(query, "read_forward", {"messageId": -10}, GROUP)
    assert len(calls) == 1 and not store.message_detail(ACCOUNT, GROUP, -10)["text"].startswith(
        "[合并转发 共"
    )


@pytest.mark.parametrize("stage", ["get_msg", "get_forward_msg"])
@pytest.mark.parametrize("change", ["recall", "delete", "pause"])
def test_source_change_during_native_read_does_not_write_or_return(stack, stage, change):
    store = stack[4]
    store.ingest(ACCOUNT, forward())
    running = True

    def permit():
        try:
            return running and store.message_detail(ACCOUNT, KEY, -10)["id"] == 1
        except ValueError:
            return False

    async def native(action, params):
        nonlocal running
        if action == stage:
            if change == "recall":
                store.recall(ACCOUNT, KEY, -10)
            elif change == "delete":
                store.delete(ACCOUNT, KEY)
            else:
                running = False
        return {"status": "ok", "data": forward() if action == "get_msg" else {"messages": nodes()}}

    query, _, _ = reader(store, native=native, permit=permit)
    with pytest.raises(asyncio.CancelledError):
        execute(query, "read_forward", {"messageId": -10})
    items = store.messages(ACCOUNT, KEY)["items"]
    assert not any(i["text"].startswith("[合并转发 共") for i in items)


def test_forward_failures_consume_budget_and_no_arbitrary_fetch(stack):
    store = stack[4]
    store.ingest(ACCOUNT, forward())

    async def failed(action, params):
        return {"status": "failed", "data": {"secret": "provider-body"}}

    query, calls, _ = reader(store, native=failed)
    for _ in range(3):
        with pytest.raises(ValueError) as error:
            execute(query, "read_forward", {"messageId": -10})
        assert "secret" not in str(error.value)
    with pytest.raises(ValueError, match="最多"):
        execute(query, "read_forward", {"messageId": -10})
    assert len(calls) == 3


def test_storage_write_cannot_resurrect_deleted_or_recalled_source(stack):
    store = stack[4]
    store.ingest(ACCOUNT, forward())
    old = store.message_detail(ACCOUNT, KEY, -10)
    store.recall(ACCOUNT, KEY, -10)
    with pytest.raises(ValueError):
        store.expand_forward(ACCOUNT, KEY, old, "[合并转发 共1条]\nhello")
    assert store.messages(ACCOUNT, KEY)["items"][0]["withdrawn"]
    store.delete(ACCOUNT, KEY)
    with pytest.raises(ValueError):
        store.expand_forward(ACCOUNT, KEY, old, "hello")
    assert not store.messages(ACCOUNT, KEY)["items"]


def test_queries_pass_through_account_directory_and_persist_after_reopen(tmp_path):
    root = tmp_path / "accounts"
    storage = AccountStorage(root)
    try:
        storage.messages.ingest(ACCOUNT, forward())
        storage.messages.ingest(OTHER, forward(self_id=OTHER))
        query, _, _ = reader(storage.messages)
        value = execute(query, "read_forward", {"messageId": -10})
        assert storage.messages.message_detail(ACCOUNT, KEY, -10)["text"] == value["text"]
        assert not storage.messages.message_detail(OTHER, KEY, -10)["text"].startswith(
            "[合并转发 共"
        )
    finally:
        storage.close()
    storage = AccountStorage(root)
    try:
        query, calls, _ = reader(storage.messages)
        assert execute(query, "read_forward", {"messageId": -10})["cached"] and not calls
    finally:
        storage.close()


def install_native(connection):
    def native(action, params, *, expected_account):
        assert connection.account == expected_account
        connection.calls.append((action, params))
        if action == "get_msg":
            return {"status": "ok", "data": forward()}
        if action == "get_forward_msg":
            return {"status": "ok", "data": {"messages": nodes()}}
        return {"status": "ok", "data": {"message_id": 100}}

    connection.invoke = native


def test_model_tools_are_wired_and_expansion_is_available_without_vision(stack):
    service, receiver, sessions, _, _store, connection, model = stack
    assert {"read_forward", "get_message_detail", "get_active_members"} <= {
        t["function"]["name"] for t in TOOLS
    }
    install_native(connection)
    model.responses = [
        call("read_forward", {"messageId": -10}),
        call("get_message_detail", {"messageId": -10}, "detail"),
        call("get_active_members", {}, "members"),
        result("send_message", "finish"),
    ]
    receiver.receive(ACCOUNT, forward())
    service.process_once(ACCOUNT, KEY)
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] != "running")
    item = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert item["status"] == "done" and len(model.calls) == 4 and not service.status()["enabled"]
    assert [r["name"] for r in item["records"] if r["kind"] == "tool"][:3] == [
        "read_forward",
        "get_message_detail",
        "get_active_members",
    ]
    assert not any(r.get("isError") for r in item["records"])
    assert "转发正文0" in json.dumps(model.calls, ensure_ascii=False)
    assert not service._query_sources


def test_recall_of_queried_nontrigger_source_stops_later_send(stack):
    service, receiver, sessions, _, store, connection, _model = stack
    receiver.receive(ACCOUNT, packet(1))
    receiver.receive(ACCOUNT, packet(2))

    class Model:
        calls = 0

        async def complete(self, *args):
            self.calls += 1
            if self.calls == 1:
                return call("get_message_detail", {"messageId": 1})
            store.recall(ACCOUNT, KEY, 1)
            return result("send_message", "finish")

    service._model = Model()
    service.process_once(ACCOUNT, KEY)
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] != "running")
    assert sessions.list(ACCOUNT)[0]["status"] == "aborted" and not connection.calls


@pytest.mark.parametrize("mid", [1, None])
@pytest.mark.parametrize("change", ["recall", "delete"])
def test_recent_query_tracks_retained_rows_even_without_native_ids(stack, mid, change):
    service, receiver, sessions, _, store, connection, _ = stack
    receiver.receive(ACCOUNT, packet(mid))
    receiver.receive(ACCOUNT, packet(2))

    class Model:
        calls = 0

        async def complete(self, *args):
            self.calls += 1
            if self.calls == 1:
                return call("get_recent_messages", {})
            if change == "recall" and mid is not None:
                store.recall(ACCOUNT, KEY, mid)
            else:
                # Delete only the queried, nontrigger row; the trigger remains.
                with store._database.lock, store._database.connection as db:
                    db.execute("DELETE FROM messages WHERE id=1")
            return result("send_message", "finish")

    service._model = Model()
    service.process_once(ACCOUNT, KEY)
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] != "running")
    assert sessions.list(ACCOUNT)[0]["status"] == "aborted" and not connection.calls
    assert not service._query_sources


def test_recent_query_omits_withdrawn_and_blocked_members(stack):
    service, receiver, sessions, settings, store, connection, model = stack
    receiver.receive(
        ACCOUNT,
        packet(
            1,
            kind="group",
            user_id=OTHER,
            message=[{"type": "text", "data": {"text": "blocked-history"}}],
        ),
    )
    receiver.receive(
        ACCOUNT,
        packet(2, kind="group", message=[{"type": "text", "data": {"text": "withdrawn-history"}}]),
    )
    receiver.receive(ACCOUNT, packet(3, kind="group"))
    settings.save(ACCOUNT, {"blockedUsers": [OTHER]})
    store.recall(ACCOUNT, GROUP, 2)
    model.responses = [call("get_recent_messages", {}), result("finish")]
    service.process_once(ACCOUNT, GROUP)
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] != "running")
    item = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    recent = next(
        r["result"]["messages"] for r in item["records"] if r.get("name") == "get_recent_messages"
    )
    assert [m["mid"] for m in recent] == ["3"] and not connection.calls


def test_stop_drains_native_read_and_prevents_expansion_and_next_model(stack):
    service, receiver, sessions, _, store, connection, model = stack
    entered, release = threading.Event(), threading.Event()

    def native(action, params, *, expected_account):
        connection.calls.append((action, params))
        entered.set()
        release.wait(3)
        return {"status": "ok", "data": forward()}

    connection.invoke = native
    model.responses = [call("read_forward", {"messageId": -10})]
    receiver.receive(ACCOUNT, forward())
    service.process_once(ACCOUNT, KEY)
    assert entered.wait(2)
    service.stop_session(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    release.set()
    wait(lambda: not service.status()["active"])
    assert (
        sessions.list(ACCOUNT)[0]["status"] == "aborted"
        and len(connection.calls) == len(model.calls) == 1
    )
    assert not store.message_detail(ACCOUNT, KEY, -10)["text"].startswith("[合并转发 共")


def bridge_for(tmp_path, stack):
    service, _, sessions, settings, store, connection, _ = stack
    original_status = connection.status
    connection.status = lambda: {**original_status(), "state": "ready"}

    class Selection:
        def read(self):
            return connection.account

    return DesktopBridge(
        DesktopPaths(tmp_path, tmp_path),
        lambda **_: None,
        selection=Selection(),
        connection=connection,
        messages=store,
        settings=settings,
        agent=service,
        sessions=sessions,
    )


def test_manual_expand_while_off_is_account_scoped_and_saves_only_source(tmp_path, stack):
    service, receiver, _, settings, _store, connection, model = stack
    install_native(connection)
    receiver.receive(ACCOUNT, forward())
    bridge = bridge_for(tmp_path, stack)
    assert not bridge.expand_forward(KEY, -10, OTHER)["ok"]
    value = bridge.expand_forward(KEY, -10, ACCOUNT)
    assert value["ok"], value
    assert not service.status()["enabled"] and not model.calls
    assert [name for name, _ in connection.calls] == ["get_msg", "get_forward_msg"]
    assert bridge.expand_forward(KEY, -10, ACCOUNT)["cached"] and len(connection.calls) == 2
    settings.save(ACCOUNT, {"deny": {"private": [PEER]}})
    assert not bridge.expand_forward(KEY, -10, ACCOUNT)["ok"] and len(connection.calls) == 2


def test_manual_expand_switch_and_native_error_are_not_saved(tmp_path, stack):
    _, receiver, _, _, store, connection, _ = stack
    receiver.receive(ACCOUNT, forward())
    bridge = bridge_for(tmp_path, stack)

    def native(action, params, *, expected_account):
        connection.account = OTHER
        return {"status": "ok", "data": forward()}

    connection.invoke = native
    assert not bridge.expand_forward(KEY, -10, ACCOUNT)["ok"]
    connection.account = ACCOUNT

    def failed(*args, **kwargs):
        raise EngineError("FAILED", "private-resource-secret")

    connection.invoke = failed
    value = bridge.expand_forward(KEY, -10, ACCOUNT)
    assert not value["ok"] and "private-resource-secret" not in json.dumps(value)
    assert not store.message_detail(ACCOUNT, KEY, -10)["text"].startswith("[合并转发 共")
