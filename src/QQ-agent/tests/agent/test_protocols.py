import copy
import json

import httpx
import pytest
from qqbot.agent.config import DEFAULTS, validate_api
from qqbot.agent.global_settings import GlobalSettings
from qqbot.agent.llm import ChatClient, ModelError, endpoint, normalize, request_body
from qqbot.agent.models import ModelChecks

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "read data",
            "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
        },
    }
]


@pytest.mark.parametrize("protocol", ["chat", "responses", "anthropic"])
def test_action_and_read_only_requests_use_compatible_tool_selection(
    protocol,
):
    from qqbot.agent.prompt import TOOLS as AGENT_TOOLS

    body = request_body(api(protocol), "test", [{"role": "user", "content": "hello"}], AGENT_TOOLS)
    assert body["tool_choice"] == ({"type": "auto"} if protocol == "anthropic" else "auto")
    normal = request_body(api(protocol), "test", [{"role": "user", "content": "hello"}], TOOLS)
    assert normal["tool_choice"] == ({"type": "auto"} if protocol == "anthropic" else "auto")
    check = request_body(api(protocol), "test", [{"role": "user", "content": "hello"}], [])
    assert "tool_choice" not in check and "tools" not in check


@pytest.mark.parametrize("protocol", ["chat", "responses", "anthropic"])
def test_search_is_only_advertised_as_a_local_function(protocol):
    from qqbot.agent.prompt import SEARCH_TOOL

    body = request_body(
        api(protocol), "test", [{"role": "user", "content": "搜索资料"}], [SEARCH_TOOL]
    )
    definition = body["tools"][0]
    if protocol == "chat":
        assert definition["type"] == "function" and definition["function"]["name"] == "web_search"
    elif protocol == "responses":
        assert definition["type"] == "function" and definition["name"] == "web_search"
    else:
        assert definition["name"] == "web_search" and "type" not in definition
    assert not set(body) & {"enable_search", "web_search_options", "search_parameters", "plugins"}
    with pytest.raises(ValueError, match="本地函数"):
        request_body(api(protocol), "test", [], [{"type": "web_search_preview"}])


@pytest.mark.parametrize("protocol", ["responses", "anthropic"])
def test_hosted_search_output_is_rejected(protocol):
    payload = response(protocol)
    if protocol == "responses":
        payload["output"] = [{"type": "web_search_call", "id": "hosted", "status": "completed"}]
    else:
        payload["content"] = [
            {
                "type": "server_tool_use",
                "id": "hosted",
                "name": "web_search",
                "input": {"query": "x"},
            }
        ]
    with pytest.raises(ValueError, match="服务端工具"):
        normalize(payload, protocol)


def api(protocol):
    return copy.deepcopy(DEFAULTS["api"]) | {
        "protocol": protocol,
        "baseUrl": "https://model.test/v1",
        "apiKey": "fixture-secret",
        "model": "chat-model",
        "sendTemperature": False,
    }


def response(protocol, *, calls=False):
    if protocol == "responses":
        return {
            "status": "completed",
            "model": "actual",
            "output": [
                {
                    "type": "reasoning",
                    "id": "rs_1",
                    "summary": [],
                    "encrypted_content": "opaque-state",
                },
                *(
                    [
                        {
                            "type": "function_call",
                            "call_id": "call-a",
                            "name": "read",
                            "arguments": '{"id":"1"}',
                        }
                    ]
                    if calls
                    else [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "pong", "annotations": []}],
                        }
                    ]
                ),
            ],
            "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
        }
    if protocol == "anthropic":
        return {
            "type": "message",
            "role": "assistant",
            "model": "actual",
            "stop_reason": "tool_use" if calls else "end_turn",
            "content": [
                {"type": "thinking", "thinking": "internal", "signature": "signed-state"},
                *(
                    [{"type": "tool_use", "id": "call-a", "name": "read", "input": {"id": "1"}}]
                    if calls
                    else [{"type": "text", "text": "pong"}]
                ),
            ],
            "usage": {
                "input_tokens": 3,
                "output_tokens": 4,
                "cache_read_input_tokens": 2,
                "cache_creation_input_tokens": 1,
            },
        }
    return {
        "choices": [{"message": {"content": "pong"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4},
    }


@pytest.mark.parametrize("protocol", ["chat", "responses", "anthropic"])
@pytest.mark.asyncio
async def test_connectivity_and_lists_follow_selected_protocol_without_temperature(protocol):
    seen = []

    def handler(request):
        seen.append(request)
        if protocol == "anthropic":
            assert (
                request.headers["x-api-key"] == "fixture-secret"
                and request.headers["anthropic-version"] == "2023-06-01"
            )
            assert "authorization" not in request.headers
        else:
            assert (
                request.headers["authorization"] == "Bearer fixture-secret"
                and "x-api-key" not in request.headers
            )
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "actual"}]})
        body = json.loads(request.content)
        assert "temperature" not in body and "tools" not in body
        assert "请只回复：pong" in request.content.decode()
        if protocol == "responses":
            assert body["store"] is False and body["max_output_tokens"] == 4096
        if protocol == "anthropic":
            assert body["max_tokens"] == 4096
        return httpx.Response(200, json=response(protocol))

    checks = ModelChecks(transport=httpx.MockTransport(handler))
    assert await checks.list_models(api(protocol)) == ["actual"]
    result = await checks.test(api(protocol))
    assert result["reply"] == "pong" and result["tokens"] == (10 if protocol == "anthropic" else 7)
    assert seen[0].url.path == "/v1/models"
    assert (
        seen[1].url.path
        == {
            "chat": "/v1/chat/completions",
            "responses": "/v1/responses",
            "anthropic": "/v1/messages",
        }[protocol]
    )


