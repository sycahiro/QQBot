import queue
import threading
from pathlib import Path

import pytest

from QQBot.desktop.paths import DesktopPaths
from QQBot.qq.connection import QqConnection
from QQBot.qq.engine import EngineError

TARGET = {"pid": 123, "processKey": "123:456789", "uin": "12345678"}


class Selection:
    def read(self):
        return TARGET["uin"]

    def choose(self, *_):
        raise AssertionError("Active account must not be changed")


class Discovery:
    def list_processes(self):
        return [
            dict(
                TARGET,
                identityReady=True,
                account={"uin": TARGET["uin"], "nickname": "测试"},
                version="9.9",
            )
        ]


class Client:
    def __init__(self, *_):
        self.calls = []
        self.events = queue.Queue()
        self.closed = threading.Event()
        self.login_uin = TARGET["uin"]

    def start(self):
        pass

    def request(self, method, params=None, **_):
        self.calls.append((method, params))
        if self.closed.is_set():
            raise EngineError("CLOSED", "Closed")
        if method == "account.attach":
            return {"ready": True, "database": {"status": "ready"}}
        if method == "account.detach":
            return {"ready": False}
        return {"status": "ok", "data": {"user_id": self.login_uin}}

    def next_event(self, timeout):
        return self.events.get(timeout=timeout)

    def close(self):
        self.closed.set()


def service(tmp_path, client=None, **options):
    child = client or Client()
    return QqConnection(
        DesktopPaths(Path(__file__).resolve().parents[2], tmp_path),
        Discovery(),
        Selection(),
        engine_factory=lambda _: child,
        **options,
    ), child


def test_explicit_connection_confirms_identity_and_prevents_selection_change(tmp_path):
    connection, child = service(tmp_path)
    try:
        assert connection.status()["connected"] is False and child.calls == []
        assert connection.connect(TARGET)["connected"] is True
        assert child.calls[1][1]["action"] == "get_login_info"
        with pytest.raises(EngineError) as active:
            connection.choose(None)
        assert active.value.code == "ACCOUNT_ACTIVE"
        assert connection.disconnect()["state"] == "idle"
        assert child.closed.is_set()
        assert any(method == "account.detach" for method, _ in child.calls)
    finally:
        connection.close()


def test_stale_process_is_rejected_before_starting_engine(tmp_path):
    connection, child = service(tmp_path)
    try:
        with pytest.raises(EngineError) as stale:
            connection.connect(TARGET | {"processKey": "123:999"})
        assert stale.value.code == "STALE_PROCESS" and child.calls == []
    finally:
        connection.close()


def test_wrong_live_identity_is_released_and_never_marked_connected(tmp_path):
    client = Client()
    client.login_uin = "87654321"
    changes = []
    connection, _ = service(tmp_path, client, on_status=changes.append)
    try:
        with pytest.raises(EngineError) as mismatch:
            connection.connect(TARGET)
        assert mismatch.value.code == "IDENTITY_MISMATCH"
        assert not any(item["connected"] for item in changes)
        assert connection.status()["connected"] is False and client.closed.is_set()
    finally:
        connection.close()


def test_events_from_other_accounts_are_not_forwarded_and_disconnect_revokes_actions(tmp_path):
    accepted, received = [], threading.Event()

    def on_event(uin, event):
        accepted.append((uin, event))
        received.set()

    connection, child = service(tmp_path, on_event=on_event)
    try:
        connection.connect(TARGET)
        for uin in ["87654321", TARGET["uin"]]:
            child.events.put(
                {"event": "qq.event", "data": {"accountUin": uin, "event": {"self_id": uin}}}
            )
        assert received.wait(2)
        assert len(accepted) == 1 and accepted[0][0] == TARGET["uin"]
        child.events.put(
            {"event": "engine.state", "data": {"ready": False, "selected": dict(TARGET)}}
        )
        # The callback above forms an ordering barrier; wait for the state event.
        for _ in range(50):
            if not connection.status()["connected"]:
                break
            threading.Event().wait(0.01)
        assert connection.status()["connected"] is False
        with pytest.raises(EngineError) as offline:
            connection.invoke("get_login_info")
        assert offline.value.code == "NOT_CONNECTED"
    finally:
        connection.close()


def test_close_during_attach_cannot_recreate_connected_state(tmp_path):
    entered = threading.Event()

    class SlowClient(Client):
        def request(self, method, params=None, **options):
            if method == "account.attach":
                entered.set()
                assert self.closed.wait(3)
            return super().request(method, params, **options)

    client = SlowClient()
    changes, failures = [], []
    connection, _ = service(tmp_path, client, on_status=changes.append)

    def connect():
        try:
            connection.connect(TARGET)
        except EngineError as error:
            failures.append(error.code)

    worker = threading.Thread(target=connect)
    worker.start()
    assert entered.wait(2)
    connection.close()
    worker.join(timeout=3)
    assert not worker.is_alive() and failures == ["CLOSED"]
    assert connection.status()["state"] == "closed"
    assert not any(item["connected"] for item in changes)


@pytest.mark.parametrize("state", ["error", "disconnected"])
def test_failed_session_is_released_before_new_selection(tmp_path, state):
    connection, client = service(tmp_path)
    calls = []

    def choose(target, discovery):
        assert client.closed.is_set() and connection._client is None
        calls.append(target)

    connection._selection = type("Selection", (), {"choose": staticmethod(choose)})()
    connection._client = client
    connection._status.update(state=state, connected=False)
    assert connection.choose(None) is None and calls == [None]
    assert connection.status()["state"] == "idle"
    connection.close()


def test_failed_session_cleanup_failure_never_changes_saved_selection(tmp_path):
    connection, client = service(tmp_path)
    client.close = lambda: (_ for _ in ()).throw(OSError("owned pipe busy"))
    connection._client = client
    connection._status.update(state="error", connected=False)
    with pytest.raises(EngineError) as error:
        connection.choose(None)
    assert error.value.code == "RELEASE_FAILED" and connection._selection.read() == TARGET["uin"]
    assert connection._client is client
    client.close = lambda: None
    connection.close()
