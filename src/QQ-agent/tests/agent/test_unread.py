import time

import pytest
from qqbot.desktop.bridge import DesktopBridge
from qqbot.desktop.paths import DesktopPaths
from qqbot.storage.accounts import AccountStorage
from qqbot.storage.database import Database
from qqbot.storage.messages import MessageStore
from test_agent import packet, result, wait
from test_agent import stack as stack
from test_storage import ACCOUNT, OTHER, PEER, event
from test_storage import stores as stores

KEY = f"private:{PEER}"
GROUP = "group:99887766"


def test_only_admitted_incoming_rows_are_unread_and_reads_have_no_side_effect(stores):
    _, messages, _ = stores
    messages.ingest(ACCOUNT, event())
    messages.ingest(ACCOUNT, event())
    messages.ingest(
        ACCOUNT, event(message_id=2, post_type="message_sent", user_id=ACCOUNT, target_id=PEER)
    )
    snapshot = messages.archive_state(ACCOUNT)
    assert (
        snapshot["unread"] == 1
        and snapshot["unreadChats"] == 1
        and snapshot["items"][0]["unread"] == 1
    )
    assert snapshot["items"][0]["count"] == 2
    assert messages.messages(ACCOUNT, KEY)["items"][0]["read"] is False
    assert messages.messages(ACCOUNT, KEY)["items"][1]["read"] is True
    messages.messages(ACCOUNT, KEY, query="你好")
    messages.context(ACCOUNT, KEY)
    assert messages.archive_state(ACCOUNT) == snapshot


def test_mark_current_uses_snapshot_boundary_and_other_chats_accounts_remain_unread(stores):
    _, messages, _ = stores
    messages.ingest(ACCOUNT, event(message_id=1))
    messages.ingest(ACCOUNT, event(message_id=2, message_type="group", group_id=99887766))
    messages.ingest(OTHER, event(OTHER, message_id=3))
    through = next(c for c in messages.list_chats(ACCOUNT) if c["chatKey"] == KEY)["lastId"]
    messages.ingest(ACCOUNT, event(message_id=4))
    assert messages.mark_read(ACCOUNT, KEY, through) == 1
    assert messages.mark_read(ACCOUNT, KEY, through) == 0
    assert {c["chatKey"]: c["unread"] for c in messages.list_chats(ACCOUNT)} == {KEY: 1, GROUP: 1}
    assert messages.archive_state(OTHER)["unread"] == 1
    assert [m["read"] for m in messages.messages(ACCOUNT, KEY)["items"]] == [True, False]


def test_mark_all_uses_full_account_snapshot_not_search_or_list_limit(stores):
    _, messages, _ = stores
    for i in range(502):
        messages.ingest(ACCOUNT, event(message_id=i + 1, user_id=str(10000 + i)))
    before = messages.archive_state(ACCOUNT)
    assert before["unread"] == 502 and len(before["items"]) == 500
    messages.ingest(ACCOUNT, event(message_id=1000))
    assert messages.mark_read(ACCOUNT, None, before["readThrough"]) == 502
    assert messages.archive_state(ACCOUNT)["unread"] == 1
    assert messages.archive_state(ACCOUNT)["items"][0]["chatKey"] == KEY


def test_unread_filter_queries_before_list_limit_and_never_marks_on_view(stores):
    _, messages, _ = stores
    messages.ingest(ACCOUNT, event(message_id=1))
    for i in range(502):
        messages.ingest(
            ACCOUNT,
            event(
                message_id=i + 2,
                user_id=str(10000 + i),
                post_type="message_sent",
                target_id=str(10000 + i),
            ),
        )
    assert KEY not in {c["chatKey"] for c in messages.archive_state(ACCOUNT)["items"]}
    filtered = messages.archive_state(ACCOUNT, unread_only=True)
    assert (
        len(filtered["items"]) == 1
        and filtered["items"][0]["chatKey"] == KEY
        and filtered["unread"] == 1
    )
    with pytest.raises(ValueError):
        messages.archive_state(ACCOUNT, unread_only="true")


