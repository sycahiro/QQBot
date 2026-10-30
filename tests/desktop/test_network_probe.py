import json

import pytest

from QQBot.agent.global_settings import GlobalSettings
from QQBot.agent.web import SearchError
from QQBot.desktop.bridge import DesktopBridge
from QQBot.desktop.paths import DesktopPaths


@pytest.fixture
def bridge(tmp_path):
    settings = GlobalSettings(tmp_path)
    b = DesktopBridge(DesktopPaths(tmp_path, tmp_path), lambda **_: None, global_settings=settings)
    yield b, settings, tmp_path
    b._reviews.close()


def test_probe_uses_actual_query_and_returns_results_without_enabling_or_saving(bridge):
    b, settings, path = bridge
    before = settings.values()
    calls = []

    async def search(config, query, permit):
        calls.append((config, query))
        assert permit()
        return {
            "results": [{"title": "真实结果", "url": "https://example.com/", "snippet": "摘要"}],
            "attempts": [],
        }

    b._web.search = search
    result = b.test_web_search(
        None, {"maxResults": 3}, {"kind": "search", "value": "想查的实际关键词"}
    )
    assert (
        result["ok"] and result["success"] and result["result"]["results"][0]["title"] == "真实结果"
    )
    assert calls[0][1] == "想查的实际关键词" and calls[0][0]["maxResults"] == 3
    assert settings.values() == before and not (path / "settings" / "global.json").exists()


def test_probe_retains_each_failed_stage_instead_of_generic_notice(bridge):
    b, _, _ = bridge
    stages = [
        {"engine": "bing", "mode": "direct", "status": "failed", "reason": "网站要求安全验证"}
    ]

    async def search(*_):
        raise SearchError("未取得结果", stages)

    b._web.search = search
    r = b.test_web_search(None, {}, {"kind": "search", "value": "测试"})
    assert r["ok"] and not r["success"] and r["attempts"] == stages


def test_fetch_probe_uses_same_reader_and_discards_changed_config(bridge):
    b, settings, _ = bridge
    calls = []

    async def fetch(url, permit):
        calls.append(url)
        assert permit()
        return {"title": "正文", "url": url, "content": "内容", "truncated": False}

    b._web.fetch = fetch
    r = b.test_web_search(None, {}, {"kind": "fetch", "value": "https://example.com/article"})
    assert r["ok"] and r["success"] and r["result"]["content"] == "内容"

    async def changed(url, permit):
        settings.save("global", {"webSearch": {"maxResults": 3}})
        return {"content": "应丢弃的内容"}

    b._web.fetch = changed
    r = b.test_web_search(None, {}, {"kind": "fetch", "value": "https://example.com/article"})
    assert not r["ok"] and r["error"]["code"] == "CONFIG_CHANGED"


@pytest.mark.parametrize(
    "probe",
    [
        {"kind": "fetch", "value": "http://127.0.0.1/"},
        {"kind": "command", "value": "anything"},
        {"kind": "search", "value": ""},
        [],
        {"kind": [], "value": "test"},
    ],
)
def test_invalid_probe_never_starts_network(bridge, probe):
    b, _, _ = bridge

    async def network(*_):
        raise AssertionError("must not request")

    b._web.fetch = b._web.search = network
    assert not b.test_web_search(None, {}, probe)["ok"]


def test_header_status_exposes_only_current_model_and_updates_after_save(bridge):
    b, settings, _ = bridge
    settings.save(
        "global",
        {"api": {"model": "model-one", "baseUrl": "https://example.com", "apiKey": "secret-value"}},
    )
    r = b.get_agent_status()
    assert r["model"] == "model-one" and not r["enabled"]
    assert "secret-value" not in json.dumps(r) and "example.com" not in json.dumps(r)
    settings.save("global", {"api": {"model": "model-two"}})
    assert b.get_agent_status()["model"] == "model-two"


def test_probe_can_use_a_saved_search_profile_from_an_unsaved_search_draft(bridge):
    b, settings, _ = bridge
    saved = settings.profile(
        "global",
        "store",
        {
            "id": None,
            "name": "搜索",
            "api": {
                "baseUrl": "https://search.example",
                "model": "search-model",
                "apiKey": "search-secret",
            },
        },
    )
    identifier = saved["profiles"][0]["id"]
    before = settings.values()
    calls = []

    async def local(*args):
        raise SearchError("blocked", [{"engine": e, "status": "failed"} for e in ("bing", "baidu")])

    async def provider(api, query, permit):
        assert permit() and api["apiKey"] == "search-secret"
        calls.append(query)
        return {
            "content": "联网结果",
            "model": "search-model",
            "results": [],
            "usage": {"promptTokens": 1, "completionTokens": 1, "totalTokens": 2, "calls": 1},
        }

    b._web.search = local
    b._web.hosted_search = provider
    r = b.test_web_search(
        None,
        {"fallback": True, "searchProfileId": identifier},
        {"kind": "search", "value": "查询词"},
    )
    assert (
        r["ok"]
        and r["success"]
        and r["result"]["engine"] == "model"
        and len(r["result"]["attempts"]) == 3
    )
    assert (
        settings.values() == before and calls == ["查询词"] and "search-secret" not in json.dumps(r)
    )


@pytest.mark.parametrize(
    "payload", [None, {"results": None}, {"results": {"title": "bad"}}, {"results": ["bad"]}]
)
def test_malformed_probe_result_is_an_explicit_failed_test_not_internal(bridge, payload):
    b, _, _ = bridge

    async def fetch(*args):
        return payload

    b._web.fetch = fetch
    result = b.test_web_search(None, {}, {"kind": "fetch", "value": "https://example.com/"})
    assert result["ok"] and not result["success"] and "结构无效" in result["message"]
