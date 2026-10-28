import json
import sqlite3
from types import SimpleNamespace

import pytest
from qqbot.agent.config import GLOBAL_FIELDS
from qqbot.agent.global_settings import GlobalSettings
from qqbot.desktop.bridge import DesktopBridge
from qqbot.desktop.paths import DesktopPaths
from qqbot.storage.accounts import AccountStorage

A, B = "12345678", "87654321"


def test_global_model_keys_and_search_shared_accounts_but_persona_and_lists_stay_local(tmp_path):
    global_settings = GlobalSettings(tmp_path)
    global_settings.profile(
        "global",
        "save",
        {
            "id": None,
            "name": "共享模型",
            "api": {"baseUrl": "https://model.test/v1", "apiKey": "global-secret", "model": "test"},
        },
    )
    global_settings.save("global", {"webSearch": {"enabled": True}})
    storage = AccountStorage(tmp_path / "accounts", global_settings=global_settings)
    try:
        storage.settings.save(
            A, {"persona": {"roleText": "角色A"}, "allow": {"private": ["11111"]}}
        )
        storage.settings.save(B, {"persona": {"roleText": "角色B"}})
        for account in [A, B]:
            config = storage.settings.read(account)
            assert config["api"]["apiKey"] == "global-secret" and config["webSearch"]["enabled"]
            with sqlite3.connect(tmp_path / "accounts" / account / "agent.sqlite3") as db:
                raw = json.loads(db.execute("SELECT value FROM settings").fetchone()[0])
            assert not set(raw) & GLOBAL_FIELDS
            with pytest.raises(ValueError):
                storage.settings.save(account, {"api": {"model": "account-override"}})
            with pytest.raises(ValueError):
                storage.settings.profile(account, "save", {})
        assert storage.settings.read(A)["persona"]["roleText"] == "角色A"
        assert storage.settings.read(B)["persona"]["roleText"] == "角色B"
        assert not storage.settings.read(B)["allow"]["private"]
        public = global_settings.read(public=True)
        assert public["api"]["apiKeyConfigured"] and "global-secret" not in json.dumps(public)
        assert "search-secret" not in json.dumps(public)
        global_settings.profile(
            "global",
            "save",
            {"id": public["activeProfileId"], "name": "修改共享模型", "api": {"model": "updated"}},
        )
        assert (
            storage.settings.read(A)["api"]["model"]
            == storage.settings.read(B)["api"]["model"]
            == "updated"
        )
    finally:
        storage.close()
    assert GlobalSettings(tmp_path).read()["api"]["model"] == "updated"


def test_global_checks_and_profile_edits_work_without_a_connected_account(tmp_path):
    shared = GlobalSettings(tmp_path)
    calls = []
    bridge = DesktopBridge(
        DesktopPaths(tmp_path, tmp_path),
        lambda **_: None,
        global_settings=shared,
        agent=SimpleNamespace(pause=lambda reason: calls.append(reason)),
    )

    class Checks:
        async def list_models(self, api):
            assert api["apiKey"] == "secret"
            return ["test"]

        async def test(self, api):
            assert api["apiKey"] == "secret"
            return {"model": "test", "tokens": 1, "latencyMs": 1, "reply": "pong"}

    bridge._models = Checks()
    try:
        assert bridge.get_global_settings()["scope"] == "global"
        result = bridge.manage_model_profile(
            "save",
            {
                "id": None,
                "name": "全局",
                "api": {"baseUrl": "https://model.test/v1", "apiKey": "secret", "model": "test"},
            },
            None,
        )
        assert result["ok"] and result["scope"] == "global" and calls
        assert bridge.get_model_list(None)["models"] == ["test"]
        assert bridge.test_model_connection(None)["reply"] == "pong"
        assert not bridge.save_global_settings({"persona": {"roleText": "not-global"}})["ok"]
        assert not bridge.get_bot_settings()["config"]
        assert not (tmp_path / "accounts").exists()
        assert "secret" not in json.dumps(bridge.get_global_settings())
    finally:
        bridge._reviews.close()
        bridge._debug_files.close()


def test_invalid_global_write_is_atomic_and_host_change_cannot_borrow_a_key(tmp_path):
    shared = GlobalSettings(tmp_path)
    config = shared.profile(
        "global",
        "save",
        {
            "id": None,
            "name": "模型",
            "api": {"baseUrl": "https://a.test/v1", "apiKey": "secret", "model": "test"},
        },
    )
    previous = (tmp_path / "global-settings.json").read_bytes()
    with pytest.raises(ValueError):
        shared.profile(
            "global",
            "save",
            {
                "id": config["activeProfileId"],
                "name": "模型",
                "api": {"baseUrl": "https://b.test/v1"},
            },
        )
    with pytest.raises(ValueError):
        shared.save("global", {"api": {"maxRounds": 0}})
    assert (tmp_path / "global-settings.json").read_bytes() == previous
    with pytest.raises(ValueError):
        shared.save(A, {"api": {}})


def test_media_save_updates_only_active_profile_and_rejects_stale_profile(tmp_path):
    shared = GlobalSettings(tmp_path)
    bridge = DesktopBridge(
        DesktopPaths(tmp_path, tmp_path), lambda **_: None, global_settings=shared
    )
    try:
        config = shared.profile(
            "global",
            "save",
            {
                "id": None,
                "name": "主模型",
                "api": {"baseUrl": "https://a.test/v1", "apiKey": "secret", "model": "chat"},
            },
        )
        active = config["activeProfileId"]
        result = bridge.save_global_settings(
            {"media": {"vision": True, "visionModel": "eyes"}, "profileId": active}
        )
        assert result["ok"] and result["scope"] == "global"
        config = shared.read()
        assert config["api"] == config["profiles"][0]["api"]
        assert (
            config["api"]["model"] == "chat"
            and config["api"]["apiKey"] == "secret"
            and config["api"]["visionModel"] == "eyes"
        )
        shared.profile(
            "global", "save", {"id": active, "name": "主模型", "api": {"model": "new-chat"}}
        )
        assert shared.read()["api"]["visionModel"] == "eyes"
        shared.profile(
            "global", "save", {"id": None, "name": "第二个模型", "api": {"model": "second"}}
        )
        previous = (tmp_path / "global-settings.json").read_bytes()
        for patch in [
            {"media": {"vision": False}, "profileId": active},
            {"media": {"apiKey": "other"}, "profileId": shared.read()["activeProfileId"]},
            {"media": {"video": False}, "profileId": shared.read()["activeProfileId"]},
        ]:
            assert not bridge.save_global_settings(patch)["ok"]
            assert (tmp_path / "global-settings.json").read_bytes() == previous
        assert not (tmp_path / "accounts").exists()
    finally:
        bridge._reviews.close()
        bridge._debug_files.close()
