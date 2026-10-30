from pathlib import Path

from QQBot.agent.global_settings import GlobalSettings
from QQBot.desktop.bridge import DesktopBridge
from QQBot.desktop.paths import DesktopPaths


def test_reply_switch_acknowledgements_include_the_same_model_as_status_polling(tmp_path):
    account = "12345678"
    settings = GlobalSettings(tmp_path)
    settings.save(
        "global", {"api": {"baseUrl": "https://model.test/v1", "model": "configured-model"}}
    )

    class Selection:
        def read(self):
            return account

    class Connection:
        def status(self):
            return {"state": "ready", "connected": True, "account": {"uin": account}}

    class Agent:
        enabled = False

        def status(self):
            return {
                "enabled": self.enabled,
                "account": account,
                "active": 0,
                "running": 0,
                "queued": 0,
                "error": None,
            }

        def enable(self, selected, enabled):
            assert selected == account
            self.enabled = enabled
            return self.status()

    bridge = DesktopBridge(
        DesktopPaths(Path(__file__).resolve().parents[2], tmp_path),
        lambda **_: None,
        selection=Selection(),
        connection=Connection(),
        agent=Agent(),
        global_settings=settings,
    )
    for enabled in (True, False, True):
        acknowledged = bridge.set_auto_reply(enabled, account)
        assert acknowledged["ok"] and acknowledged["status"]["enabled"] is enabled
        assert acknowledged["status"]["model"] == "configured-model"
        assert acknowledged["status"] == bridge.get_agent_status()
