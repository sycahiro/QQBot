import asyncio
import copy
import json
import threading

import pytest
from qqbot.agent.memory_review import MemoryReviews
from qqbot.desktop.bridge import DesktopBridge
from qqbot.desktop.paths import DesktopPaths
from qqbot.storage.accounts import AccountStorage
from test_agent import ACCOUNT, OTHER, PEER, packet

KEY = f"private:{PEER}"


@pytest.fixture
def review(tmp_path):
    storage = AccountStorage(tmp_path / "accounts")
    storage.settings.save(
        ACCOUNT,
        {
            "api": {
                "baseUrl": "https://model.test/v1",
                "model": "fixture",
                "apiKey": "private-key",
            },
            "allow": {"private": [PEER], "groups": ["99887766"]},
        },
    )
    storage.memory.replace(ACCOUNT, KEY, PEER, "名字", ["喜欢猫", "喜欢可爱的猫"])
    storage.messages.ingest(ACCOUNT, packet(1))

    class Model:
        calls = []
        content = '{"memories":["喜欢猫"]}'

        async def complete(self, api, prompt, tools):
            self.calls.append((copy.deepcopy(prompt), tools))
            assert api["model"] == "fixture" and not tools
            return {
                "message": {"content": self.content},
                "model": "fixture",
                "usage": {"totalTokens": 12},
            }

    class Selection:
        value = ACCOUNT

        def read(self):
            return self.value

    selection = Selection()

    class Connection:
        def status(self):
            return {"state": "ready", "connected": True, "account": {"uin": selection.value}}

    bridge = DesktopBridge(
        DesktopPaths(tmp_path, tmp_path),
        lambda **_: None,
        selection=selection,
        connection=Connection(),
        memory=storage.memory,
        messages=storage.messages,
        settings=storage.settings,
    )
    model = Model()
    model.calls = []
    bridge._reviews = MemoryReviews(model=model)
    yield bridge, storage, selection, model
    bridge._reviews.close()
    storage.close()


def test_closed_review_does_no_snapshot_or_model_work(review, monkeypatch):
    bridge, storage, _, model = review
    bridge._reviews.close()

    def unexpected(*args):
        pytest.fail("Closed review must stop before reading memories")

    monkeypatch.setattr(storage.memory, "snapshot", unexpected)
    result = bridge.preview_memory(KEY, PEER, ACCOUNT)
    assert not result["ok"] and "已关闭" in result["error"]["message"] and not model.calls


def test_full_review_capacity_rejects_before_calling_model_and_keeps_existing_previews(review):
    import time

    bridge, _, _, model = review
    bridge._reviews._pending = {str(i): {"created": time.monotonic()} for i in range(16)}
    result = bridge.preview_memory(KEY, PEER, ACCOUNT)
    assert not result["ok"] and "预览过多" in result["error"]["message"]
    assert len(bridge._reviews._pending) == 16 and not model.calls


def test_preview_never_writes_and_explicit_edited_apply_is_single_use(review):
    bridge, store, _, model = review
    before = store.memory.snapshot(ACCOUNT, KEY, PEER)
    result = bridge.preview_memory(KEY, PEER, ACCOUNT)
    assert (
        result["ok"]
        and result["preview"]["before"] == before["values"]
        and result["preview"]["after"] == ["喜欢猫"]
    )
    assert store.memory.snapshot(ACCOUNT, KEY, PEER) == before and len(model.calls) == 1
    assert bridge.apply_memory_preview(
        KEY, PEER, result["preview"]["token"], ["喜欢猫咪"], ACCOUNT
    )["ok"]
    assert store.memory.snapshot(ACCOUNT, KEY, PEER)["values"] == ["喜欢猫咪"]
    assert not bridge.apply_memory_preview(KEY, PEER, result["preview"]["token"], [], ACCOUNT)["ok"]
    assert not model.calls[0][1] and "private-key" not in json.dumps(result)


@pytest.mark.parametrize("change", ["edit", "delete", "recall", "account", "blocked", "model"])
def test_preview_cannot_overwrite_changed_memories_sources_or_account(review, change):
    bridge, store, selection, _ = review
    preview = bridge.preview_memory(KEY, PEER, ACCOUNT)["preview"]
    if change == "edit":
        store.memory.append(ACCOUNT, KEY, PEER, "名字", "喜欢游戏")
    elif change == "delete":
        store.memory.delete(ACCOUNT, KEY, PEER)
    elif change == "recall":
        store.messages.recall(ACCOUNT, KEY, 1)
    elif change == "account":
        selection.value = OTHER
    elif change == "blocked":
        store.settings.save(ACCOUNT, {"blockedUsers": [PEER]})
    else:
        store.settings.save(ACCOUNT, {"api": {"model": "new"}})
    current = store.memory.snapshot(ACCOUNT, KEY, PEER)
    assert not bridge.apply_memory_preview(KEY, PEER, preview["token"], ["不该写入"], ACCOUNT)["ok"]
    assert store.memory.snapshot(ACCOUNT, KEY, PEER) == current


