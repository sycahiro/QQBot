import asyncio
import base64

import pytest
from qqbot.agent.web_browser import HOSTS, _PageNetwork


def test_edge_is_located_through_the_app_paths_key(monkeypatch, tmp_path):
    import winreg

    import qqbot.agent.web_browser as module

    exe = tmp_path / "msedge.exe"
    exe.write_bytes(b"")

    class Handle:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def open_key(root, _key):
        if root == winreg.HKEY_LOCAL_MACHINE:
            return Handle()
        raise OSError(2, "not found")

    monkeypatch.setattr(winreg, "OpenKey", open_key)
    monkeypatch.setattr(winreg, "QueryValue", lambda _handle, _name: str(exe))
    assert module.edge_executable() == exe


def test_missing_edge_gets_a_readable_error(monkeypatch):
    import winreg

    import qqbot.agent.web_browser as module

    def missing(*_args, **_kwargs):
        raise OSError(2, "not found")

    monkeypatch.setattr(winreg, "OpenKey", missing)
    with pytest.raises(ValueError, match="未找到系统自带的 Microsoft Edge"):
        module.edge_executable()


TARGET = "https://cn.bing.com/search?q=Python"


class BrowserError(Exception):
    pass


class Session:
    def __init__(self, body=b"<title>Python</title>", error=None):
        self.body = body
        self.position = 0
        self.commands = []
        self.error = error

    async def send(self, method, params):
        self.commands.append((method, params))
        if method == "Fetch.fulfillRequest" and self.error:
            raise self.error
        if method == "Fetch.takeResponseBodyAsStream":
            return {"stream": "stream-1"}
        if method == "IO.read":
            end = self.position + params["size"]
            data = self.body[self.position : end]
            self.position = end
            return {
                "data": base64.b64encode(data).decode(),
                "base64Encoded": True,
                "eof": end >= len(self.body),
            }
        return {}


def event(identifier="1", **extra):
    return {
        "requestId": identifier,
        "frameId": "main",
        "resourceType": "Document",
        "request": {"url": TARGET, "method": "GET"},
        **extra,
    }


def response(identifier="1", **extra):
    return event(
        identifier,
        responseStatusCode=200,
        responseHeaders=[{"name": "content-type", "value": "text/html"}],
        **extra,
    )


def network(session, permit=lambda: True):
    return _PageNetwork(
        "bing", TARGET, "main", permit, session, "default-src none", BrowserError, HOSTS["bing"]
    )


@pytest.mark.asyncio
async def test_native_request_is_continued_then_streamed_before_delivery():
    session = Session(body="正文".encode())
    n = network(session)
    await n.handle(event())
    await n.handle(response())
    commands = [c[0] for c in session.commands]
    assert commands == [
        "Fetch.continueRequest",
        "Fetch.takeResponseBodyAsStream",
        "IO.read",
        "IO.close",
        "Fetch.fulfillRequest",
    ]
    assert base64.b64decode(session.commands[-1][1]["body"]) == "正文".encode()
    assert n.failure is None and n.main_error is None


@pytest.mark.asyncio
async def test_private_redirect_and_unadmitted_responses_never_deliver():
    session = Session()
    n = network(session)
    await n.handle(event())
    await n.handle(
        event(
            responseStatusCode=302,
            responseHeaders=[{"name": "location", "value": "http://127.0.0.1/"}],
        )
    )
    await n.handle(response("unadmitted"))
    assert n.main_error and not any(c[0] == "Fetch.fulfillRequest" for c in session.commands)
    assert sum(c[0] == "Fetch.failRequest" for c in session.commands) == 2


@pytest.mark.asyncio
async def test_bounded_stream_closes_handle_on_oversize_chunked_response():
    session = Session(body=b"x" * (2 * 1024 * 1024 + 1))
    n = network(session)
    await n.handle(event())
    await n.handle(response())
    assert "上限" in str(n.main_error)
    assert any(c[0] == "IO.close" for c in session.commands)
    assert not any(c[0] == "Fetch.fulfillRequest" for c in session.commands)


@pytest.mark.asyncio
async def test_browser_failures_are_collected_as_safe_structured_errors():
    session = Session(error=BrowserError("sensitive provider failure"))
    n = network(session)
    await n.handle(event())
    n.schedule(response())
    await asyncio.gather(*n.pending)
    await asyncio.sleep(0)
    assert str(n.failure) == "搜索页面资源交付失败" and not n.pending


@pytest.mark.asyncio
async def test_close_cancels_and_collects_stream_tasks_and_closes_handle():
    entered = asyncio.Event()

    class Slow(Session):
        async def send(self, method, params):
            if method == "IO.read":
                entered.set()
                await asyncio.sleep(10)
            return await super().send(method, params)

    session = Slow()
    n = network(session)
    await n.handle(event())
    n.schedule(response())
    await entered.wait()
    await n.close()
    assert not n.pending and any(c[0] == "IO.close" for c in session.commands)
    assert not any(c[0] == "Fetch.fulfillRequest" for c in session.commands)


@pytest.mark.asyncio
async def test_resource_budget_stops_129th_native_request():
    session = Session()
    n = network(session)
    for i in range(129):
        await n.handle(event(str(i)))
    assert n.count == 128
    assert sum(c[0] == "Fetch.continueRequest" for c in session.commands) == 128
    assert session.commands[-1][0] == "Fetch.failRequest"


@pytest.mark.asyncio
async def test_subframe_and_post_and_unresolved_host_are_denied_before_network():
    session = Session()
    n = network(session)
    await n.handle(event(frameId="other"))
    await n.handle(event(request={"url": TARGET, "method": "POST"}))
    n.hosts = frozenset()
    await n.handle(event())
    assert all(c[0] == "Fetch.failRequest" for c in session.commands) and n.count == 0


@pytest.mark.asyncio
async def test_dynamic_request_flood_cannot_consume_the_static_script_budget():
    session = Session()
    n = network(session)
    for i in range(17):
        await n.handle(
            event(
                str(i),
                resourceType="XHR",
                request={"url": "https://cn.bing.com/telemetry", "method": "GET"},
            )
        )
    assert (
        n.dynamic_count == 16 and n.count == 16 and session.commands[-1][0] == "Fetch.failRequest"
    )
    await n.handle(
        event(
            "required-script",
            resourceType="Script",
            request={"url": "https://cn.bing.com/required.js", "method": "GET"},
        )
    )
    assert session.commands[-1][0] == "Fetch.continueRequest" and n.count == 17
