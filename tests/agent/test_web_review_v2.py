import asyncio
import threading
import time
import zlib
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from test_search_browser import BrowserError, Session, event, network, response

import QQBot.agent.web_browser as browser
from QQBot.agent import web


async def resolve(_host):
    return "93.184.216.34"


@pytest.mark.asyncio
async def test_cdp_delivery_failure_aborts_the_paused_main_request():
    session = Session(error=BrowserError("private-error"))
    handler = network(session)
    await handler.handle(event())
    await handler.handle(response())
    assert session.commands[-1][0] == "Fetch.failRequest"
    assert handler.main_error.code == "resource_delivery_failed"
    assert "private-error" not in str(handler.main_error)


@pytest.mark.asyncio
async def test_secondary_failure_is_diagnostic_and_does_not_poison_the_main_document():
    session = Session(error=BrowserError("private-error"))
    handler = network(session)
    request = event(resourceType="Script")
    await handler.handle(request)
    await handler.handle(response(resourceType="Script"))
    assert session.commands[-1][0] == "Fetch.failRequest"
    assert handler.failure is None and handler.main_error is None
    assert handler.resource_errors[0]["code"] == "resource_delivery_failed"


@pytest.mark.asyncio
async def test_browser_close_stops_accepting_resource_and_auth_tasks():
    handler = network(Session())
    await handler.close()
    handler.schedule(response())
    handler.reject_auth({"requestId": "late"})
    await asyncio.sleep(0)
    assert not handler.pending


@pytest.mark.asyncio
async def test_browser_slot_wait_is_bounded_cancellable_and_reusable(monkeypatch):
    monkeypatch.setattr(browser, "_SLOT", threading.BoundedSemaphore(1))
    monkeypatch.setattr(browser, "SLOT_WAIT", 0.01)
    entered, release = asyncio.Event(), asyncio.Event()

    class Held(browser.SearchBrowser):
        async def _render(self, *args):
            entered.set()
            await release.wait()
            return {"text": "ok"}

    first = asyncio.create_task(Held().render("bing", event()["request"]["url"], lambda: True))
    await entered.wait()
    with pytest.raises(browser.BrowserBusyError):
        await Held().render("bing", event()["request"]["url"], lambda: True)
    with pytest.raises(asyncio.CancelledError):
        await Held().render("bing", event()["request"]["url"], lambda: False)
    release.set()
    await first
    assert await Held().render("bing", event()["request"]["url"], lambda: True) == {"text": "ok"}


@pytest.mark.asyncio
async def test_busy_is_not_reported_as_engine_failure_and_never_starts_provider_fallback():
    calls = []

    class Busy:
        async def render(self, engine, *args):
            calls.append(engine)
            raise browser.BrowserBusyError()

    class Hosted:
        async def search(self, *args):
            raise AssertionError("Busy local capacity must not spend provider tokens")

    client = web.WebClient(browser=Busy(), hosted=Hosted())
    with pytest.raises(web.SearchError) as result:
        await web.search_with_fallback(
            client, {**web.DEFAULT_SEARCH, "fallback": True}, "query", lambda: True
        )
    assert result.value.code == "browser_busy" and calls == ["bing"]
    assert result.value.attempts[0]["code"] == "browser_busy"


@pytest.mark.asyncio
async def test_browser_timeout_runs_cleanup_and_releases_slot(monkeypatch):
    monkeypatch.setattr(browser, "RENDER_TIMEOUT", 0.01)
    monkeypatch.setattr(browser, "_SLOT", threading.BoundedSemaphore(1))
    closed = []

    class Slow(browser.SearchBrowser):
        async def _render(self, *args):
            try:
                await asyncio.sleep(5)
            finally:
                closed.append(True)

    with pytest.raises(browser.BrowserSearchError) as result:
        await Slow().render("bing", event()["request"]["url"], lambda: True)
    assert result.value.code == "browser_timeout" and closed == [True]
    assert browser._SLOT.acquire(blocking=False)
    browser._SLOT.release()


@pytest.mark.asyncio
async def test_cancellation_during_owned_cleanup_waits_for_the_cleanup_task():
    entered, release = asyncio.Event(), asyncio.Event()
    finished = []

    async def cleanup():
        entered.set()
        await release.wait()
        finished.append(True)

    task = asyncio.create_task(browser._finish_cleanup(cleanup))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished == [True]


