import asyncio
import copy
import json

import httpx
import pytest

from QQBot.agent.config import DEFAULTS
from QQBot.agent.llm import ChatClient, ModelError
from QQBot.agent.media_models import resolve_media, understand, validate_media
from QQBot.agent.models import ModelChecks
from QQBot.agent.queries import expand_nodes
from QQBot.agent.service import AgentService


@pytest.mark.parametrize("field", ["max_tokens", "max_completion_tokens"])
def test_chat_limit_is_sent_once_using_the_explicit_field(field):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body[field] == 4321
        assert ("max_tokens" in body) != ("max_completion_tokens" in body)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    api = copy.deepcopy(DEFAULTS["api"]) | {
        "baseUrl": "https://model.test/v1",
        "model": "fixture",
        "chatTokenLimitField": field,
        "maxOutputTokens": 4321,
    }
    response = asyncio.run(
        ChatClient(transport=httpx.MockTransport(handler)).complete(
            api, [{"role": "user", "content": "中文"}], []
        )
    )
    assert response["message"]["content"] == "ok" and len(calls) == 1


@pytest.mark.parametrize(
    "error", [ValueError("known"), TimeoutError("timeout"), RuntimeError("native")]
)
def test_native_failure_while_stopping_preserves_cancellation_and_drains(error):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        completed = []

        async def native():
            entered.set()
            await release.wait()
            completed.append(True)
            raise error

        future = asyncio.create_task(native())
        waiter = asyncio.create_task(AgentService._await_native(future))
        await entered.wait()
        waiter.cancel()
        await asyncio.sleep(0)
        assert not waiter.done() and not future.cancelled()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert completed and future.done()

    asyncio.run(run())


def test_forward_counts_include_invalid_and_empty_omitted_nodes():
    value = expand_nodes([{"message": "first"}, {}, None, {"message": "last"}])
    assert value["shown"] == value["omitted"] == 2
    assert value["total"] == value["shown"] + value["omitted"]
    assert "还有 2 条未展开" in value["text"]


def test_image_check_missing_endpoint_never_opens_a_request():
    def handler(request):
        pytest.fail("Incomplete configuration must not send an HTTP request")

    with pytest.raises(ValueError, match="地址和模型"):
        asyncio.run(ModelChecks(transport=httpx.MockTransport(handler)).test_image(DEFAULTS["api"]))


def test_malformed_test_tool_arguments_are_model_errors_without_a_second_request():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "one",
                                    "type": "function",
                                    "function": {
                                        "name": "connection_check",
                                        "arguments": "not json",
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
        )

    api = copy.deepcopy(DEFAULTS["api"]) | {"baseUrl": "https://model.test/v1", "model": "test"}
    with pytest.raises(ModelError, match="响应格式"):
        asyncio.run(ModelChecks(transport=httpx.MockTransport(handler)).test_tools(api))
    assert len(calls) == 1


def test_missing_media_reference_and_retired_media_fields_are_explicit_errors():
    config = copy.deepcopy(DEFAULTS)
    config["mediaOptions"]["imageProfileId"] = "missing"
    with pytest.raises(ValueError, match="引用的模型"):
        resolve_media(config)
    with pytest.raises(ValueError, match="媒体设置"):
        validate_media({"mediaOptions": {"video": True}})

def test_bad_media_model_result_is_diagnostic_and_never_retried():
    class Model:
        calls = 0

        async def complete(self, *args):
            self.calls += 1
            return {}

    model = Model()
    with pytest.raises(ModelError, match="有效理解结果"):
        asyncio.run(understand(model, copy.deepcopy(DEFAULTS), [], lambda: True))
    assert model.calls == 1
