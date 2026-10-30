import asyncio
import gzip
import json

import httpx
import pytest
from qqbot.agent.config import DEFAULTS
from qqbot.agent.global_settings import GlobalSettings
from qqbot.agent.llm import ChatClient, ModelError, SearchModelError, request_body
from qqbot.agent.web import DEFAULT_SEARCH, SearchError, WebClient, WebTools, search_with_fallback
from test_agent import ACCOUNT, packet, result, wait
from test_agent import stack as stack


def api(protocol="responses"):
    return {
        **DEFAULTS["api"],
        "protocol": protocol,
        "baseUrl": "https://provider.example/v1",
        "model": "search-model",
        "apiKey": "search-secret",
    }


def payload(protocol):
    if protocol == "responses":
        return {
            "status": "completed",
            "model": "search-model",
            "usage": {"input_tokens": 7, "output_tokens": 3},
            "output": [
                {"type": "web_search_call", "status": "completed"},
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "检索回答",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://example.com/source",
                                    "title": "来源",
                                }
                            ],
                        }
                    ],
                },
            ],
        }
    if protocol == "anthropic":
        return {
            "type": "message",
            "role": "assistant",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 7, "output_tokens": 3, "cache_read_input_tokens": 2},
            "content": [
                {"type": "server_tool_use", "name": "web_search", "id": "search1"},
                {
                    "type": "web_search_tool_result",
                    "tool_use_id": "search1",
                    "content": [
                        {
                            "type": "web_search_result",
                            "url": "https://example.com/source",
                            "title": "来源",
                        }
                    ],
                },
                {"type": "text", "text": "检索回答"},
            ],
        }
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "检索回答",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url_citation": {"url": "https://example.com/source", "title": "来源"},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }


@pytest.mark.parametrize("protocol", ["chat", "responses", "anthropic"])
def test_three_native_search_protocols_use_only_the_selected_profile_and_fresh_query(protocol):
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        assert body["model"] == "search-model" and not body["stream"]
        assert "persona-secret" not in request.content.decode() and "history" not in body
        if protocol == "responses":
            assert (
                body["tools"] == [{"type": "web_search"}]
                and body["store"] is False
                and body["max_tool_calls"] == 1
            )
        elif protocol == "anthropic":
            assert (
                body["tools"][0]["max_uses"] == 1
                and request.headers["x-api-key"] == "search-secret"
            )
        else:
            assert (
                body["web_search_options"] == {"search_context_size": "low"} and "tools" not in body
            )
        return httpx.Response(200, json=payload(protocol))

    client = ChatClient(transport=httpx.MockTransport(handler))
    r = asyncio.run(client.search(api(protocol), "公开关键词", lambda: True))
    assert (
        len(requests) == 1
        and r["content"] == "检索回答"
        and r["results"][0]["url"] == "https://example.com/source"
    )
    assert r["usage"]["totalTokens"] == (12 if protocol == "anthropic" else 10)
    assert "search-secret" not in json.dumps(r)


@pytest.mark.parametrize("protocol", ["chat", "responses", "anthropic"])
def test_plaintext_without_native_search_evidence_is_failure_but_usage_is_retained(protocol):
    data = payload(protocol)
    if protocol == "responses":
        data["output"] = data["output"][1:]
    elif protocol == "anthropic":
        data["content"] = data["content"][2:]
    else:
        data["choices"][0]["message"]["annotations"] = []
    client = ChatClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data)))
    with pytest.raises(SearchModelError) as error:
        asyncio.run(client.search(api(protocol), "query", lambda: True))
    assert error.value.usage["calls"] == 1 and error.value.usage["totalTokens"] > 0


@pytest.mark.parametrize(
    "data",
    [
        [],
        None,
        {"status": "completed", "output": [None]},
        {"status": "completed", "output": [{"type": "code_interpreter_call"}]},
    ],
)
def test_malformed_or_unrequested_server_tool_output_is_rejected_without_exposing_payload(data):
    client = ChatClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data)))
    with pytest.raises(ModelError):
        asyncio.run(client.search(api(), "query", lambda: True))


def test_hosted_search_error_and_redirect_never_echo_body_or_forward_keys():
    for status in (302, 400, 500):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(
                status,
                text="sensitive-search-secret",
                headers={"location": "https://other.example/"},
            )

        with pytest.raises(ModelError) as error:
            asyncio.run(
                ChatClient(transport=httpx.MockTransport(handler)).search(
                    api(), "query", lambda: True
                )
            )
        assert len(calls) == 1 and "sensitive-search-secret" not in str(error.value)


