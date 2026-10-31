import asyncio
import gzip
import json
import zlib

import httpx
import pytest
from test_agent import ACCOUNT, OTHER, packet, result, wait

from QQBot.agent.config import SettingsStore
from QQBot.agent.web import (
    DEFAULT_SEARCH,
    SearchError,
    WebClient,
    WebTools,
    merge_search,
    parse_rss,
    sanitize_query,
    validate_search,
    web_url,
)
from QQBot.agent.web_pages import TextParser
from QQBot.storage.database import Database


async def resolve(host):
    return "93.184.216.34"


def client(handler):
    return WebClient(transport=httpx.MockTransport(handler), resolver=resolve)


def response(html=None):
    return httpx.Response(
        200,
        headers={"content-type": "text/html; charset=utf-8"},
        content=(html or '<html><title>Search</title><p>Readable text</p></html>').encode(),
    )


def rss(*items):
    entries = "".join(
        f"<item><title>{t}</title><link>{u}</link><description>{s}</description></item>"
        for t, u, s in items
    )
    return f"<rss><channel>{entries}</channel></rss>"


RSS = rss(("Python 官网", "https://www.python.org/", "官方资料"))


def rss_response(body=RSS):
    return httpx.Response(
        200,
        headers={"content-type": "application/rss+xml; charset=utf-8"},
        content=body.encode(),
    )


HTML = '<html><title>Search</title><p>Readable text</p></html>'


@pytest.mark.parametrize(
    "url",
    [
        "file:///secret",
        "data:text/html,hi",
        "http://127.0.0.1/",
        "https://localhost/",
        "https://10.0.0.1/",
        "http://[::1]/",
        "https://example.test:444/",
        "https://user:secret@example.test/",
        "https://example.test/\n",
    ],
)
def test_public_web_urls_reject_local_paths_private_addresses_and_credentials(url):
    with pytest.raises(ValueError):
        web_url(url)


def test_query_and_rss_parser_preserve_sources_without_markup():
    assert sanitize_query(" [CQ:at,qq=1] Python\n 官网 ") == "Python 官网"
    assert parse_rss(rss(("Python <b>官网</b>", "https://www.python.org/", "官方 <i>资料</i>")), 6) == [
        {"title": "Python 官网", "url": "https://www.python.org/", "snippet": "官方 资料"}
    ]
    parser = TextParser()
    parser.feed(
        "<title>页面</title><nav>导航</nav><article><h1>正文</h1><p>你好</p><script>偷取密钥</script></article>"
    )
    assert parser.text() == "正文\n你好" and "".join(parser.title) == "页面"


def test_bing_rss_receives_the_encoded_query_and_no_api_key():
    requests = []

    def handler(request):
        requests.append(request)
        return rss_response()

    r = asyncio.run(
        client(handler).search({**DEFAULT_SEARCH, "apiKey": "never-send-to-bing"}, "Python 官网", lambda: True)
    )
    assert r["results"] == [{"title": "Python 官网", "url": "https://www.python.org/", "snippet": "官方资料"}]
    assert r["engine"] == "bing" and r["mode"] == "rss"
    assert len(requests) == 1
    assert requests[0].url.host == "www.bing.com" and requests[0].url.path == "/search"
    assert requests[0].url.params["format"] == "rss"
    assert (
        "authorization" not in requests[0].headers and requests[0].url.params["q"] == "Python 官网"
    )


def test_rss_results_are_validated_deduplicated_and_truncated():
    body = rss(
        ("First", "https://example.com/one", "one"),
        ("Second", "https://example.com/two", "two"),
        ("Dup", "https://example.com/one", "dup"),
        ("Private", "http://127.0.0.1/secret", "skip"),
        ("NoLink", "", "skip"),
    )
    assert parse_rss(body, 2) == [
        {"title": "First", "url": "https://example.com/one", "snippet": "one"},
        {"title": "Second", "url": "https://example.com/two", "snippet": "two"},
    ]


def test_rss_failures_surface_as_a_single_failed_attempt():
    for reply, code in (
        (httpx.Response(503, text="down"), "search_failed"),
        (httpx.Response(200, content=b"<rss><channel></channel></rss>"), "search_failed"),
        (httpx.Response(200, content=b"<rss><channel><item>broken"), "search_failed"),
    ):
        with pytest.raises(SearchError) as error:
            asyncio.run(client(lambda _, r=reply: r).search(DEFAULT_SEARCH, "x", lambda: True))
        assert error.value.code == code
        assert error.value.attempts == [
            {"engine": "bing", "mode": "rss", "status": "failed", "reason": error.value.attempts[0]["reason"], "elapsedMs": error.value.attempts[0]["elapsedMs"]}
        ]


def test_search_result_urls_are_not_the_query_echo():
    result = asyncio.run(
        client(lambda _: rss_response()).search(DEFAULT_SEARCH, "2026 英雄联盟总决赛", lambda: True)
    )
    assert result["engine"] == "bing" and httpx.URL(result["searchUrl"]).params["q"] == "2026 英雄联盟总决赛"


def test_retired_search_addresses_and_channels_are_rejected_instead_of_migrated():
    for key in ("baseUrl", "baiduBaseUrl", "provider", "apiKey", "mode", "fallback", "searchProfileId"):
        value = "local" if key == "mode" else True if key == "fallback" else "https://example.com/s"
        with pytest.raises(ValueError, match="字段|未知字段"):
            validate_search({**DEFAULT_SEARCH, key: value})
        with pytest.raises(ValueError, match="未知字段"):
            merge_search(DEFAULT_SEARCH, {key: value})