def test_recall_delete_and_late_echo_never_leave_phantom_unread(stores):
    _, messages, _ = stores
    messages.ingest(ACCOUNT, event())
    messages.recall(ACCOUNT, KEY, -123)
    messages.ingest(ACCOUNT, event(message_seq=8))
    assert messages.archive_state(ACCOUNT)["unread"] == 0
    assert all(m["read"] for m in messages.messages(ACCOUNT, KEY)["items"])
    messages.ingest(ACCOUNT, event(message_id=2))
    messages.mark_read(ACCOUNT, KEY, messages.archive_state(ACCOUNT)["readThrough"])
    assert messages.ingest(ACCOUNT, event(message_id=2)) is None
    assert messages.archive_state(ACCOUNT)["unread"] == 0
    messages.ingest(ACCOUNT, event(message_id=3))
    messages.delete(ACCOUNT, KEY)
    assert messages.archive_state(ACCOUNT) == {
        "items": [],
        "unread": 0,
        "unreadChats": 0,
        "readThrough": 0,
    }


@pytest.mark.parametrize("through", [None, True, -1, 1.5, "1", 2**63])
def test_invalid_read_boundaries_do_not_mutate(stores, through):
    _, messages, _ = stores
    messages.ingest(ACCOUNT, event())
    with pytest.raises(ValueError):
        messages.mark_read(ACCOUNT, KEY, through)
    assert messages.archive_state(ACCOUNT)["unread"] == 1


def test_batch_claim_is_atomic_scoped_and_manual_run_can_use_read_messages(stores):
    _, messages, _ = stores
    first = messages.ingest(ACCOUNT, event(message_id=1))["id"]
    second = messages.ingest(ACCOUNT, event(message_id=2))["id"]
    group = messages.ingest(ACCOUNT, event(message_id=3, message_type="group", group_id=99887766))[
        "id"
    ]
    messages.mark_read(ACCOUNT, KEY, first)
    assert messages.claim(ACCOUNT, KEY, [first, second, group]) == {second}
    assert messages.claim(ACCOUNT, KEY, [first, second]) == set()
    assert messages.claim(ACCOUNT, KEY, [first], only_unread=False) == {first}
    assert messages.archive_state(ACCOUNT)["unread"] == 1


def test_unread_persists_through_account_directory_proxy_and_reopen(tmp_path):
    root = tmp_path / "accounts"
    store = AccountStorage(root)
    for account in [ACCOUNT, OTHER]:
        store.messages.ingest(account, event(account))
    through = store.messages.archive_state(ACCOUNT)["readThrough"]
    assert store.messages.mark_read(ACCOUNT, KEY, through) == 1
    store.close()
    reopened = AccountStorage(root)
    try:
        assert reopened.messages.archive_state(ACCOUNT)["unread"] == 0
        assert reopened.messages.archive_state(OTHER)["unread"] == 1
    finally:
        reopened.close()


def version5(file):
    database = Database(file)
    messages = MessageStore(database)
    messages.ingest(ACCOUNT, event())
    database.connection.execute("DROP INDEX messages_unread")
    database.connection.execute("ALTER TABLE messages DROP COLUMN is_read")
    database.connection.execute("PRAGMA user_version=5")
    database.connection.commit()
    database.close()


def test_schema_upgrade_keeps_old_archive_read_without_changing_body(tmp_path):
    file = tmp_path / "old.sqlite3"
    version5(file)
    db = Database(file)
    try:
        messages = MessageStore(db)
        assert messages.archive_state(ACCOUNT)["unread"] == 0
        assert messages.messages(ACCOUNT, KEY)["items"][0]["text"] == "你好"
        messages.ingest(ACCOUNT, event(message_id=2))
        assert messages.archive_state(ACCOUNT)["unread"] == 1
    finally:
        db.close()


def test_account_database_upgrades_old_receipts(tmp_path):
    target = tmp_path / "accounts" / ACCOUNT / "agent.sqlite3"
    target.parent.mkdir(parents=True)
    version5(target)
    store = AccountStorage(tmp_path / "accounts")
    try:
        assert (
            store.messages.archive_state(ACCOUNT)["unread"] == 0
            and store.messages.list_chats(ACCOUNT)[0]["count"] == 1
        )
    finally:
        store.close()