def test_preview_is_scoped_to_member_and_does_not_expose_other_chat_or_other_users(review):
    bridge, store, _, model = review
    key = "group:99887766"
    store.memory.replace(ACCOUNT, key, PEER, "群友", ["爱猫"])
    store.memory.replace(ACCOUNT, key, OTHER, "其他人", ["不应泄露的印象"])
    store.messages.ingest(
        ACCOUNT,
        packet(
            2,
            kind="group",
            user_id=OTHER,
            message=[{"type": "text", "data": {"text": "不应发送的别人的发言"}}],
        ),
    )
    preview = bridge.preview_memory(key, PEER, ACCOUNT)["preview"]
    sent = json.dumps(model.calls[-1], ensure_ascii=False)
    assert "不应" not in sent
    assert not bridge.apply_memory_preview(key, OTHER, preview["token"], ["覆盖"], ACCOUNT)["ok"]
    assert store.memory.snapshot(ACCOUNT, key, OTHER)["values"] == ["不应泄露的印象"]
    assert not bridge.preview_memory(KEY, OTHER, ACCOUNT)["ok"]


@pytest.mark.parametrize(
    "output",
    [
        "null",
        "[]",
        '{"memories":"bad"}',
        '```json\n{"memories":[]}\n```',
        '{"memories":["' + ("x" * 121) + '"]}',
        '{"memories":[],"userId":"wrong"}',
    ],
)
def test_bad_model_output_is_rejected_without_mutation(review, output):
    bridge, store, _, model = review
    model.content = output
    before = store.memory.snapshot(ACCOUNT, KEY, PEER)
    assert not bridge.preview_memory(KEY, PEER, ACCOUNT)["ok"]
    assert store.memory.snapshot(ACCOUNT, KEY, PEER) == before and len(model.calls) == 1


def test_preview_expiry_and_close_invalidate_application(review, monkeypatch):
    bridge, store, _, _ = review
    preview = bridge.preview_memory(KEY, PEER, ACCOUNT)["preview"]
    bridge._reviews._pending[preview["token"]]["created"] -= 601
    assert not bridge.apply_memory_preview(KEY, PEER, preview["token"], [], ACCOUNT)["ok"]
    preview = bridge.preview_memory(KEY, PEER, ACCOUNT)["preview"]
    bridge._reviews.close()
    assert not bridge.apply_memory_preview(KEY, PEER, preview["token"], [], ACCOUNT)["ok"]
    assert len(store.memory.snapshot(ACCOUNT, KEY, PEER)["values"]) == 2


def test_inflight_model_is_cancelled_on_source_change_and_duplicate_click_is_rejected(review):
    bridge, store, selection, _ = review
    entered, cancelled = threading.Event(), threading.Event()

    class Waiting:
        async def complete(self, *_):
            entered.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

    bridge._reviews = MemoryReviews(model=Waiting())
    responses = []
    thread = threading.Thread(
        target=lambda: responses.append(bridge.preview_memory(KEY, PEER, ACCOUNT))
    )
    thread.start()
    assert entered.wait(2)
    assert not bridge.preview_memory(KEY, PEER, ACCOUNT)["ok"]
    selection.value = OTHER
    thread.join(timeout=3)
    assert not thread.is_alive() and cancelled.is_set() and not responses[0]["ok"]
    assert store.memory.snapshot(ACCOUNT, KEY, PEER)["values"] == ["喜欢猫", "喜欢可爱的猫"]


def test_apply_compare_and_swap_keeps_other_members_and_records_unchanged(review):
    bridge, store, _, _ = review
    key = "group:99887766"
    store.memory.replace(ACCOUNT, key, PEER, "目标", ["爱猫"])
    store.memory.replace(ACCOUNT, key, OTHER, "其他成员", ["爱狗"])
    other = store.memory.snapshot(ACCOUNT, key, OTHER)
    preview = bridge.preview_memory(key, PEER, ACCOUNT)["preview"]
    assert bridge.apply_memory_preview(key, PEER, preview["token"], [], ACCOUNT)["ok"]
    assert not store.memory.snapshot(ACCOUNT, key, PEER)["values"]
    assert store.memory.snapshot(ACCOUNT, key, OTHER) == other
