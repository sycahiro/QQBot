"""Ephemeral Playwright renderer for fixed public search pages only.

The browser owns TLS, HTTP and its temporary cookies. Public DNS is resolved
before launch and pinned in Chromium; CDP bounds each response before delivery.
No listener, persistent profile, arbitrary URL navigation or background browser.
"""

import asyncio
import base64
import ipaddress
import logging
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

from .images import public_address

_EDGE_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
_SLOT = threading.BoundedSemaphore(1)
MAX_REQUESTS = 128
RENDER_TIMEOUT = 16
SLOT_WAIT = 1
CLEANUP_TIMEOUT = 1.5
HOSTS = {
    "bing": frozenset({"cn.bing.com", "www.bing.com", "bing.com", "r.bing.com"}),
    "baidu": frozenset(
        {
            "www.baidu.com",
            "ss0.bdstatic.com",
            "ss1.bdstatic.com",
            "ss2.bdstatic.com",
            "s1.bdstatic.com",
            "pss.bdstatic.com",
            "dss0.bdstatic.com",
            "dss1.bdstatic.com",
        }
    ),
}
TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "application/json",
    "application/javascript",
    "text/javascript",
    "application/x-javascript",
    "text/css",
)


class BrowserSearchError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class BrowserBusyError(BrowserSearchError):
    def __init__(self):
        super().__init__("browser_busy", "本地搜索浏览器忙，请稍后重试")


async def _finish_cleanup(cleanup):
    async def bounded():
        try:
            async with asyncio.timeout(CLEANUP_TIMEOUT):
                await cleanup()
        except Exception as error:
            logging.getLogger(__name__).warning("搜索浏览器清理未完成：%s", type(error).__name__)

    task = asyncio.create_task(bounded())
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    await task
    if cancelled:
        raise asyncio.CancelledError()


def edge_executable():
    """系统自带 Edge 的位置。

    只用来提前给出可读报错；真正启动走 Playwright 的 msedge 通道，由它处理 Edge
    的命令行差异。浏览器版本跟着 Windows 更新走，不再随项目打包。
    """
    try:
        import winreg
    except ImportError as error:  # pragma: no cover - 仅非 Windows 运行时
        raise ValueError("本地搜索浏览器只支持 Windows 自带的 Microsoft Edge") from error
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, _EDGE_KEY) as handle:
                value = winreg.QueryValue(handle, None)
        except OSError:
            continue
        if isinstance(value, str) and Path(value).is_file():
            return Path(value)
    raise ValueError("未找到系统自带的 Microsoft Edge，请确认 Edge 已安装且未被移除")