def test_bridge_rejects_stale_offline_and_invalid_scope_without_model_or_qq(tmp_path):
    class Selection:
        value = ACCOUNT

        def read(self):
            return self.value

    selection = Selection()

    class Connection:
        connected = True

        def status(self):
            return {
                "state": "ready" if self.connected else "idle",
                "connected": self.connected,
                "account": {"uin": selection.value},
            }

        def invoke(self, *args, **kwargs):
            raise AssertionError("Mark-read must never invoke QQ")

    connection = Connection()
    store = AccountStorage(tmp_path / "accounts")
    bridge = DesktopBridge(
        DesktopPaths(tmp_path, tmp_path),
        lambda **_: None,
        selection=selection,
        connection=connection,
        messages=store.messages,
    )
    try:
        store.messages.ingest(ACCOUNT, event())
        snapshot = bridge.get_archives()
        assert snapshot["ok"] and snapshot["unread"] == 1
        assert not bridge.mark_archive_read(KEY, snapshot["readThrough"], OTHER)["ok"]
        assert not bridge.mark_archive_read("invalid", snapshot["readThrough"], ACCOUNT)["ok"]
        connection.connected = False
        assert bridge.get_archives()["unread"] == 0
        assert not bridge.mark_archive_read(KEY, snapshot["readThrough"], ACCOUNT)["ok"]
        connection.connected = True
        assert bridge.mark_archive_read(KEY, snapshot["readThrough"], ACCOUNT)["marked"] == 1
        assert store.messages.messages(ACCOUNT, KEY)["items"][0]["text"] == "你好"
    finally:
        bridge._reviews.close()
        store.close()


def test_off_keeps_unread_enable_does_not_replay_and_manual_process_consumes_only_latest(stack):
    service, receiver, sessions, _, messages, connection, model = stack
    receiver.receive(ACCOUNT, packet(1))
    receiver.receive(ACCOUNT, packet(2))
    assert messages.archive_state(ACCOUNT)["unread"] == 2
    service.enable(ACCOUNT, True)
    time.sleep(0.06)
    assert not model.calls and messages.archive_state(ACCOUNT)["unread"] == 2
    service.pause()
    service.process_once(ACCOUNT, KEY)
    wait(lambda: service.status()["active"] == 0)
    assert len(model.calls) == 1 and messages.archive_state(ACCOUNT)["unread"] == 1
    assert messages.messages(ACCOUNT, KEY)["items"][0]["read"] is False


def test_trigger_miss_is_read_without_model_and_does_not_clear_older_backlog(stack):
    service, receiver, _, settings, messages, _, model = stack
    receiver.receive(ACCOUNT, packet(1, kind="group"))
    settings.save(ACCOUNT, {"groupTrigger": "at"})
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet(2, kind="group"))
    time.sleep(0.05)
    assert not model.calls and messages.archive_state(ACCOUNT)["unread"] == 1
    assert [m["read"] for m in messages.messages(ACCOUNT, GROUP)["items"]] == [False, True]


def test_marking_queued_batch_prevents_model_but_not_future_messages(stack):
    service, receiver, sessions, _, messages, _, model = stack
    service._debounce = 0.15
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet(1))
    messages.mark_read(ACCOUNT, KEY, messages.archive_state(ACCOUNT)["readThrough"])
    time.sleep(0.22)
    assert not model.calls and not sessions.list(ACCOUNT)
    receiver.receive(ACCOUNT, packet(2))
    wait(lambda: len(model.calls) == 1 and service.status()["active"] == 0)
    assert messages.archive_state(ACCOUNT)["unread"] == 0


def test_model_error_remains_read_and_manual_rerun_is_explicit(stack):
    service, receiver, sessions, _, messages, _, model = stack

    async def fail(*args):
        raise RuntimeError("fixture failure")

    model.complete = fail
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet(1))
    wait(lambda: sessions.list(ACCOUNT) and service.status()["active"] == 0)
    assert sessions.list(ACCOUNT)[0]["status"] == "error"
    assert messages.archive_state(ACCOUNT)["unread"] == 0


def test_new_arrival_during_model_run_remains_unread_when_automatic_is_off(stack):
    service, receiver, sessions, _, messages, _, model = stack
    import asyncio
    import threading

    started = threading.Event()
    release = threading.Event()

    async def complete(*args):
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return result("finish")

    model.complete = complete
    receiver.receive(ACCOUNT, packet(1))
    service.process_once(ACCOUNT, KEY)
    assert started.wait(2)
    receiver.receive(ACCOUNT, packet(2))
    assert [m["read"] for m in messages.messages(ACCOUNT, KEY)["items"]] == [True, False]
    release.set()
    wait(lambda: service.status()["active"] == 0)
    assert messages.archive_state(ACCOUNT)["unread"] == 1