@pytest.mark.asyncio
async def test_browser_inherits_the_web_clients_injected_resolver(monkeypatch):
    observed = []

    class Injected:
        def __init__(self, resolver):
            observed.append(resolver)

        async def render(self, *_args):
            raise ValueError("No network")

    monkeypatch.setattr(browser, "SearchBrowser", Injected)
    with pytest.raises(web.SearchError):
        await web.WebClient(resolver=resolve).search(
            web.DEFAULT_SEARCH, "2026 原文查询", lambda: True
        )
    assert observed == [resolve]


@pytest.mark.parametrize("args", [None, "query", [], ["query"], 1])
def test_web_tools_reject_non_objects_before_spending_the_call_budget(args):
    tools = web.WebTools({**web.DEFAULT_SEARCH, "enabled": True}, lambda: True)
    with pytest.raises(ValueError, match="对象"):
        asyncio.run(tools.execute("web_search", args))
    assert tools._calls == 0


def test_retired_search_secrets_are_rejected_instead_of_stripped():
    value = {**web.DEFAULT_SEARCH, "apiKey": "old-secret", "baseUrl": "old"}
    with pytest.raises(ValueError, match="字段"):
        web.validate_search(value)


@pytest.mark.parametrize("response", [None, {}, {"usage": {}}, {"usage": {}, "results": []}])
@pytest.mark.asyncio
async def test_malformed_hosted_response_keeps_the_structured_attempt_chain(response):
    usage = []

    class Client:
        async def search(self, *_args):
            raise web.SearchError("Local failed", [{"engine": "bing", "status": "failed"}])

        async def hosted_search(self, *_args):
            return response

    with pytest.raises(web.SearchError) as result:
        await web.search_with_fallback(
            Client(),
            {**web.DEFAULT_SEARCH, "fallback": True},
            "query",
            lambda: True,
            {"baseUrl": "https://example.com", "model": "test"},
            usage.append,
        )
    assert len(result.value.attempts) == 2
    assert result.value.attempts[-1]["status"] == "failed"
    assert usage == ([{}] if isinstance(response, dict) and "usage" in response else [])


class Chunks(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = data

    async def __aiter__(self):
        yield self.data[:1]
        yield self.data[1:]


@pytest.mark.parametrize("size", [40, web.MAX_BODY + 1])
def test_raw_deflate_is_supported_without_relaxing_expansion_bounds(size):
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    data = compressor.compress(b"x" * size) + compressor.flush()
    client = web.WebClient(
        resolver=resolve,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/plain", "content-encoding": "deflate"},
                stream=Chunks(data),
            )
        ),
    )
    if size > web.MAX_BODY:
        with pytest.raises(ValueError, match="上限|限制"):
            asyncio.run(client.fetch("https://example.com", lambda: True))
    else:
        assert (
            asyncio.run(client.fetch("https://example.com", lambda: True))["content"] == "x" * size
        )


def test_reader_dns_error_mentions_web_pages_not_images():
    async def invalid(_):
        raise ValueError("图片地址解析异常")

    with pytest.raises(ValueError, match="网页地址解析异常"):
        asyncio.run(web.WebClient(resolver=invalid).fetch("https://example.com", lambda: True))


def test_exact_redirect_limit_includes_the_final_document_request():
    seen = []

    def handler(request):
        seen.append(request)
        return (
            httpx.Response(302, headers={"location": f"https://example.com/{len(seen)}"})
            if len(seen) <= web.MAX_REDIRECTS
            else httpx.Response(200, headers={"content-type": "text/plain"}, text="done")
        )

    client = web.WebClient(resolver=resolve, transport=httpx.MockTransport(handler))
    assert asyncio.run(client.fetch("https://example.com", lambda: True))["content"] == "done"
    assert len(seen) == web.MAX_REDIRECTS + 1