def resource_allowed(engine, target, url, kind, method, main_frame):
    """Only GETs to exact fixed HTTPS hosts; no subframe/main-page navigation."""
    try:
        parsed = urlsplit(url)
        if (
            method != "GET"
            or parsed.scheme != "https"
            or parsed.hostname not in HOSTS[engine]
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            return False
        if kind == "document":
            original = urlsplit(target)
            key = "q" if engine == "bing" else "wd"
            return (
                main_frame
                and parsed.path == original.path
                and bool(parse_qs(parsed.query).get(key))
            )
        # Search pages may keep their result container hidden until their
        # stylesheets have loaded. Blocking CSS changes page readiness.
        return kind in ("script", "stylesheet", "xhr", "fetch")
    except ValueError, KeyError:
        return False


class SearchBrowser:
    def __init__(self, resolver=public_address):
        self._resolver = resolver

    async def render(self, engine, target, permit):
        if not permit():
            raise asyncio.CancelledError()
        if engine not in HOSTS or not resource_allowed(
            engine, target, target, "document", "GET", True
        ):
            raise ValueError("浏览器仅用于 Bing 和百度的搜索页面")
        deadline = time.monotonic() + RENDER_TIMEOUT
        wait_until = min(deadline, time.monotonic() + SLOT_WAIT)
        while not _SLOT.acquire(blocking=False):
            if not permit():
                raise asyncio.CancelledError()
            if time.monotonic() >= wait_until:
                raise BrowserBusyError()
            await asyncio.sleep(0.05)
        try:
            work = asyncio.create_task(self._render(engine, target, permit, deadline))
            try:
                async with asyncio.timeout_at(
                    asyncio.get_running_loop().time() + max(0, deadline - time.monotonic())
                ):
                    while not work.done():
                        if not permit():
                            raise asyncio.CancelledError()
                        await asyncio.wait({work}, timeout=0.1)
                    if not permit():
                        raise asyncio.CancelledError()
                    return work.result()
            except TimeoutError as error:
                raise BrowserSearchError("browser_timeout", "本地搜索浏览器步骤超时") from error
            finally:
                if not work.done():
                    work.cancel()
                await asyncio.gather(work, return_exceptions=True)
        finally:
            _SLOT.release()

    async def _render(self, engine, target, permit, deadline):
        try:
            from playwright.async_api import Error as BrowserError
            from playwright.async_api import TimeoutError as BrowserTimeout
            from playwright.async_api import async_playwright
        except ImportError as error:
            raise ValueError("项目环境尚未安装 Playwright") from error
        # 提前查一次，能把「没装 Edge」变成中文报错，而不是 Playwright 的英文堆栈。
        edge_executable()

        def milliseconds(cap, stage):
            remaining = deadline - time.monotonic() - 0.35
            if remaining <= 0:
                raise BrowserSearchError("browser_timeout", f"搜索浏览器在{stage}阶段等待超时")
            return max(1, int(min(cap, remaining) * 1000))

        # Browser requests must not re-resolve a name to a private address later.
        # Failed optional CDN lookups are blocked; the main host is mandatory.
        async def resolve(host):
            try:
                async with asyncio.timeout(
                    min(
                        4 if host == urlsplit(target).hostname else 1.5,
                        milliseconds(4, "解析地址") / 1000,
                    )
                ):
                    address = await self._resolver(host)
                ip = ipaddress.ip_address(address)
                return (host, str(ip)) if ip.is_global else None
            except ValueError, OSError, TimeoutError:
                return None

        resolved = dict(
            item
            for item in await asyncio.gather(*(resolve(host) for host in HOSTS[engine]))
            if item
        )
        if urlsplit(target).hostname not in resolved:
            raise BrowserSearchError("dns_failed", "搜索网站无法解析为公开网络地址")
        rules = (
            ", ".join(
                f"MAP {host} {'[' + ip + ']' if ':' in ip else ip}" for host, ip in resolved.items()
            )
            + ", MAP * ~NOTFOUND"
        )
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    channel="msedge",
                    headless=True,
                    chromium_sandbox=True,
                    timeout=milliseconds(7, "启动"),
                    ignore_default_args=["--disable-popup-blocking"],
                    args=[
                        "--disable-background-networking",
                        "--disable-component-update",
                        "--disable-sync",
                        "--no-proxy-server",
                        "--host-resolver-rules=" + rules,
                        "--disable-quic",
                        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                    ],
                )
                context = None
                network = None
                try:
                    context = await browser.new_context(
                        locale="zh-CN",
                        viewport={"width": 1366, "height": 900},
                        service_workers="block",
                        accept_downloads=False,
                    )
                    page = await context.new_page()
                    # The renderer has no user interaction and never needs a new
                    # browsing target. Block script-created popups before content.
                    await context.add_init_script(
                        "Object.defineProperty(window,'open',{value:()=>null,writable:false,configurable:false})"
                    )

                    async def close_extra(extra):
                        if extra != page:
                            try:
                                await extra.close()
                            except BrowserError:
                                pass

                    context.on("page", close_extra)
                    policy = (
                        "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' "
                        + " ".join("https://" + h for h in HOSTS[engine])
                        + "; connect-src "
                        + " ".join("https://" + h for h in HOSTS[engine])
                        + "; style-src 'unsafe-inline' "
                        + " ".join("https://" + h for h in HOSTS[engine])
                        + "; img-src data:; frame-src 'none'; worker-src 'none'; base-uri 'none'; form-action 'none'"
                    )
                    session = await context.new_cdp_session(page)
                    frame = (await session.send("Page.getFrameTree"))["frameTree"]["frame"]["id"]
                    network = _PageNetwork(
                        engine,
                        target,
                        frame,
                        permit,
                        session,
                        policy,
                        BrowserError,
                        frozenset(resolved),
                    )
                    session.on("Fetch.requestPaused", network.schedule)
                    session.on("Fetch.authRequired", network.reject_auth)
                    await session.send(
                        "Fetch.enable",
                        {
                            "patterns": [{"urlPattern": "*", "requestStage": "Request"}],
                            "handleAuthRequests": True,
                        },
                    )

                    async def close_socket(socket):
                        try:
                            await socket.close()
                        except BrowserError:
                            pass

                    await context.route_web_socket("**/*", close_socket)

                    async def dismiss(dialog):
                        try:
                            await dialog.dismiss()
                        except BrowserError:
                            pass

                    page.on("dialog", dismiss)
                    try:
                        await page.goto(
                            target,
                            wait_until="domcontentloaded",
                            timeout=milliseconds(8, "加载页面"),
                        )
                    except BrowserError:
                        if network.main_error:
                            raise network.main_error
                        raise
                    try:
                        await page.wait_for_selector(
                            ".b_algo h2" if engine == "bing" else "#content_left h3",
                            state="attached",
                            timeout=milliseconds(2, "等待结果"),
                        )
                    except BrowserTimeout:
                        pass  # Return the DOM so the shared parser can identify a challenge page.
                    if network.main_error:
                        raise network.main_error
                    # Bound the serialized DOM before it crosses the browser pipe.
                    try:
                        html = await page.evaluate("""() => {
                            const html=document.documentElement.outerHTML;
                            if(new TextEncoder().encode(html).byteLength>2097152)return null;return html;
                        }""")
                    except BrowserError as error:
                        raise BrowserSearchError(
                            "dom_read_failed", "搜索页面正文提取失败"
                        ) from error
                    if html is None:
                        raise BrowserSearchError("dom_too_large", "搜索页面超过 2 MB 读取上限")
                    if network.main_error:
                        raise network.main_error
                    if not permit():
                        raise asyncio.CancelledError()
                    return {
                        "url": page.url,
                        "text": html,
                        "type": "text/html",
                        "diagnostics": {
                            "unresolvedHosts": sorted(HOSTS[engine] - frozenset(resolved)),
                            "resourceErrors": network.resource_errors,
                        },
                    }
                finally:
                    if network:
                        network.closing = True

                    async def cleanup():
                        try:
                            if network:
                                session.remove_listener("Fetch.requestPaused", network.schedule)
                                session.remove_listener("Fetch.authRequired", network.reject_auth)
                                await network.close()
                        finally:
                            await browser.close()

                    await _finish_cleanup(cleanup)
        except (BrowserError, OSError) as error:
            raise BrowserSearchError("browser_failed", "搜索浏览器未能完成页面读取") from error


