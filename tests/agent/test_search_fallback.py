import asyncio

import httpx
import pytest

from QQBot.agent.web import DEFAULT_SEARCH, WebClient, parse_baidu, search_results
from QQBot.agent.web_browser import SearchBrowser, resource_allowed

BING = '<li class="b_algo"><h2><a href="https://www.python.org/">Python 官网</a></h2><p>官方资料</p></li>'
BAIDU = """<div id="content_left"><div class="result c-container" id="1">
<h3><a href="https://www.baidu.com/link?url=source"><em>Python</em> 官网</a></h3>
<div><span>官方资料</span><p>下载与文档</p></div><script>secret</script></div></div>"""


async def resolve(host):
    return "93.184.216.34"


def reply(html):
    return httpx.Response(
        200, headers={"content-type": "text/html;charset=utf-8"}, content=html.encode()
    )


def test_baidu_extracts_nested_results_skips_scripts_and_deduplicates():
    assert parse_baidu(BAIDU + BAIDU, 6) == [
        {
            "title": "Python 官网",
            "url": "https://www.baidu.com/link?url=source",
            "snippet": "官方资料 下载与文档",
        }
    ]
    assert (
        parse_baidu(BAIDU.replace("https://www.baidu.com/link?url=source", "http://127.0.0.1/"), 6)
        == []
    )
    assert parse_baidu('<h3><a href="https://bad.example/">Navigation</a></h3>', 6) == []
    assert search_results("baidu", '<input name="wd" value="different">' + BAIDU, 6)
    for engine, html in [("bing", BING), ("baidu", BAIDU)]:
        with pytest.raises(ValueError, match="验证"):
            search_results(engine, "<title>百度安全验证</title>" + html, 6)


class Browser:
    def __init__(self, calls, success="bing"):
        self.calls = calls
        self.success = success

    async def render(self, engine, target, permit):
        self.calls.append(("browser", engine))
        if engine != self.success:
            raise ValueError("blocked")
        return {"url": target, "text": BING if engine == "bing" else BAIDU}


@pytest.mark.parametrize("success", [("browser", "bing"), ("browser", "baidu")])
def test_fixed_order_stops_immediately_on_first_usable_result(success):
    calls = []

    def handler(request):
        raise AssertionError("Search must never use the direct HTTP reader")

    c = WebClient(
        transport=httpx.MockTransport(handler), resolver=resolve, browser=Browser(calls, success[1])
    )
    result = asyncio.run(c.search(DEFAULT_SEARCH, "Python 官网", lambda: True))
    order = [("browser", "bing"), ("browser", "baidu")]
    assert calls == order[: order.index(success) + 1]
    assert (result["mode"], result["engine"]) == success and result["attempts"][-1][
        "status"
    ] == "ok"
    assert len(result["attempts"]) == len(calls) and result["results"][0]["title"] == "Python 官网"


def test_empty_search_page_triggers_baidu():
    count = []

    class IrrelevantBrowser:
        async def render(self, engine, target, permit):
            count.append(engine)
            return {
                "url": target,
                "text": "<html><title>Bing</title></html>" if engine == "bing" else BAIDU,
            }

    c = WebClient(browser=IrrelevantBrowser())
    assert asyncio.run(c.search(DEFAULT_SEARCH, "Python 官网", lambda: True))["engine"] == "baidu"
    assert len(count) == 2


def test_cancellation_stops_fallback_without_starting_another_engine():
    active = [True]
    calls = []

    class CancelBrowser:
        async def render(self, *args):
            active[0] = False
            calls.append("browser")
            raise ValueError("cancelled")

    def handler(request):
        raise AssertionError("No direct request after cancellation")

    c = WebClient(transport=httpx.MockTransport(handler), resolver=resolve, browser=CancelBrowser())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(c.search(DEFAULT_SEARCH, "Python", lambda: active[0]))
    assert calls == ["browser"]