@pytest.mark.asyncio
async def test_local_total_deadline_cancels_the_current_engine_without_an_extra_attempt(
    monkeypatch,
):
    monkeypatch.setattr(web, "LOCAL_SEARCH_TIMEOUT", 0.02)
    calls, drained = [], []

    class Slow:
        async def render(self, engine, *_args):
            calls.append(engine)
            try:
                await asyncio.sleep(5)
            finally:
                drained.append(engine)

    with pytest.raises(web.SearchError) as error:
        await web.WebClient(browser=Slow()).search(
            web.DEFAULT_SEARCH, "完整关键词2026", lambda: True
        )
    assert error.value.code == "search_timeout"
    assert calls == drained == ["bing"]
    assert error.value.attempts[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_page_total_budget_stops_a_drip_feed_and_closes_its_stream(monkeypatch):
    monkeypatch.setattr(web, "FETCH_TIMEOUT", 0.03)
    closed, calls = [], []

    class Drip(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                await asyncio.sleep(0.01)
                yield b"x"

        async def aclose(self):
            closed.append(True)

    def transport(request):
        calls.append(request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, stream=Drip())

    with pytest.raises(ValueError, match="超时"):
        await web.WebClient(resolver=resolve, transport=httpx.MockTransport(transport)).fetch(
            "https://example.com", lambda: True
        )
    assert closed == [True] and len(calls) == 1


@pytest.mark.asyncio
async def test_failed_main_dns_never_launches_a_browser_and_has_its_own_error_code():
    async def invalid(_host):
        raise OSError("Unresolved")

    with pytest.raises(browser.BrowserSearchError) as error:
        await browser.SearchBrowser(resolver=invalid)._render(
            "bing", event()["request"]["url"], lambda: True, time.monotonic() + 16
        )
    assert error.value.code == "dns_failed"


@pytest.mark.parametrize("late_main_failure", [False, True])
@pytest.mark.asyncio
async def test_real_renderer_orchestration_checks_late_main_failures_and_ignores_secondary_errors(
    monkeypatch, late_main_failure
):
    import playwright.async_api as playwright

    commands, listeners, closed = [], {}, []

    class FakeSession:
        async def send(self, name, args=None):
            commands.append((name, args))
            if name == "Page.getFrameTree":
                return {"frameTree": {"frame": {"id": "main"}}}
            return {}

        def on(self, name, callback):
            listeners[name] = callback

        def remove_listener(self, name, callback):
            assert listeners.pop(name) == callback

    class Page:
        url = event()["request"]["url"]

        async def goto(self, url, **kwargs):
            assert 0 < kwargs["timeout"] <= 8000

        async def wait_for_selector(self, selector, **kwargs):
            assert 0 < kwargs["timeout"] <= 2000
            handler = listeners["Fetch.requestPaused"].__self__
            handler.record_error(False, "resource_delivery_failed", "Optional resource failed")

        async def evaluate(self, script):
            assert "TextEncoder" in script
            if late_main_failure:
                handler = listeners["Fetch.requestPaused"].__self__
                handler.record_error(True, "resource_delivery_failed", "Main failed late")
            return '<li class="b_algo"><h2><a href="https://example.com">Result</a></h2></li>'

        def on(self, *_args):
            pass

    class Context:
        async def new_page(self):
            return Page()

        async def add_init_script(self, _script):
            pass

        def on(self, *_args):
            pass

        async def new_cdp_session(self, _page):
            return FakeSession()

        async def route_web_socket(self, *_args):
            pass

    class Chromium:
        async def launch(self, **kwargs):
            assert 0 < kwargs["timeout"] <= 7000
            assert "MAP * ~NOTFOUND" in " ".join(kwargs["args"])
            return self

        async def new_context(self, **_kwargs):
            return Context()

        async def close(self):
            closed.append(True)

    class Manager:
        async def __aenter__(self):
            return SimpleNamespace(chromium=Chromium())

        async def __aexit__(self, *_args):
            pass

    monkeypatch.setattr(playwright, "async_playwright", Manager)
    monkeypatch.setattr(playwright, "Error", BrowserError)
    # 现在走系统 Edge（channel="msedge"），启动前只用它做一次存在性检查。
    monkeypatch.setattr(browser, "edge_executable", lambda: Path("system-edge.exe"))

    async def partially_resolved(host):
        if host == "r.bing.com":
            raise OSError("DNS temporarily unavailable")
        return "93.184.216.34"

    render = browser.SearchBrowser(resolver=partially_resolved)._render(
        "bing", Page.url, lambda: True, time.monotonic() + 16
    )
    if late_main_failure:
        with pytest.raises(browser.BrowserSearchError, match="Main failed late"):
            await render
    else:
        result = await render
        assert result["diagnostics"]["unresolvedHosts"] == ["r.bing.com"]
        assert result["diagnostics"]["resourceErrors"][0]["code"] == "resource_delivery_failed"
    assert closed == [True] and not listeners