class _PageNetwork:
    """Admit fixed GETs and stream native responses within a shared byte budget."""

    def __init__(
        self, engine, target, main_frame, permit, session, policy, browser_error, pinned_hosts
    ):
        self.engine, self.target, self.frame = engine, target, main_frame
        self.permit, self.session, self.policy = permit, session, policy
        self.hosts = pinned_hosts
        self.browser_error = browser_error
        self.pending = set()
        self.gate = asyncio.Semaphore(3)
        self.total = 0
        self.count = 0
        self.main_error = None
        self.failure = None
        self.closing = False
        self.dynamic_count = 0
        self.admitted = set()
        self.resource_errors = []

    def schedule(self, event):
        if self.closing:
            return
        task = asyncio.create_task(self.handle(event))
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)

    def reject_auth(self, event):
        if self.closing:
            return
        task = asyncio.create_task(self._auth(event))
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)

    async def _auth(self, event):
        try:
            await self.session.send(
                "Fetch.continueWithAuth",
                {
                    "requestId": event["requestId"],
                    "authChallengeResponse": {"response": "CancelAuth"},
                },
            )
        except self.browser_error:
            await self.abort(event["requestId"])

    async def abort(self, identifier):
        try:
            async with asyncio.timeout(0.3):
                await self.session.send(
                    "Fetch.failRequest", {"requestId": identifier, "errorReason": "BlockedByClient"}
                )
        except self.browser_error, TimeoutError:
            pass

    def record_error(self, main, code, message):
        error = BrowserSearchError(code, message)
        if main:
            self.main_error = self.failure = error
        elif len(self.resource_errors) < 8 and code not in [
            e["code"] for e in self.resource_errors
        ]:
            self.resource_errors.append({"code": code, "message": message})

    async def handle(self, event):
        identifier = event["requestId"]
        request = event["request"]
        kind = event.get("resourceType", "").lower()
        main = kind == "document" and event.get("frameId") == self.frame
        response = "responseStatusCode" in event or "responseErrorReason" in event
        try:
            if self.closing or not self.permit():
                await self.abort(identifier)
                return
            if not response:
                dynamic = kind in ("xhr", "fetch")
                if (
                    self.count >= MAX_REQUESTS
                    or (dynamic and self.dynamic_count >= 16)
                    or self.total >= 8 * 1024 * 1024
                    or urlsplit(request["url"]).hostname not in self.hosts
                    or not resource_allowed(
                        self.engine, self.target, request["url"], kind, request["method"], main
                    )
                ):
                    await self.abort(identifier)
                    return
                self.count += 1
                self.admitted.add(identifier)
                if dynamic:
                    self.dynamic_count += 1
                # This is native Chromium networking, not APIRequestContext or an
                # httpx replay. Inspect response headers before consuming its body.
                await self.session.send(
                    "Fetch.continueRequest", {"requestId": identifier, "interceptResponse": True}
                )
                return
            if identifier not in self.admitted:
                await self.abort(identifier)
                return
            self.admitted.discard(identifier)
            headers = event.get("responseHeaders", [])
            values = {h["name"].lower(): h["value"] for h in headers}
            status = event.get("responseStatusCode", 0)
            if status in (301, 302, 303, 307, 308):
                location = urljoin(request["url"], values.get("location", ""))
                if not resource_allowed(self.engine, self.target, location, kind, "GET", main):
                    raise ValueError("搜索页面跳转到非搜索页面或安全验证")
                await self.session.send("Fetch.continueResponse", {"requestId": identifier})
                return
            if not status:
                raise ValueError("搜索浏览器未能建立网站连接")
            if status != 200:
                raise ValueError(f"搜索网站返回 HTTP {status}")
            content_type = values.get("content-type", "").split(";")[0].strip().lower()
            if content_type not in TYPES:
                raise ValueError("搜索资源不是可读取的网页或脚本")
            length = values.get("content-length")
            if length and (not length.isdigit() or int(length) > 2 * 1024 * 1024):
                raise ValueError("搜索页面资源超过 2 MB 上限")
            async with self.gate:
                body = bytearray()
                stream = None
                try:
                    async with asyncio.timeout(9 if main else 4):
                        stream = (
                            await self.session.send(
                                "Fetch.takeResponseBodyAsStream", {"requestId": identifier}
                            )
                        )["stream"]
                        while True:
                            if not self.permit():
                                raise asyncio.CancelledError()
                            chunk = await self.session.send(
                                "IO.read", {"handle": stream, "size": 65536}
                            )
                            data = (
                                base64.b64decode(chunk["data"], validate=True)
                                if chunk.get("base64Encoded")
                                else chunk["data"].encode("utf-8")
                            )
                            body.extend(data)
                            self.total += len(data)
                            if len(body) > 2 * 1024 * 1024 or self.total > 8 * 1024 * 1024:
                                raise ValueError("搜索页面资源超过读取上限")
                            if chunk.get("eof"):
                                break
                finally:
                    if stream:
                        try:
                            await self.session.send("IO.close", {"handle": stream})
                        except self.browser_error:
                            pass
                if not self.permit():
                    raise asyncio.CancelledError()
                filtered = [
                    h
                    for h in headers
                    if h["name"].lower()
                    not in (
                        "content-length",
                        "content-encoding",
                        "transfer-encoding",
                        "connection",
                        "content-security-policy",
                        "content-security-policy-report-only",
                        "report-to",
                        "nel",
                    )
                ]
                filtered.append({"name": "Content-Security-Policy", "value": self.policy})
                await self.session.send(
                    "Fetch.fulfillRequest",
                    {
                        "requestId": identifier,
                        "responseCode": 200,
                        "responseHeaders": filtered,
                        "body": base64.b64encode(body).decode("ascii"),
                    },
                )
        except (ValueError, TimeoutError) as error:
            self.record_error(
                main,
                "resource_timeout" if isinstance(error, TimeoutError) else "resource_rejected",
                "搜索页面读取超时" if isinstance(error, TimeoutError) else str(error),
            )
            await self.abort(identifier)
        except self.browser_error:
            if not self.closing:
                self.record_error(main, "resource_delivery_failed", "搜索页面资源交付失败")
            await self.abort(identifier)
        except asyncio.CancelledError:
            await self.abort(identifier)
            raise
        except Exception:
            self.record_error(main, "resource_processing_failed", "搜索页面资源处理失败")
            await self.abort(identifier)

    async def close(self):
        self.closing = True
        tasks = list(self.pending)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
