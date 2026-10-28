import base64
import copy
import json
import threading

import pytest
from qqbot.agent.config import DEFAULTS
from qqbot.agent.images import ImageDownloader, prepare_image
from qqbot.agent.prompt import sticker_tools
from qqbot.desktop.bridge import DesktopBridge
from qqbot.desktop.paths import DesktopPaths
from qqbot.qq.engine import EngineError
from qqbot.storage.accounts import AccountStorage
from qqbot.storage.stickers import StickerStore
from test_agent import ACCOUNT, OTHER, PEER, packet, result, wait
from test_agent import stack as stack
from test_images import KEY, image_packet, raster


@pytest.fixture
def library(stack):
    service, receiver, sessions, settings, messages, connection, model = stack
    store = StickerStore(messages._database)
    service._stickers = store
    settings.save(
        ACCOUNT,
        {
            "api": {"vision": True, "sendImages": True},
            "sticker": {"enabled": True, "collectEnabled": True},
        },
    )
    yield (*stack, store)


def call(name, args, identifier=None):
    r = result()
    r["message"]["tool_calls"] = [
        {
            "id": identifier or name,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        }
    ]
    return r


def install_download(monkeypatch, connection):
    downloads = []

    async def download(self, url, permit):
        downloads.append(url)
        return raster()

    monkeypatch.setattr(ImageDownloader, "fetch", download)
    invoke = connection.invoke

    def native(action, params, **kwargs):
        if action == "get_msg":
            connection.calls.append((action, params))
            return {"status": "ok", "data": image_packet(params["message_id"])}
        return invoke(action, params, **kwargs)

    connection.invoke = native
    return downloads


def completed(service, receiver, sessions, event=None):
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, event or packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] != "running")
    return sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])


def test_library_is_account_scoped_deduped_persistent_and_metadata_only(library):
    *_, store = library
    image = prepare_image(raster())
    first = store.add(ACCOUNT, image, "开心", ["点头"], "赞同")
    assert first["collected"] and store.add(ACCOUNT, image, "重复")["duplicate"]
    assert len(store.list(ACCOUNT)) == 1 and not store.list(OTHER)
    assert len(store.list(ACCOUNT, "开心")) == 1 and not store.list(ACCOUNT, "missing")
    assert "image" not in store.list(ACCOUNT)[0] and "part" not in store.list(ACCOUNT)[0]
    other = store.add(OTHER, image, "other")
    assert other["id"] != first["id"]
    with pytest.raises(ValueError):
        store.get(OTHER, first["id"])
    assert store.get(ACCOUNT, first["id"])["part"] == image["part"]
    assert store.note(ACCOUNT, first["id"], "新备注", ["开心"], "庆祝")["note"] == "新备注"


@pytest.mark.parametrize(
    "bad", ["../secret", "file:///private", "https://remote.test/a", None, ["a"]]
)
def test_no_paths_urls_or_other_accounts_can_select_image(library, bad):
    *_, store = library
    with pytest.raises(ValueError):
        store.get(ACCOUNT, bad)
    if bad is not None:
        with pytest.raises(ValueError):
            store.delete(ACCOUNT, bad)


def test_original_source_must_still_exist_at_collection_commit(library):
    _, _, _, _, messages, _, _, store = library
    item = messages.ingest(ACCOUNT, image_packet())
    source = {"chatKey": KEY, "id": item["id"], "mid": item["mid"]}
    messages.recall(ACCOUNT, KEY, "1")
    with pytest.raises(ValueError, match="撤回"):
        store.add(ACCOUNT, prepare_image(raster()), source=source)
    assert not store.list(ACCOUNT)


def test_capacity_and_annotation_bounds(library):
    *_, store = library
    with pytest.raises(ValueError):
        store.add(ACCOUNT, prepare_image(raster()), "x" * 121)
    with pytest.raises(ValueError):
        store.add(ACCOUNT, prepare_image(raster()), tags=["x"] * 9)
    with store._database.lock, store._database.connection as db:
        image = base64.b64decode(
            prepare_image(raster())["part"]["image_url"]["url"].split(",", 1)[1]
        )
        db.executemany(
            "INSERT INTO stickers VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (f"{i:032x}", ACCOUNT, f"seed-{i}", image, "", "[]", "", 30, 20, 0, 1, 0)
                for i in range(200)
            ],
        )
    with pytest.raises(ValueError, match="200"):
        store.add(ACCOUNT, prepare_image(raster()))
    assert len(store.list(ACCOUNT)) == 200
    assert store.delete(ACCOUNT) == 200 and not store.list(ACCOUNT)


