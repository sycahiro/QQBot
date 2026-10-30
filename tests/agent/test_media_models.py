import asyncio
import json

import httpx
import pytest
from test_agent import ACCOUNT, result, wait
from test_images import image_packet, install_native_images, raster

from QQBot.agent.global_settings import GlobalSettings
from QQBot.agent.images import ImageDownloader
from QQBot.agent.llm import ChatClient, ModelError
from QQBot.agent.media_models import resolve_media, understand
from QQBot.agent.models import ModelChecks


def add(shared, name, protocol="chat", activate=False):
    before = {p["id"] for p in shared.read()["profiles"]}
    value = shared.profile(
        "global",
        "save" if activate else "store",
        {
            "id": None,
            "name": name,
            "api": {
                "model": name,
                "protocol": protocol,
                "apiKey": name + "-key",
                "baseUrl": "https://" + name + ".test/v1",
            },
        },
    )
    return next(p["id"] for p in value["profiles"] if p["id"] not in before)


def test_global_media_bindings_survive_chat_switch_and_profile_store_never_activates(tmp_path):
    shared = GlobalSettings(tmp_path)
    a = add(shared, "chat", activate=True)
    b = add(shared, "eyes", "anthropic")
    assert shared.read()["activeProfileId"] == a
    shared.save("global", {"mediaOptions": {"vision": True, "imageProfileId": b}})
    config = shared.read()
    assert resolve_media(config)["apiKey"] == "eyes-key"
    add(shared, "other", activate=True)
    assert (
        shared.read()["mediaOptions"] == config["mediaOptions"] and shared.read()["api"]["vision"]
    )
    with pytest.raises(ValueError, match="图片理解"):
        shared.profile("global", "delete", {"id": b})
    before = (tmp_path / "settings" / "global.json").read_bytes()
    with pytest.raises(ValueError):
        shared.save("global", {"mediaOptions": {"imageProfileId": "missing"}})
    assert (tmp_path / "settings" / "global.json").read_bytes() == before
    shared.save("global", {"mediaOptions": {"imageProfileId": ""}})
    assert resolve_media(shared.read())["model"] == "other"


def test_missing_media_options_are_rejected_instead_of_rebuilt(tmp_path):
    shared = GlobalSettings(tmp_path)
    add(shared, "chat", activate=True)
    raw = json.loads((tmp_path / "settings" / "global.json").read_text())
    raw.pop("mediaOptions")
    (tmp_path / "settings" / "global.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="全局设置无法读取"):
        shared.read()

@pytest.mark.asyncio
async def test_media_request_isolated_tool_free_and_failure_has_no_fallback(tmp_path):
    shared = GlobalSettings(tmp_path)
    add(shared, "chat", activate=True)
    image = add(shared, "eyes", "anthropic")
    shared.save("global", {"mediaOptions": {"imageProfileId": image}})
    calls = []

    class Model:
        async def complete(self, api, messages, tools):
            calls.append((api, messages, tools))
            return result(content="红色图片")

    parts = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,aA=="}}]
    text, _ = await understand(Model(), shared.read(), parts, lambda: True)
    assert text == "红色图片" and calls[0][0]["protocol"] == "anthropic" and calls[0][2] == []
    assert len(calls[0][1]) == 2 and calls[0][1][1]["content"] == parts

    class Broken:
        async def complete(self, *args):
            calls.append(args)
            raise ModelError("failed")

    before = len(calls)
    with pytest.raises(ModelError):
        await understand(Broken(), shared.read(), parts, lambda: True)
    assert len(calls) == before + 1
    active = True

    class Cancelled:
        async def complete(self, *args):
            nonlocal active
            active = False
            return result(content="late")

    with pytest.raises(asyncio.CancelledError):
        await understand(Cancelled(), shared.read(), parts, lambda: active)


def test_agent_mixed_protocol_media_never_passes_chat_history_or_wire_state_to_vision(
    stack, monkeypatch, tmp_path
):
    service, receiver, sessions, settings, _, connection, _ = stack
    shared = GlobalSettings(tmp_path / "global")
    add(shared, "chat", "responses", True)
    eyes = add(shared, "eyes", "anthropic")
    shared.save("global", {"mediaOptions": {"vision": True, "imageProfileId": eyes}})
    settings._global_settings = shared
    install_native_images(connection)

    async def fetch(*args):
        return raster()

    monkeypatch.setattr(ImageDownloader, "fetch", fetch)
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append((request.url.host, body))
        if request.url.host == "eyes.test":
            assert body["messages"][0]["content"][0]["type"] == "text"
            assert "tools" not in body and "opaque-run-state" not in request.content.decode()
            assert (
                "【当前聊天】" not in request.content.decode()
                and ACCOUNT not in request.content.decode()
            )
            assert request.headers["x-api-key"] == "eyes-key"
            return httpx.Response(
                200,
                json={
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "红色图像"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 2, "output_tokens": 3},
                },
            )
        first = len(requests) == 1
        if not first:
            assert "base64," not in request.content.decode()
            assert any("红色图像" in i.get("output", "") for i in body["input"])
            assert any(i.get("encrypted_content") == "opaque-run-state" for i in body["input"])
        calls = (
            [("get_message_images", {"messageId": 1})]
            if first
            else [("send_message", {"messages": "看到了红色图像"}), ("finish", {"summary": "完成"})]
        )
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"type": "reasoning", "summary": [], "encrypted_content": "opaque-run-state"},
                    *[
                        {
                            "type": "function_call",
                            "call_id": name,
                            "name": name,
                            "arguments": json.dumps(args),
                        }
                        for name, args in calls
                    ],
                ],
                "usage": {"input_tokens": 2, "output_tokens": 3},
            },
        )

    service._model = ChatClient(transport=httpx.MockTransport(handler))
    receiver.receive(ACCOUNT, image_packet())
    service.process_once(ACCOUNT, "private:11223344")
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] != "running")
    item = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert item["status"] == "done", item["reason"]
    assert [host for host, _ in requests] == ["chat.test", "eyes.test", "chat.test"]
    assert item["usage"]["calls"] == 3 and item["model"] == "chat"
    assert "base64," not in json.dumps(item) and "opaque-run-state" not in json.dumps(item)


@pytest.mark.asyncio
async def test_image_check_sends_only_synthetic_image_and_profile_lookup_honors_binding(tmp_path):
    shared = GlobalSettings(tmp_path)
    add(shared, "chat", activate=True)
    eyes = add(shared, "eyes")

    def handler(request):
        body = json.loads(request.content)
        assert request.url.host == "eyes.test" and body["model"] == "eyes" and "tools" not in body
        assert body["messages"][0]["content"][1]["image_url"]["url"].startswith(
            "data:image/png;base64,"
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": "红色"}}]})

    assert (
        await ModelChecks(transport=httpx.MockTransport(handler)).test_image(
            shared.check_api("global", None, eyes)
        )
    )["reply"] == "红色"