def test_rejected_optional_parameter_is_dropped_and_retried_once():
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                400, json={"error": {"message": "Unsupported parameter: max_tool_calls"}}
            )
        return httpx.Response(200, json=payload("responses"))

    r = asyncio.run(
        ChatClient(transport=httpx.MockTransport(handler)).search(api(), "query", lambda: True)
    )
    bodies = [json.loads(request.content) for request in requests]
    assert len(requests) == 2
    assert bodies[0]["max_tool_calls"] == 1 and "max_tool_calls" not in bodies[1]
    assert r["content"] == "检索回答"


def test_parameter_fallback_is_generic_across_names_and_protocols():
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Unrecognized request argument supplied: max_output_tokens"
                    }
                },
            )
        return httpx.Response(200, json=payload("responses"))

    r = asyncio.run(
        ChatClient(transport=httpx.MockTransport(handler)).search(api(), "query", lambda: True)
    )
    bodies = [json.loads(request.content) for request in requests]
    assert len(requests) == 2
    assert "max_output_tokens" in bodies[0] and "max_output_tokens" not in bodies[1]
    assert r["content"] == "检索回答"


def test_rejections_naming_core_keys_or_nothing_are_not_retried():
    for message in ("Unsupported parameter: tools", "Invalid model identifier"):
        calls = []

        def handler(request, message=message, calls=calls):
            calls.append(request)
            return httpx.Response(400, json={"error": {"message": message}})

        with pytest.raises(ModelError, match=message):
            asyncio.run(
                ChatClient(transport=httpx.MockTransport(handler)).search(
                    api(), "query", lambda: True
                )
            )
        assert len(calls) == 1


def test_hosted_search_is_cancellable_and_closes_its_inflight_request():
    active = [True]
    closed = []

    async def handler(request):
        try:
            active[0] = False
            await asyncio.sleep(10)
        finally:
            closed.append(True)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            ChatClient(transport=httpx.MockTransport(handler)).search(
                api(), "query", lambda: active[0]
            )
        )
    assert closed == [True]


def test_shared_model_reader_bounds_compressed_response_before_expansion():
    wire = gzip.compress(b"x" * (5 * 1024 * 1024))
    client = ChatClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-encoding": "gzip"}, stream=httpx.ByteStream(wire)
            )
        )
    )
    with pytest.raises(ModelError, match="4 MB"):
        asyncio.run(client.search(api(), "query", lambda: True))


class SearchClient:
    def __init__(self, success=False, fail=False):
        self.calls = []
        self.success = success
        self.fail = fail

    async def search(self, config, query, permit):
        self.calls.append("local")
        if self.success:
            return {"results": []}
        raise SearchError(
            "local failed",
            [{"engine": e, "mode": "browser", "status": "failed"} for e in ("bing", "baidu")],
        )

    async def hosted_search(self, selected, query, permit):
        self.calls.append(("hosted", selected["model"], query))
        if self.fail:
            raise SearchModelError(
                "unsupported",
                {"promptTokens": 7, "completionTokens": 3, "totalTokens": 10, "calls": 1},
            )
        return {
            "model": selected["model"],
            "content": "检索回答",
            "results": [],
            "usage": {"promptTokens": 7, "completionTokens": 3, "totalTokens": 10, "calls": 1},
        }


@pytest.mark.parametrize(
    "local,enabled,expect",
    [
        (True, True, ["local"]),
        (False, False, ["local"]),
        (False, True, ["local", ("hosted", "search-model", "query")]),
    ],
)
def test_fallback_only_runs_after_local_failure_and_explicit_enable(local, enabled, expect):
    client = SearchClient(local)
    usage = []
    config = {**DEFAULT_SEARCH, "fallbackEnabled": enabled}
    if not local and not enabled:
        with pytest.raises(SearchError):
            asyncio.run(
                search_with_fallback(client, config, "query", lambda: True, api(), usage.append)
            )
    else:
        r = asyncio.run(
            search_with_fallback(client, config, "query", lambda: True, api(), usage.append)
        )
        if not local:
            assert [s["engine"] for s in r["attempts"]] == ["bing", "baidu", "model"] and r[
                "mode"
            ] == "provider"
    assert client.calls == expect and len(usage) == int(not local and enabled)


def test_failed_hosted_attempt_is_not_retried_and_usage_counts_once():
    client = SearchClient(fail=True)
    usage = []
    with pytest.raises(SearchError) as error:
        asyncio.run(
            search_with_fallback(
                client,
                {**DEFAULT_SEARCH, "fallbackEnabled": True},
                "query",
                lambda: True,
                api(),
                usage.append,
            )
        )
    assert len(client.calls) == 2 and len(usage) == 1 and len(error.value.attempts) == 3
    assert (
        error.value.attempts[-1]["status"] == "failed" and "elapsedMs" in error.value.attempts[-1]
    )


