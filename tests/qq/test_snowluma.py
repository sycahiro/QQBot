"""SnowLuma 发现映射的回归测试；不启动真实服务。"""

from unittest.mock import Mock

import pytest

from QQBot.qq.engine import EngineError
from QQBot.qq.snowluma import SnowLumaDiscovery, SnowLumaEngine


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
