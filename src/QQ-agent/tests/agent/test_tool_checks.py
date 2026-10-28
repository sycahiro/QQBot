import copy
import json

import httpx
import pytest
from qqbot.agent.config import DEFAULTS
from qqbot.agent.llm import ModelError
from qqbot.agent.models import ModelChecks


def payload(protocol, first):
    if protocol == "chat":
        message = {
            "role": "assistant",
            "content": None if first else "pong",
            "reasoning_content": "live continuation",
        }
        if first:
            message["tool_calls"] = [
                {
                    "id": "check-1",
                    "type": "function",
                    "function": {"name": "connection_check", "arguments": '{"value":"pong"}'},
                }
            ]
        return {
            "model": "actual",
            "choices": [{"message": message}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
        }
    if protocol == "responses":
        return {
            "model": "actual",
            "status": "completed",
            "output": [
                {"type": "reasoning", "summary": [], "encrypted_content": "opaque-only"},
                {
                    "type": "function_call",
                    "call_id": "check-1",
                    "name": "connection_check",
                    "arguments": '{"value":"pong"}',
                }
                if first
                else {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "pong"}],
                },
            ],
            "usage": {"input_tokens": 1, "output_tokens": 2},
        }
    return {
        "model": "actual",
        "type": "message",
        "role": "assistant",
        "stop_reason": "tool_use" if first else "end_turn",
        "content": [
            {"type": "thinking", "thinking": "thinking", "signature": "signed-only"},
            {
                "type": "tool_use",
                "id": "check-1",
                "name": "connection_check",
                "input": {"value": "pong"},
            }
            if first
            else {"type": "text", "text": "pong"},
        ],
        "usage": {"input_tokens": 1, "output_tokens": 2},
    }


@pytest.mark.parametrize("protocol", ["chat", "responses", "anthropic"])
@pytest.mark.asyncio
async def test_tool_probe_performs_two_fixed_rounds_with_native_continuation(protocol):
    api = copy.deepcopy(DEFAULTS["api"])
    api.update(baseUrl="https://model.test/v1", model="test", protocol=protocol)
    original = copy.deepcopy(api)
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["tool_choice"] == ({"type": "auto"} if protocol == "anthropic" else "auto")
        assert len(body["tools"]) == 1
        if len(requests) == 2:
            if protocol == "chat":
                assert body["messages"][-2]["reasoning_content"] == "live continuation"
            elif protocol == "responses":
                assert any(i.get("type") == "function_call_output" for i in body["input"])
            else:
                assert body["messages"][-1]["content"][0]["type"] == "tool_result"
        return httpx.Response(200, json=payload(protocol, len(requests) == 1))

    result = await ModelChecks(transport=httpx.MockTransport(handler)).test_tools(api)
    assert len(requests) == 2 and result["tokens"] == 6 and result["model"] == "actual"
    assert api == original and "opaque-only" not in str(result) and "signed-only" not in str(result)


@pytest.mark.parametrize("failure", ["text-only", "bad-arguments", "http-first", "http-second"])
@pytest.mark.asyncio
async def test_tool_probe_failure_never_retries_or_switches_protocol(failure):
    api = copy.deepcopy(DEFAULTS["api"])
    api.update(baseUrl="https://model.test/v1", model="test")
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "http-first" or (failure == "http-second" and len(calls) == 2):
            return httpx.Response(400, text="secret-provider-body")
        data = payload("chat", True)
        if failure == "text-only":
            data = payload("chat", False)
        if failure == "bad-arguments":
            data["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = (
                '{"value":"wrong"}'
            )
        return httpx.Response(200, json=data)

    with pytest.raises(ModelError) as error:
        await ModelChecks(transport=httpx.MockTransport(handler)).test_tools(api)
    assert len(calls) == (2 if failure == "http-second" else 1)
    assert "secret-provider-body" not in str(error.value)