def test_cancelled_local_search_never_triggers_provider_search():
    class Cancel(SearchClient):
        async def search(self, *args):
            raise asyncio.CancelledError()

    client = Cancel()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            search_with_fallback(
                client, {**DEFAULT_SEARCH, "fallbackEnabled": True}, "query", lambda: True, api()
            )
        )
    assert not client.calls


def test_completed_provider_usage_is_kept_even_if_configuration_changed_before_return():
    active = [True]
    usage = []

    class Changed(SearchClient):
        async def hosted_search(self, *args):
            response = await super().hosted_search(*args)
            active[0] = False
            return response

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            search_with_fallback(
                Changed(),
                {**DEFAULT_SEARCH, "fallbackEnabled": True},
                "query",
                lambda: active[0],
                api(),
                usage.append,
            )
        )
    assert len(usage) == 1 and usage[0]["totalTokens"] == 10


def test_provider_fallback_still_consumes_only_one_web_tool_budget_slot():
    client = SearchClient()
    usage = []
    tools = WebTools(
        {**DEFAULT_SEARCH, "enabled": True, "fallbackEnabled": True},
        lambda: True,
        client=client,
        fallback_api=api(),
        on_usage=usage.append,
    )
    for _ in range(4):
        asyncio.run(tools.execute("web_search", {"query": "query"}))
    with pytest.raises(ValueError, match="4 次"):
        asyncio.run(tools.execute("web_search", {"query": "query"}))
    assert len(usage) == 4 and len(client.calls) == 8


def test_saved_search_binding_is_global_write_only_and_protects_profile_deletion(tmp_path):
    store = GlobalSettings(tmp_path)
    with pytest.raises(ValueError):
        store.save("global", {"webSearch": {"fallbackEnabled": True}})
    saved = store.profile("global", "store", {"id": None, "name": "搜索专用", "api": api()})
    identifier = saved["profiles"][0]["id"]
    store.save("global", {"webSearch": {"fallbackEnabled": True, "fallbackProfileId": identifier}})
    assert store.read()["api"]["model"] == "" and "search-secret" not in json.dumps(
        store.read(public=True)
    )
    with pytest.raises(ValueError, match="搜索"):
        store.profile("global", "delete", {"id": identifier})
    with pytest.raises(ValueError):
        store.save("global", {"webSearch": {"fallbackProfileId": "missing"}})
    store.save("global", {"webSearch": {"fallbackEnabled": False, "fallbackProfileId": ""}})
    assert store.profile("global", "delete", {"id": identifier})["profiles"] == []


def test_main_agent_transport_still_rejects_hosted_tools():
    with pytest.raises(ValueError):
        request_body(
            api(), "search-model", [{"role": "user", "content": "test"}], [{"type": "web_search"}]
        )


def test_search_fallback_usage_is_counted_in_agent_session_and_chat_model_is_unchanged(
    stack, monkeypatch
):
    service, receiver, sessions, settings, _, connection, _ = stack
    profile = settings.profile(ACCOUNT, "store", {"id": None, "name": "搜索", "api": api()})[
        "profiles"
    ][0]["id"]
    settings.save(
        ACCOUNT,
        {"webSearch": {"enabled": True, "fallbackEnabled": True, "fallbackProfileId": profile}},
    )

    async def local(self, *args):
        raise SearchError("local", [])

    async def hosted(self, selected, query, permit):
        assert selected["model"] == "search-model"
        return {
            "model": "search-model",
            "content": "检索回答",
            "results": [],
            "usage": {"promptTokens": 7, "completionTokens": 3, "totalTokens": 10, "calls": 1},
        }

    monkeypatch.setattr(WebClient, "search", local)
    monkeypatch.setattr(WebClient, "hosted_search", hosted)

    class Model:
        count = 0

        async def complete(self, selected, messages, tools):
            assert selected["model"] == "test"
            self.count += 1
            if self.count == 1:
                r = result()
                r["message"]["tool_calls"] = [
                    {
                        "id": "search",
                        "type": "function",
                        "function": {"name": "web_search", "arguments": '{"query":"query"}'},
                    }
                ]
                return r
            assert "检索回答" in messages[-1]["content"]
            return result("finish")

    service._model = Model()
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] != "running")
    item = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert (
        item["usage"]["calls"] == 3 and item["usage"]["totalTokens"] == 34 and not connection.calls
    )
    assert any(r.get("result", {}).get("engine") == "model" for r in item["records"])