def test_both_tools_and_runtime_gates_are_default_off():
    config = copy.deepcopy(DEFAULTS)
    assert sticker_tools(config) == []
    config["sticker"]["enabled"] = True
    assert {t["function"]["name"] for t in sticker_tools(config)} == {
        "list_stickers",
        "sticker_note",
    }
    config["api"]["vision"] = True
    assert "get_sticker_image" in {t["function"]["name"] for t in sticker_tools(config)}
    assert "send_sticker" not in {t["function"]["name"] for t in sticker_tools(config)}


def test_collection_reuses_actual_reviewed_image_and_keeps_bytes_out_of_sessions(
    library, monkeypatch
):
    service, receiver, sessions, settings, messages, connection, model, store = library
    downloads = install_download(monkeypatch, connection)
    model.responses = [
        call("get_message_images", {"messageId": 1}),
        call("collect_sticker", {"messageId": 1, "note": "开心"}),
        result("finish"),
    ]
    item = completed(service, receiver, sessions, image_packet())
    assert (
        len(downloads) == 1
        and len(store.list(ACCOUNT)) == 1
        and store.list(ACCOUNT)[0]["note"] == "开心"
    )
    assert [name for name, _ in connection.calls] == ["get_msg"]
    serialized = json.dumps(item, ensure_ascii=False)
    assert "base64" not in serialized and "private-ticket" not in serialized
    assert (
        store.get(ACCOUNT, store.list(ACCOUNT)[0]["id"])["part"] == prepare_image(raster())["part"]
    )


def test_same_response_cannot_look_and_collect_without_model_review(library, monkeypatch):
    service, receiver, sessions, _, _, connection, model, store = library
    install_download(monkeypatch, connection)
    combined = call("get_message_images", {"messageId": 1})
    combined["message"]["tool_calls"] += call("collect_sticker", {"messageId": 1})["message"][
        "tool_calls"
    ]
    model.responses = [combined, result("finish")]
    item = completed(service, receiver, sessions, image_packet())
    assert not store.list(ACCOUNT) and any(
        r.get("name") == "collect_sticker" and r["isError"] for r in item["records"]
    )


def test_sticker_send_uses_exact_preview_bytes_and_confirmed_receipt(library):
    service, receiver, sessions, _, _, connection, model, store = library
    entry = store.add(ACCOUNT, prepare_image(raster()), "开心")
    model.responses = [
        call("get_sticker_image", {"stickerId": entry["id"]}),
        call("send_sticker", {"stickerId": entry["id"]}),
        result("finish"),
    ]
    item = completed(service, receiver, sessions)
    assert (
        item["status"] == "done"
        and len(connection.calls) == 1
        and item["sent"][0]["messageId"] == "-1"
    )
    sent = connection.calls[0][1]["message"][0]["data"]["file"].removeprefix("base64://")
    assert (
        "data:image/jpeg;base64," + sent
        == store.get(ACCOUNT, entry["id"])["part"]["image_url"]["url"]
    )
    assert store.list(ACCOUNT)[0]["uses"] == 1


def test_new_request_can_send_same_sticker_while_each_run_skips_its_own_duplicate(library):
    service, receiver, sessions, _, _, connection, model, store = library
    entry = store.add(ACCOUNT, prepare_image(raster()), "开心")
    sequence = [
        call("get_sticker_image", {"stickerId": entry["id"]}),
        call("send_sticker", {"stickerId": entry["id"]}),
        call("send_sticker", {"stickerId": entry["id"]}, "repeat"),
        result("finish"),
    ]
    model.responses = sequence * 2
    first = completed(service, receiver, sessions)
    wait(lambda: not service.status()["active"])
    receiver.receive(ACCOUNT, packet(2))
    wait(lambda: len(sessions.list(ACCOUNT)) == 2 and not service.status()["active"])
    second = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    for item in (first, second):
        assert item["status"] == "done" and len(item["sent"]) == 1
        sends = [r["result"] for r in item["records"] if r.get("name") == "send_sticker"]
        assert sends[0]["sent"] == 1 and sends[1]["deduped"] == 1
        assert "本次处理已确认发送" in sends[1]["message"]
    assert first["sent"][0]["messageId"] != second["sent"][0]["messageId"]
    assert len(connection.calls) == store.list(ACCOUNT)[0]["uses"] == 2


