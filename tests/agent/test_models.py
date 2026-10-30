import copy
import json

import httpx
import pytest

from QQBot.agent.config import DEFAULTS, SettingsStore
from QQBot.agent.llm import ModelError
from QQBot.agent.models import ModelChecks
from QQBot.desktop.bridge import DesktopBridge
from QQBot.desktop.paths import DesktopPaths
from QQBot.storage.database import Database


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/v1", "/v1/", "/v1/chat/completions"])
async def test_models_use_same_endpoint_and_key_and_accept_upstream_list_shapes(path):
    api = copy.deepcopy(DEFAULTS["api"]) | {
        "baseUrl": "https://model.test" + path,
        "apiKey": "test-only",
    }

    def handler(request):
        assert str(request.url) == "https://model.test/v1/models"
        assert request.headers["authorization"] == "Bearer test-only"
        return httpx.Response(
            200,
            json={"data": [{"id": "b"}, {"model": "a"}, "b", {}, {"id": ""}, {"id": "bad\nname"}]},
        )

    assert await ModelChecks(transport=httpx.MockTransport(handler)).list_models(api) == ["a", "b"]


@pytest.mark.asyncio
async def test_connectivity_sends_only_fixed_prompt_without_qq_history_or_tools():
    api = copy.deepcopy(DEFAULTS["api"]) | {
        "baseUrl": "https://model.test/v1",
        "model": "test",
        "apiKey": "test-only",
    }
    calls = []

    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body["messages"] == [{"role": "user", "content": "请只回复：pong"}]
        assert body["model"] == "test" and "tools" not in body and "tool_choice" not in body
        return httpx.Response(
            200,
            json={
                "model": "actual",
                "choices": [{"message": {"content": "pong"}}],
                "usage": {"total_tokens": 5},
            },
        )

    result = await ModelChecks(transport=httpx.MockTransport(handler)).test(api)
    assert (
        result["reply"] == "pong"
        and result["model"] == "actual"
        and result["tokens"] == 5
        and len(calls) == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 404, 500, 302])
async def test_provider_failure_is_not_retried_or_echoed(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="private-key-and-provider-body")

    checker = ModelChecks(transport=httpx.MockTransport(handler))
    api = copy.deepcopy(DEFAULTS["api"]) | {"baseUrl": "https://model.test/v1", "model": "test"}
    for check in (checker.list_models, checker.test):
        with pytest.raises(ModelError) as error:
            await check(api)
        assert "private-key" not in str(error.value)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_invalid_and_oversized_model_lists_are_rejected():
    api = copy.deepcopy(DEFAULTS["api"]) | {"baseUrl": "https://model.test/v1"}
    for data in ({"invalid": []}, "x" * (2 * 1024 * 1024 + 1)):
        checker = ModelChecks(
            transport=httpx.MockTransport(lambda request, data=data: httpx.Response(200, json=data))
        )
        with pytest.raises(ModelError):
            await checker.list_models(api)


def test_bridge_uses_current_account_settings_and_rejects_results_after_disconnect(tmp_path):
    class Selection:
        def read(self):
            return "12345678"

    class Connection:
        connected = True

        def status(self):
            return {"state": "ready", "connected": self.connected, "account": {"uin": "12345678"}}

    connection = Connection()
    db = Database(tmp_path / "data.sqlite3")
    try:
        settings = SettingsStore(db)
        settings.save(
            "12345678",
            {
                "api": {
                    "baseUrl": "https://model.test/v1",
                    "model": "selected",
                    "apiKey": "current-key",
                }
            },
        )
        bridge = DesktopBridge(
            DesktopPaths(tmp_path, tmp_path),
            lambda **kwargs: None,
            connection=connection,
            selection=Selection(),
            settings=settings,
        )
        calls = []

        def handler(request):
            calls.append(request)
            assert request.headers["authorization"] == "Bearer current-key"
            if request.method == "GET":
                return httpx.Response(200, json=["selected"])
            return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

        bridge._models = ModelChecks(transport=httpx.MockTransport(handler))
        assert bridge.get_model_list("12345678")["models"] == ["selected"]
        assert bridge.test_model_connection("12345678")["model"] == "selected"
        assert not bridge.get_model_list("87654321")["ok"]
        assert not bridge.test_model_connection(None)["ok"] and len(calls) == 2

        async def disconnected(api):
            connection.connected = False
            return ["must-not-display"]

        bridge._models.list_models = disconnected
        assert not bridge.get_model_list("12345678")["ok"]
    finally:
        db.close()
