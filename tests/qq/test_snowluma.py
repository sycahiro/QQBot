"""SnowLuma 发现映射的回归测试；不启动真实服务。"""

import struct
from unittest.mock import Mock

import pytest

from QQBot.qq.engine import EngineError
from QQBot.qq.snowluma import SnowLumaDiscovery, SnowLumaEngine, _WebSocket


class StubService:
    def __init__(self, items):
        self.running = True
        self._items = items

    def processes(self):
        return self._items


def test_list_processes_prefers_account_identity_over_injection_placeholder(
    tmp_path, monkeypatch
):
    # 未接管时顶层 uin 是占位 "0"，登录身份在 account 里；不能让 "0" 短路真实账号。
    discovery = SnowLumaDiscovery(tmp_path)
    monkeypatch.setattr(
        discovery,
        "_service",
        StubService(
            [
                {
                    "pid": 12416,
                    "uin": "0",
                    "loggedIn": False,
                    "connected": False,
                    "account": {"uin": "1234567890", "nickname": "示例用户"},
                },
                {
                    "pid": 3936,
                    "uin": "0",
                    "account": {"uin": "", "nickname": ""},
                },
            ]
        ),
    )
    monkeypatch.setattr("QQBot.qq.snowluma._read_versions", lambda pids: {})
    items = discovery.list_processes()
    assert [item["account"]["uin"] for item in items] == ["1234567890", ""]
    assert [item["identityReady"] for item in items] == [True, False]
    assert items[0]["processKey"] == "12416:1234567890"


def test_list_processes_keeps_injected_top_level_uin(tmp_path, monkeypatch):
    # 注入接管后顶层 uin 有真实值，此时以它为准。
    discovery = SnowLumaDiscovery(tmp_path)
    monkeypatch.setattr(
        discovery,
        "_service",
        StubService(
            [
                {
                    "pid": 8012,
                    "uin": "1234567890",
                    "loggedIn": True,
                    "connected": True,
                    "account": {"uin": "1234567890", "nickname": "示例用户"},
                }
            ]
        ),
    )
    monkeypatch.setattr("QQBot.qq.snowluma._read_versions", lambda pids: {})
    items = discovery.list_processes()
    assert items[0]["account"]["uin"] == "1234567890" and items[0]["identityReady"] is True


def test_onebot_connection_starts_after_attach_and_failure_unloads(tmp_path, monkeypatch):
    service = Mock(running=True, onebot_token="token")
    engine = SnowLumaEngine(tmp_path, service=service)

    def connect(*_args, **_kwargs):
        service.load.assert_called_once_with(12416, "1234567890", timeout=45)
        raise ConnectionRefusedError("not ready")

    monkeypatch.setattr("QQBot.qq.snowluma._WebSocket", connect)
    engine.start()
    with pytest.raises(EngineError, match="OneBot 连接失败"):
        engine.request("account.attach", {"pid": 12416, "uin": "1234567890"})
    engine.close()
    service.unload.assert_called_once_with(12416, timeout=40)


def test_close_during_snowluma_attach_unloads_after_load_finishes(tmp_path):
    service = Mock(running=True, onebot_token="token")
    engine = SnowLumaEngine(tmp_path, service=service)
    service.load.side_effect = lambda *_args, **_kwargs: engine.close()
    engine.start()
    with pytest.raises(EngineError, match="已经关闭"):
        engine.request("account.attach", {"pid": 12416, "uin": "1234567890"})
    service.unload.assert_called_once_with(12416, timeout=45)


def ws_frame(fin, opcode, payload=b""):
    first = (0x80 if fin else 0) | opcode
    length = len(payload)
    if length < 126:
        return bytes([first, length]) + payload
    return bytes([first, 126]) + struct.pack(">H", length) + payload


class FakeSocket:
    def __init__(self, data):
        self._data, self.sent = data, b""

    def settimeout(self, timeout):
        pass

    def recv(self, size):
        if not self._data:
            raise ConnectionError("closed")
        chunk, self._data = self._data[:size], self._data[size:]
        return chunk

    def sendall(self, data):
        self.sent += data


def make_ws(data):
    ws = object.__new__(_WebSocket)
    ws._socket = FakeSocket(data)
    ws._buffer = b""
    return ws


def test_recv_text_aggregates_fragmented_messages_per_rfc6455():
    # 起始帧 FIN=0 + 续帧 FIN=1 必须拼成一条消息，不把续帧当独立消息返回。
    ws = make_ws(
        ws_frame(False, 0x1, b'{"a"')
        + ws_frame(False, 0x0, b':')
        + ws_frame(True, 0x0, b'1}')
        + ws_frame(True, 0x1, "下一条".encode())
    )
    assert ws.recv_text() == '{"a":1}'
    assert ws.recv_text() == "下一条"


def test_recv_text_pong_between_fragments_keeps_aggregation():
    ws = make_ws(
        ws_frame(False, 0x1, b"part-")
        + ws_frame(True, 0x9, b"heartbeat")
        + ws_frame(True, 0x0, b"one")
    )
    assert ws.recv_text() == "part-one"
    sent = ws._socket.sent
    assert sent[:1] == b"\x8a" and len(sent) == 2 + 4 + 9  # pong：头+掩码+心跳载荷（载荷已按 RFC 掩码）


def test_recv_text_close_and_single_frame_unaffected():
    ws = make_ws(ws_frame(True, 0x1, "单帧".encode()) + ws_frame(True, 0x8))
    assert ws.recv_text() == "单帧"
    with pytest.raises(ConnectionError):
        ws.recv_text()


def test_onebot_action_whitelist_allows_business_actions_only(tmp_path, monkeypatch):
    service = Mock(running=True, onebot_token="token")
    engine = SnowLumaEngine(tmp_path, service=service)
    posted = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        posted["url"] = url
        return Mock(
            status_code=200, content=b"{}", json=lambda: {"status": "ok", "retcode": 0, "data": None}
        )

    monkeypatch.setattr("QQBot.qq.snowluma.httpx.post", fake_post)
    assert engine.request(
        "account.action", {"uin": "1234567890", "action": "get_msg", "params": {"message_id": 1}}
    )["status"] == "ok"
    assert posted["url"].endswith("/get_msg")
    with pytest.raises(EngineError, match="白名单"):
        engine.request(
            "account.action", {"uin": "1234567890", "action": "set_group_whole_ban", "params": {}}
        )
    assert "set_group_whole_ban" not in posted["url"]