def test_same_response_cannot_view_then_send(library):
    service, receiver, sessions, _, _, connection, model, store = library
    entry = store.add(ACCOUNT, prepare_image(raster()))
    first = call("get_sticker_image", {"stickerId": entry["id"]})
    first["message"]["tool_calls"] += call("send_sticker", {"stickerId": entry["id"]})["message"][
        "tool_calls"
    ]
    model.responses = [first, result("finish")]
    item = completed(service, receiver, sessions)
    assert not connection.calls and item["status"] == "noreply"


@pytest.mark.parametrize("disabled", ["library", "vision", "send"])
def test_forged_tool_calls_cannot_bypass_opt_in(library, disabled):
    service, receiver, sessions, settings, _, connection, model, store = library
    entry = store.add(ACCOUNT, prepare_image(raster()))
    settings.save(
        ACCOUNT,
        {"sticker": {"enabled": False}}
        if disabled == "library"
        else {"api": {"vision" if disabled == "vision" else "sendImages": False}},
    )
    model.responses = [
        call("get_sticker_image", {"stickerId": entry["id"]}),
        call("send_sticker", {"stickerId": entry["id"]}),
        result("finish"),
    ]
    item = completed(service, receiver, sessions)
    assert not connection.calls and not item["sent"]


def test_delete_while_waiting_for_queue_stops_sticker_send(library, monkeypatch):
    service, receiver, sessions, _, _, connection, model, store = library
    entry = store.add(ACCOUNT, prepare_image(raster()))
    entered = threading.Event()
    original = service._sender.send_image

    def send(*args):
        entered.set()
        return original(*args)

    monkeypatch.setattr(service._sender, "send_image", send)
    model.responses = [
        call("get_sticker_image", {"stickerId": entry["id"]}),
        call("send_sticker", {"stickerId": entry["id"]}),
    ]
    service._native_lock.acquire()
    try:
        service.enable(ACCOUNT, True)
        receiver.receive(ACCOUNT, packet())
        assert entered.wait(2)
        store.delete(ACCOUNT, entry["id"])
    finally:
        service._native_lock.release()
    wait(lambda: service.status()["active"] == 0)
    assert not connection.calls and not sessions.list(ACCOUNT)[0]["sent"]


def test_unknown_sticker_receipt_is_not_retried(library):
    service, receiver, sessions, _, _, connection, model, store = library
    entry = store.add(ACCOUNT, prepare_image(raster()))
    connection.error = EngineError("TIMEOUT", "unknown")
    model.responses = [
        call("get_sticker_image", {"stickerId": entry["id"]}),
        call("send_sticker", {"stickerId": entry["id"]}),
    ]
    item = completed(service, receiver, sessions)
    assert (
        item["status"] == "error"
        and len(connection.calls) == 1
        and store.list(ACCOUNT)[0]["uses"] == 0
        and not item["sent"]
    )


def bridge_for(tmp_path, library):
    service, _, _, settings, messages, connection, _, store = library

    class Selection:
        def read(self):
            return ACCOUNT

    status = connection.status
    connection.status = lambda: {**status(), "state": "ready"}
    return DesktopBridge(
        DesktopPaths(tmp_path, tmp_path),
        lambda **_: None,
        connection=connection,
        selection=Selection(),
        messages=messages,
        settings=settings,
        agent=service,
        stickers=store,
    )


def test_manual_collection_works_with_auto_reply_off_and_never_calls_model(
    tmp_path, library, monkeypatch
):
    service, _, _, settings, messages, connection, model, store = library
    install_download(monkeypatch, connection)
    messages.ingest(ACCOUNT, image_packet())
    bridge = bridge_for(tmp_path, library)
    settings.save(
        ACCOUNT, {"api": {"vision": False}, "sticker": {"enabled": False, "collectEnabled": False}}
    )
    result = bridge.collect_sticker(KEY, "1", ACCOUNT)
    assert (
        result["ok"]
        and result["item"]["collected"]
        and not service.status()["enabled"]
        and not model.calls
    )
    assert bridge.get_stickers("", ACCOUNT)["items"][0]["id"] == result["item"]["id"]
    assert bridge.get_sticker_preview(result["item"]["id"], ACCOUNT)["image"].startswith(
        "data:image/jpeg;base64,"
    )
    assert not bridge.get_stickers("", OTHER)["ok"]
    assert not bridge.delete_sticker(result["item"]["id"], OTHER)["ok"]