@pytest.mark.parametrize("protocol", ["responses", "anthropic"])
@pytest.mark.asyncio
async def test_multiple_round_tools_reasoning_and_images_preserve_native_continuation(protocol):
    messages = [{"role": "system", "content": "persona"}, {"role": "user", "content": "hello"}]
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if len(seen) == 1:
            tool = body["tools"][0]
            assert tool["name"] == "read"
            assert ("parameters" if protocol == "responses" else "input_schema") in tool
            return httpx.Response(200, json=response(protocol, calls=True))
        if protocol == "responses":
            items = body["input"]
            assert any(i.get("encrypted_content") == "opaque-state" for i in items)
            assert any(
                i.get("type") == "function_call_output" and i["call_id"] == "call-a" for i in items
            )
            assert items[-1]["content"][0]["type"] == "input_image"
            assert body["store"] is False and "previous_response_id" not in body
        else:
            assert body["system"] == [{"type": "text", "text": "persona"}]
            items = body["messages"]
            assert (
                items[-2]["role"] == "assistant"
                and items[-2]["content"][0]["signature"] == "signed-state"
            )
            blocks = items[-1]["content"]
            assert blocks[0]["type"] == "tool_result" and blocks[0]["tool_use_id"] == "call-a"
            assert blocks[1] == {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": "aGVsbG8="},
            }
        assert body["model"] == "visual-model"
        return httpx.Response(200, json=response(protocol))

    client = ChatClient(transport=httpx.MockTransport(handler))
    config = api(protocol) | {"vision": True, "visionModel": "visual-model"}
    first = await client.complete(config, messages, TOOLS)
    assert json.loads(first["message"]["tool_calls"][0]["function"]["arguments"]) == {"id": "1"}
    messages.extend(
        [
            first["message"],
            {"role": "tool", "tool_call_id": "call-a", "content": '{"found":true}'},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,aGVsbG8="}}
                ],
            },
        ]
    )
    assert (await client.complete(config, messages, TOOLS))["message"]["content"] == "pong"
    assert len(seen) == 2


@pytest.mark.parametrize("protocol", ["chat", "responses", "anthropic"])
@pytest.mark.parametrize("kind", ["truncated", "duplicate", "bad-args", "invalid-root"])
@pytest.mark.asyncio
async def test_bad_responses_fail_before_any_tools_are_exposed(protocol, kind):
    data = response(protocol, calls=True)
    if protocol == "chat":
        data = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "type": "function",
                                "id": "call-a",
                                "function": {"name": "read", "arguments": "{}"},
                            }
                        ]
                    }
                }
            ]
        }
    if kind == "invalid-root":
        data = []
    elif kind == "truncated":
        if protocol == "chat":
            data["choices"][0]["finish_reason"] = "length"
        elif protocol == "responses":
            data["status"] = "incomplete"
        else:
            data["stop_reason"] = "max_tokens"
    elif kind == "duplicate":
        if protocol == "chat":
            data["choices"][0]["message"]["tool_calls"] *= 2
        elif protocol == "responses":
            data["output"].append(copy.deepcopy(data["output"][-1]))
        else:
            data["content"].append(copy.deepcopy(data["content"][-1]))
    else:
        if protocol == "chat":
            data["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "not-json"
        elif protocol == "responses":
            data["output"][-1]["arguments"] = "not-json"
        else:
            data["content"][-1]["input"] = []
    client = ChatClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data)))
    with pytest.raises(ModelError):
        await client.complete(api(protocol), [{"role": "user", "content": "hi"}], TOOLS)


def test_protocol_defaults_profile_persistence_and_https_downgrade_key_guard(tmp_path):
    shared = GlobalSettings(tmp_path)
    old = copy.deepcopy(DEFAULTS["api"])
    for key in ("protocol", "sendTemperature", "maxOutputTokens"):
        old.pop(key)
    assert validate_api(old)["protocol"] == "chat"
    config = shared.profile(
        "global", "save", {"id": None, "name": "Claude", "api": api("anthropic")}
    )
    identifier = config["activeProfileId"]
    assert shared.read()["api"]["protocol"] == "anthropic"
    with pytest.raises(ValueError, match="协议或主机"):
        shared.profile(
            "global",
            "save",
            {"id": identifier, "name": "Claude", "api": {"baseUrl": "http://model.test/v1"}},
        )
    assert shared.read()["api"]["baseUrl"] == "https://model.test/v1"
    assert (
        endpoint("https://api.anthropic.com", "anthropic")
        == "https://api.anthropic.com/v1/messages"
    )
    assert (
        endpoint("https://model.test/prefix/responses", "responses", models=True)
        == "https://model.test/prefix/models"
    )


@pytest.mark.asyncio
async def test_connectivity_retains_user_temperature():
    def handler(request):
        assert json.loads(request.content)["temperature"] == 0.8
        return httpx.Response(200, json=response("chat"))

    await ModelChecks(transport=httpx.MockTransport(handler)).test(
        api("chat") | {"sendTemperature": True}
    )