def test_all_failures_are_bounded_and_do_not_expose_server_bodies():
    calls = []

    def handler(request):
        raise AssertionError("Failed browser searches must never restore direct HTTP search")

    c = WebClient(
        transport=httpx.MockTransport(handler), resolver=resolve, browser=Browser(calls, None)
    )
    with pytest.raises(ValueError, match="均未返回") as error:
        asyncio.run(c.search(DEFAULT_SEARCH, "Python", lambda: True))
    assert len(calls) == 2 and "secret-body" not in str(error.value)
    assert [
        (entry["mode"], entry["engine"], entry["status"]) for entry in error.value.attempts
    ] == [("browser", "bing", "failed"), ("browser", "baidu", "failed")]
    assert all(entry["reason"] for entry in error.value.attempts)


def test_two_engine_search_consumes_one_tool_call_not_the_entire_run_budget():
    from QQBot.agent.web import SearchError, WebTools

    calls = []
    c = WebClient(
        transport=httpx.MockTransport(lambda _: reply("<title>安全验证</title>")),
        resolver=resolve,
        browser=Browser(calls, None),
    )
    tools = WebTools({**DEFAULT_SEARCH, "enabled": True}, lambda: True, client=c)
    for _ in range(4):
        with pytest.raises(SearchError):
            asyncio.run(tools.execute("web_search", {"query": "Python 官网"}))
    with pytest.raises(ValueError, match="4 次"):
        asyncio.run(tools.execute("web_search", {"query": "Python 官网"}))
    assert len(calls) == 8


@pytest.mark.parametrize(
    "url,kind,method,main",
    [
        ("http://www.baidu.com/s?wd=Python", "document", "GET", True),
        ("https://127.0.0.1/", "script", "GET", True),
        ("https://www.baidu.com.evil.example/a.js", "script", "GET", True),
        ("https://www.baidu.com:444/a.js", "script", "GET", True),
        ("https://user:pass@www.baidu.com/a.js", "script", "GET", True),
        ("https://www.baidu.com/a.js", "script", "POST", True),
        ("https://www.baidu.com/other", "document", "GET", True),
        ("https://www.baidu.com/s?wd=Python", "document", "GET", False),
        ("https://www.baidu.com/file", "image", "GET", True),
        ("https://www.baidu.com/file", "websocket", "GET", True),
    ],
)
def test_browser_network_is_limited_to_fixed_engine_gets(url, kind, method, main):
    assert not resource_allowed(
        "baidu", "https://www.baidu.com/s?wd=Python", url, kind, method, main
    )


def test_browser_allows_static_scripts_but_rejects_redirect_escape():
    assert resource_allowed(
        "baidu",
        "https://www.baidu.com/s?wd=Python",
        "https://ss0.bdstatic.com/a.js",
        "script",
        "GET",
        True,
    )
    assert resource_allowed(
        "bing",
        "https://cn.bing.com/search?q=Python",
        "https://r.bing.com/style.css",
        "stylesheet",
        "GET",
        True,
    )
    assert not resource_allowed(
        "baidu",
        "https://www.baidu.com/s?wd=Python",
        "https://public.example/",
        "document",
        "GET",
        True,
    )


def test_browser_renderer_cleans_up_after_account_change_and_releases_slot():
    active = [True]
    events = []

    class Fake(SearchBrowser):
        async def _render(self, *args):
            try:
                events.append("start")
                active[0] = False
                await asyncio.sleep(10)
            finally:
                events.append("close")

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(Fake().render("bing", "https://cn.bing.com/search?q=Python", lambda: active[0]))
    assert events == ["start", "close"]
    active[0] = True

    class Ready(SearchBrowser):
        async def _render(self, *args):
            return {"text": BING}

    assert (
        asyncio.run(Ready().render("bing", "https://cn.bing.com/search?q=Python", lambda: True))[
            "text"
        ]
        == BING
    )