@pytest.mark.parametrize("change", ["recall", "switch"])
def test_manual_collection_rechecks_source_and_identity_after_download(
    tmp_path, library, monkeypatch, change
):
    _, _, _, _, messages, connection, _, store = library
    install_download(monkeypatch, connection)
    messages.ingest(ACCOUNT, image_packet())
    bridge = bridge_for(tmp_path, library)

    async def download(self, url, permit):
        if change == "recall":
            messages.recall(ACCOUNT, KEY, "1")
        else:
            connection.account = OTHER
        return raster()

    monkeypatch.setattr(ImageDownloader, "fetch", download)
    assert not bridge.collect_sticker(KEY, "1", ACCOUNT)["ok"] and not store.list(ACCOUNT)


def test_sticker_blob_survives_restart(tmp_path):
    initial = AccountStorage(tmp_path / "accounts")
    entry = initial.stickers.add(ACCOUNT, prepare_image(raster()), "persistent")
    initial.close()
    accounts = AccountStorage(tmp_path / "accounts")
    try:
        assert accounts.stickers.get(ACCOUNT, entry["id"])["meta"]["note"] == "persistent"
        assert not accounts.stickers.list(OTHER)
    finally:
        accounts.close()


def test_poke_default_off_and_private_target_is_current_peer(library):
    service, receiver, sessions, settings, _, connection, model, _ = library
    model.responses = [call("send_poke", {}), result("finish")]
    item = completed(service, receiver, sessions)
    assert not connection.calls and not item["sent"]
    service.pause()
    wait(lambda: service.status()["active"] == 0)
    settings.save(ACCOUNT, {"sticker": {"allowPoke": True}})
    model.responses = [call("send_poke", {}), result("finish")]
    model.calls.clear()
    receiver.receive(ACCOUNT, packet(2))
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet(3))
    wait(
        lambda: (
            len(sessions.list(ACCOUNT)) == 2 and sessions.list(ACCOUNT)[0]["status"] != "running"
        )
    )
    assert connection.calls == [("send_poke", {"user_id": PEER})]
    newest = sessions.list(ACCOUNT)[0]
    assert (
        newest["status"] == "done"
        and newest["sent"][0]["type"] == "poke"
        and newest["sent"][0]["messageId"] is None
    )


@pytest.mark.parametrize("target", [None, "99999999"])
def test_group_poke_rejects_unknown_or_missing_member(library, target):
    service, receiver, sessions, settings, _, connection, model, _ = library
    settings.save(ACCOUNT, {"sticker": {"allowPoke": True}, "groupTrigger": "all"})
    model.responses = [
        call("send_poke", {} if target is None else {"targetUserId": target}),
        result("finish"),
    ]
    item = completed(service, receiver, sessions, packet(kind="group"))
    assert not connection.calls and not item["sent"]


def test_group_poke_routes_known_member_and_limits_one_per_run(library):
    service, receiver, sessions, settings, _, connection, model, _ = library
    settings.save(ACCOUNT, {"sticker": {"allowPoke": True}, "groupTrigger": "all"})
    first = call("send_poke", {"targetUserId": PEER}, "poke-one")
    first["message"]["tool_calls"] += call("send_poke", {"targetUserId": PEER}, "poke-two")[
        "message"
    ]["tool_calls"]
    model.responses = [first, result("finish")]
    item = completed(service, receiver, sessions, packet(kind="group"))
    assert connection.calls == [("send_poke", {"user_id": PEER, "group_id": "99887766"})]
    assert len(item["sent"]) == 1 and any(
        r.get("name") == "send_poke" and r["isError"] for r in item["records"]
    )


def test_poke_unknown_receipt_stops_without_retry(library):
    service, receiver, sessions, settings, _, connection, model, _ = library
    settings.save(ACCOUNT, {"sticker": {"allowPoke": True}})
    connection.error = EngineError("TIMEOUT", "unknown")
    model.responses = [call("send_poke", {})]
    item = completed(service, receiver, sessions)
    assert item["status"] == "error" and not item["sent"] and len(connection.calls) == 1


def test_poke_rechecks_switch_while_waiting_for_queue(library, monkeypatch):
    service, receiver, sessions, settings, _, connection, model, _ = library
    settings.save(ACCOUNT, {"sticker": {"allowPoke": True}})
    entered = threading.Event()
    original = service._sender.poke

    def poke(*args):
        entered.set()
        return original(*args)

    monkeypatch.setattr(service._sender, "poke", poke)
    service._native_lock.acquire()
    try:
        model.responses = [call("send_poke", {})]
        service.enable(ACCOUNT, True)
        receiver.receive(ACCOUNT, packet())
        assert entered.wait(2)
        settings.save(ACCOUNT, {"sticker": {"allowPoke": False}})
    finally:
        service._native_lock.release()
    wait(lambda: service.status()["active"] == 0)
    assert not connection.calls
