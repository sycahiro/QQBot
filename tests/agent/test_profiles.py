import copy
import json

import httpx
import pytest

from QQBot.agent.config import DEFAULTS, SettingsStore
from QQBot.agent.models import ModelChecks
from QQBot.desktop.bridge import DesktopBridge
from QQBot.desktop.paths import DesktopPaths
from QQBot.storage.database import Database

ACCOUNT, OTHER = "12345678", "87654321"


@pytest.fixture
def store(tmp_path):
    db = Database(tmp_path / "profiles.sqlite3")
    settings = SettingsStore(db)
    settings.save(
        ACCOUNT,
        {"api": {"baseUrl": "https://first.test/v1", "model": "first", "apiKey": "first-key"}},
    )
    yield settings
    db.close()


def save(store, name, host, key):
    return store.profile(
        ACCOUNT,
        "save",
        {"name": name, "api": {"baseUrl": f"https://{host}/v1", "model": name, "apiKey": key}},
    )


def test_profiles_keep_separate_keys_manual_selection_and_write_only_public_data(store):
    first = save(store, "first", "first.test", "first-key")
    first_id = first["activeProfileId"]
    second = save(store, "second", "second.test", "second-key")
    second_id = second["activeProfileId"]
    assert first_id != second_id and len(second["profiles"]) == 2
    assert all(
        "apiKey" not in p["api"] and p["api"]["apiKeyConfigured"] for p in second["profiles"]
    )
    store.profile(ACCOUNT, "use", {"id": first_id})
    assert store.read(ACCOUNT)["api"]["apiKey"] == "first-key"
    store.profile(ACCOUNT, "save", {"id": first_id, "name": "renamed", "api": {"model": "updated"}})
    cfg = store.read(ACCOUNT)
    assert cfg["api"]["apiKey"] == "first-key" and cfg["api"]["model"] == "updated"
    assert next(p for p in cfg["profiles"] if p["id"] == second_id)["api"]["apiKey"] == "second-key"
    assert store.read(OTHER)["profiles"] == []


def test_legacy_current_config_can_be_saved_without_reentering_or_exposing_key(store):
    saved = store.profile(
        ACCOUNT, "save", {"id": "", "name": "当前配置", "api": {"model": "edited"}}
    )
    assert saved["activeProfileId"] and store.read(ACCOUNT)["api"]["apiKey"] == "first-key"
    assert saved["api"]["apiKeyConfigured"] and "apiKey" not in saved["profiles"][0]["api"]


def test_new_profiles_and_host_changes_never_borrow_a_saved_key(store):
    new = save(store, "saved", "first.test", "key")
    cfg = store.read(ACCOUNT)
    assert (
        store.check_api(ACCOUNT, {"baseUrl": "https://second.test/v1", "model": "new"}, None)[
            "apiKey"
        ]
        == ""
    )
    with pytest.raises(ValueError, match="主机已改变"):
        store.check_api(ACCOUNT, {"baseUrl": "https://second.test/v1"}, new["activeProfileId"])
    with pytest.raises(ValueError):
        store.profile(
            ACCOUNT,
            "save",
            {
                "id": new["activeProfileId"],
                "name": "new",
                "api": {"baseUrl": "https://second.test/v1"},
            },
        )
    assert store.read(ACCOUNT) == cfg


def test_card_patches_preserve_other_cards_profiles_and_credentials(store):
    saved = save(store, "first", "first.test", "key")
    store.save(ACCOUNT, {"persona": {"roleText": "new role"}})
    cfg = store.read(ACCOUNT)
    assert cfg["persona"]["roleText"] == "new role" and cfg["api"]["apiKey"] == "key"
    assert cfg["profiles"][0]["id"] == saved["activeProfileId"]
    store.save(ACCOUNT, {"deny": {"groups": ["99887766"]}})
    assert store.read(ACCOUNT)["persona"]["roleText"] == "new role"


def test_profile_delete_requires_another_active_profile_and_is_account_scoped(store):
    first = save(store, "first", "first.test", "key")["activeProfileId"]
    with pytest.raises(ValueError):
        store.profile(ACCOUNT, "delete", {"id": first})
    second = save(store, "second", "second.test", "key2")["activeProfileId"]
    store.profile(ACCOUNT, "delete", {"id": first})
    assert [p["id"] for p in store.read(ACCOUNT)["profiles"]] == [second]
    with pytest.raises(ValueError):
        store.profile(OTHER, "use", {"id": second})


def test_draft_model_checks_use_current_form_without_saving_or_changing_active_profile(
    store, tmp_path
):
    class Selection:
        def read(self):
            return ACCOUNT

    class Connection:
        def status(self):
            return {"state": "ready", "connected": True, "account": {"uin": ACCOUNT}}

    bridge = DesktopBridge(
        DesktopPaths(tmp_path, tmp_path),
        lambda **kwargs: None,
        connection=Connection(),
        selection=Selection(),
        settings=store,
    )
    before = store.read(ACCOUNT)

    def handler(request):
        assert (
            request.url.host == "draft.test"
            and request.headers["authorization"] == "Bearer draft-key"
        )
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "draft-model"}]})
        body = json.loads(request.content)
        assert body["model"] == "draft-model" and len(body["messages"]) == 1
        assert request.url.path == "/v1/chat/completions" and request.url.params["route"] == "test"
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    bridge._models = ModelChecks(transport=httpx.MockTransport(handler))
    draft = {
        "baseUrl": "https://draft.test/v1/chat/completions/?route=test",
        "model": "draft-model",
        "apiKey": "draft-key",
    }
    assert bridge.get_model_list(ACCOUNT, draft, None)["models"] == ["draft-model"]
    assert bridge.test_model_connection(ACCOUNT, draft, None)["ok"]
    assert store.read(ACCOUNT) == before
    assert not bridge.manage_model_profile("save", {}, None)["ok"]


def test_empty_model_response_is_not_reported_as_connected():
    import asyncio

    api = copy.deepcopy(DEFAULTS["api"]) | {"baseUrl": "https://model.test/v1", "model": "test"}
    checker = ModelChecks(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"choices": [{"message": {"content": None}}]})
        )
    )
    with pytest.raises(Exception, match="空内容"):
        asyncio.run(checker.test(api))