def test_redirect_rechecks_dns_before_following_the_new_address():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://private.example/"})

    async def resolver(host):
        return "127.0.0.1" if host == "private.example" else "93.184.216.34"

    c = WebClient(transport=httpx.MockTransport(handler), resolver=resolver)
    with pytest.raises(ValueError):
        asyncio.run(c.fetch("https://public.example/", lambda: True))
    assert len(calls) == 1


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(200, headers={"content-type": "text/html", "content-length": "3000000"}),
        httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF"),
        httpx.Response(500, text="private-server-error"),
    ],
)
def test_limits_formats_and_error_bodies_are_not_exposed(reply):
    with pytest.raises(ValueError) as error:
        asyncio.run(client(lambda _: reply).fetch("https://example.com/", lambda: True))
    assert "private-server-error" not in str(error.value)


@pytest.mark.parametrize("encoding,compress", [("gzip", gzip.compress), ("deflate", zlib.compress)])
def test_compressed_html_is_read_without_unbounded_expansion(encoding, compress):
    def good(_):
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-encoding": encoding},
            stream=httpx.ByteStream(compress(b"<title>Source</title><p>Readable text</p>")),
        )

    result = asyncio.run(client(good).fetch("https://example.com/", lambda: True))
    assert result["title"] == "Source" and result["content"] == "Readable text"

    def bomb(_):
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-encoding": encoding},
            stream=httpx.ByteStream(compress(b"a" * (3 * 1024 * 1024))),
        )

    with pytest.raises(ValueError, match="上限|限制"):
        asyncio.run(client(bomb).fetch("https://example.com/", lambda: True))


def test_article_truncation_retains_title_and_source_and_cancelled_read_returns_no_text():
    result = asyncio.run(
        client(lambda _: response("<title>Source</title><p>" + "a" * 16000 + "</p>")).fetch(
            "https://example.com/", lambda: True
        )
    )
    assert (
        result["truncated"]
        and len(result["content"]) == 12000
        and result["url"] == "https://example.com/"
    )
    active = [True]

    def handler(_):
        active[0] = False
        return response()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(client(handler).fetch("https://example.com/", lambda: active[0]))


def test_disabled_budget_browse_and_cancellation_gates():
    count = []

    def handler(request):
        if request.url.path != "/":
            count.append(request)
        return rss_response() if request.url.path == "/search" else response(HTML)

    c = client(handler)
    off = WebTools(DEFAULT_SEARCH, lambda: True, client=c)
    with pytest.raises(ValueError, match="关闭"):
        asyncio.run(off.execute("web_search", {"query": "x"}))
    assert not count
    tools = WebTools({**DEFAULT_SEARCH, "enabled": True, "browse": False}, lambda: True, client=c)
    with pytest.raises(ValueError, match="关闭"):
        asyncio.run(tools.execute("web_fetch", {"url": "https://example.com/"}))
    for _ in range(4):
        asyncio.run(tools.execute("web_search", {"query": "Python"}))
    with pytest.raises(ValueError, match="4 次"):
        asyncio.run(tools.execute("web_search", {"query": "x"}))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            WebTools({**DEFAULT_SEARCH, "enabled": True}, lambda: False, client=c).execute(
                "web_search", {"query": "x"}
            )
        )
    assert len(count) == 4


def test_search_settings_are_keyless_and_draft_checks_do_not_save(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    s = SettingsStore(db)
    try:
        s.save(ACCOUNT, {"webSearch": {"enabled": True}})
        assert set(s.read(ACCOUNT, public=True)["webSearch"]) == set(DEFAULT_SEARCH)
        assert not s.read(OTHER)["webSearch"]["enabled"] and not s.read(ACCOUNT)["api"]["apiKey"]
        for patch in ({"provider": "bocha"}, {"apiKey": "unused"}):
            with pytest.raises(ValueError):
                s.save(ACCOUNT, {"webSearch": patch})
        s.check_search(ACCOUNT, {"maxResults": 2})
        assert s.read(ACCOUNT)["webSearch"]["maxResults"] == 6
    finally:
        db.close()


def test_agent_exposes_search_only_when_enabled_and_logs_tool_result(stack, monkeypatch):
    service, receiver, sessions, settings, _, connection, _model = stack
    calls = []

    async def search(self, config, query, permit):
        calls.append(query)
        return {"results": [{"title": "来源", "url": "https://example.com/", "snippet": "资料"}]}

    monkeypatch.setattr(WebClient, "search", search)

    class Model:
        def __init__(self):
            self.count = 0

        async def complete(self, api, messages, tools):
            assert "web_search" in {t["function"]["name"] for t in tools}
            self.count += 1
            if self.count == 1:
                r = result()
                r["message"]["tool_calls"] = [
                    {
                        "id": "search-1",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": json.dumps({"query": "Python"}),
                        },
                    }
                ]
                return r
            assert "https://example.com/" in messages[-1]["content"]
            return result("finish")

    settings.save(ACCOUNT, {"webSearch": {"enabled": True}})
    service._model = Model()
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] != "running")
    item = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert (
        calls == ["Python"]
        and not connection.calls
        and any(r.get("name") == "web_search" for r in item["records"])
    )
