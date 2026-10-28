import asyncio
import base64
import copy
import io
import json
import threading

import httpx
import pytest
from PIL import Image
from qqbot.agent.images import ImageDownloader
from qqbot.agent.outgoing_images import OutgoingImages, public_image_url
from qqbot.qq.engine import EngineError
from test_agent import ACCOUNT, OTHER, PEER, packet, result, wait
from test_agent import stack as stack
from test_images import raster, resolve

URL = "https://images.example.test/photo.png?private-ticket=not-for-logs"
KEY = f"private:{PEER}"


class Download:
    def __init__(self):
        self.calls = []

    async def fetch(self, url, permit):
        self.calls.append(url)
        return raster()


@pytest.mark.parametrize(
    "url",
    [
        "file:///D:/secret.png",
        "data:image/png;base64,abc",
        "base64://abc",
        "http://example.test/a.png",
        "https://user:password@example.test/a",
        "https://example.test:444/a",
        "https://example.test/a#fragment",
        "https://example.test/a\n",
        None,
    ],
)
def test_outgoing_urls_reject_paths_embedded_data_credentials_and_non_https(url):
    with pytest.raises(ValueError):
        public_image_url(url)


def test_public_image_download_checks_redirects_and_private_addresses():
    calls = []

    async def private(host):
        return "127.0.0.1"

    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(raster()))

    async def run():
        downloader = ImageDownloader(
            transport=httpx.MockTransport(handler), resolver=private, url_validator=public_image_url
        )
        with pytest.raises(ValueError, match="解析"):
            await downloader.fetch(URL, lambda: True)
        assert not calls

        async def redirected_host(host):
            return "127.0.0.1" if host == "localhost" else "8.8.8.8"

        def redirect(request):
            calls.append(request)
            return httpx.Response(302, headers={"location": "https://localhost/secret"})

        downloader = ImageDownloader(
            transport=httpx.MockTransport(redirect),
            resolver=redirected_host,
            url_validator=public_image_url,
        )
        with pytest.raises(ValueError, match="解析"):
            await downloader.fetch(URL, lambda: True)
        assert len(calls) == 1

        def invalid_redirect(request):
            return httpx.Response(302, headers={"location": "file:///D:/secret.png"})

        downloader = ImageDownloader(
            transport=httpx.MockTransport(invalid_redirect),
            resolver=resolve,
            url_validator=public_image_url,
        )
        with pytest.raises(ValueError, match="HTTPS"):
            await downloader.fetch(URL, lambda: True)

    asyncio.run(run())


def test_preview_then_next_model_response_sends_the_exact_same_bytes_only_once():
    downloader, sent = Download(), []

    async def send(args, prepared):
        sent.append(prepared)
        return {"sent": 1, "deduped": 0, "messageIds": ["-1"]}

    async def run():
        outgoing = OutgoingImages(lambda: True, send, downloader=downloader)
        with pytest.raises(ValueError, match="预览|查看图片"):
            await outgoing.execute({"url": URL})
        preview, parts = await outgoing.execute({"url": URL, "preview": True})
        assert preview["preview"] and len(parts) == 1 and not sent
        with pytest.raises(ValueError, match="查看图片"):
            await outgoing.execute({"url": URL})
        outgoing.confirm_previews()
        response, images = await outgoing.execute({"url": URL, "note": "这张图"})
        assert response["sent"] == 1 and not images and len(downloader.calls) == 1
        assert sent[0]["part"] == parts[0]
        data = base64.b64decode(parts[0]["image_url"]["url"].split(",", 1)[1])
        assert Image.open(io.BytesIO(data)).format == "JPEG" and len(data) <= 512 * 1024
        repeated, images = await outgoing.execute({"url": URL, "preview": True})
        assert repeated["count"] == 0 and not images and len(downloader.calls) == 1

    asyncio.run(run())


def test_preview_budget_includes_failures_and_send_budget_is_bounded():
    class Failed:
        async def fetch(self, *args):
            raise ValueError("下载失败")

    async def send(*args):
        return {"sent": 1, "messageIds": ["-1"], "deduped": 0}

    async def run():
        outgoing = OutgoingImages(lambda: True, send, downloader=Failed())
        for _ in range(3):
            with pytest.raises(ValueError, match="下载失败"):
                await outgoing.execute({"url": URL, "preview": True})
        with pytest.raises(ValueError, match="最多预览"):
            await outgoing.execute({"url": URL, "preview": True})
        outgoing = OutgoingImages(lambda: True, send, downloader=Download())
        await outgoing.execute({"url": URL, "preview": True})
        outgoing.confirm_previews()
        for _ in range(3):
            await outgoing.execute({"url": URL})
        with pytest.raises(ValueError, match="最多发送"):
            await outgoing.execute({"url": URL})

    asyncio.run(run())


@pytest.mark.parametrize(
    "extra", [{"chatKey": "private:87654321"}, {"preview": "true"}, {"note": "x" * 1001}]
)
def test_invalid_arguments_do_not_download_or_send(extra):
    download = Download()

    async def send(*args):
        pytest.fail("must not send")

    async def run():
        outgoing = OutgoingImages(lambda: True, send, downloader=download)
        with pytest.raises(ValueError):
            await outgoing.execute({"url": URL, "preview": True, **extra})
        assert not download.calls

    asyncio.run(run())


def call(args, call_id="image"):
    response = result("send_image")
    response["message"]["tool_calls"][0].update(id=call_id)
    response["message"]["tool_calls"][0]["function"]["arguments"] = json.dumps(args)
    return response


def enable_images(settings):
    settings.save(ACCOUNT, {"api": {"vision": True, "sendImages": True}})


def install_download(monkeypatch):
    calls = []

    async def fetch(self, url, permit):
        calls.append(url)
        return raster()

    monkeypatch.setattr(ImageDownloader, "fetch", fetch)
    return calls


def test_full_preview_send_acknowledgement_and_logs_have_no_image_bytes(stack, monkeypatch):
    service, receiver, sessions, settings, messages, connection, model = stack
    downloads = install_download(monkeypatch)
    enable_images(settings)
    model.responses = [
        call({"url": URL, "preview": True}, "preview"),
        call({"url": URL, "note": "这张图", "replyToMessageId": 1}, "send"),
        result("finish"),
    ]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "done")
    assert len(downloads) == 1 and len(connection.calls) == 1
    action, params = connection.calls[0]
    assert action == "send_private_msg" and params["user_id"] == PEER
    assert [s["type"] for s in params["message"]] == ["reply", "image", "text"]
    image = params["message"][1]["data"]["file"]
    assert image.startswith("base64://") and len(json.dumps(params).encode()) < 1024 * 1024
    assert model.media_calls[0][-1]["content"][-1]["image_url"]["url"].split(",", 1)[
        1
    ] == image.removeprefix("base64://")
    detail = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert detail["sent"][0]["type"] == "image" and detail["sent"][0]["messageId"] == "-1"
    serialized = json.dumps(detail) + json.dumps(messages.context(ACCOUNT, KEY))
    assert (
        "base64," not in serialized
        and "base64://" not in serialized
        and "private-ticket" not in serialized
    )
    assert "send_image" in [r.get("name") for r in detail["records"]]


def test_preview_and_send_in_one_tool_batch_cannot_skip_actual_model_review(stack, monkeypatch):
    service, receiver, sessions, settings, _, connection, model = stack
    install_download(monkeypatch)
    enable_images(settings)
    preview = call({"url": URL, "preview": True})
    preview["message"]["tool_calls"] += call({"url": URL}, "send")["message"]["tool_calls"]
    model.responses = [preview, result("finish")]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "noreply")
    assert not connection.calls
    detail = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert any(r.get("name") == "send_image" and r["isError"] for r in detail["records"])


@pytest.mark.parametrize("enabled", ["off", "vision-only", "send-only"])
def test_tool_unavailable_by_default_and_requires_both_image_settings(stack, monkeypatch, enabled):
    service, receiver, sessions, settings, _, connection, model = stack
    downloads = install_download(monkeypatch)
    settings.save(
        ACCOUNT, {"api": {"vision": enabled == "vision-only", "sendImages": enabled == "send-only"}}
    )
    model.responses = [call({"url": URL, "preview": True}), result("finish")]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "error")
    assert not downloads and not connection.calls


@pytest.mark.parametrize("stop", ["pause", "recall", "disconnect", "block", "switch"])
def test_stopping_during_download_prevents_followup_model_and_qq_send(stack, monkeypatch, stop):
    service, receiver, sessions, settings, messages, connection, model = stack
    entered, release = threading.Event(), threading.Event()

    async def fetch(self, url, permit):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return raster()

    monkeypatch.setattr(ImageDownloader, "fetch", fetch)
    enable_images(settings)
    model.responses = [call({"url": URL, "preview": True}), call({"url": URL}, "send")]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    assert entered.wait(2)
    if stop == "pause":
        service.pause()
    elif stop == "recall":
        messages.recall(ACCOUNT, KEY, 1)
    elif stop == "disconnect":
        connection.connected = False
    elif stop == "switch":
        connection.account = OTHER
    else:
        settings.save(ACCOUNT, {"blockedUsers": [PEER]})
    release.set()
    wait(lambda: service.status()["active"] == 0)
    assert (
        not connection.calls
        and len(model.calls) == 1
        and sessions.list(ACCOUNT)[0]["status"] == "aborted"
    )


def test_unknown_image_delivery_does_not_retry_or_use_another_route(stack, monkeypatch):
    service, receiver, sessions, settings, _, connection, model = stack
    install_download(monkeypatch)
    enable_images(settings)
    connection.error = EngineError("REQUEST_TIMEOUT", "uncertain")
    model.responses = [
        call({"url": URL, "preview": True}),
        call({"url": URL}, "send"),
        result("finish"),
    ]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "error")
    assert len(connection.calls) == 1 and len(model.calls) == 2
    assert not sessions.list(ACCOUNT)[0]["sent"] and "未确认" in sessions.list(ACCOUNT)[0]["reason"]


def test_repeated_image_is_deduped_after_success(stack, monkeypatch):
    service, receiver, sessions, settings, _, connection, model = stack
    install_download(monkeypatch)
    enable_images(settings)
    model.responses = [
        call({"url": URL, "preview": True}),
        call({"url": URL}, "send"),
        call({"url": URL, "note": "重复说明"}, "duplicate"),
        result("finish"),
    ]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "done")
    assert len(connection.calls) == 1 and len(sessions.list(ACCOUNT)[0]["sent"]) == 1
    detail = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert any(r.get("result", {}).get("deduped") == 1 for r in detail["records"])


def test_group_image_uses_current_group_and_validated_mention(stack, monkeypatch):
    service, receiver, sessions, settings, _, connection, model = stack
    install_download(monkeypatch)
    enable_images(settings)
    settings.save(ACCOUNT, {"groupTrigger": "all"})
    model.responses = [
        call({"url": URL, "preview": True}),
        call({"url": URL, "atUserId": PEER}, "send"),
        result("finish"),
    ]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet(kind="group"))
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "done")
    action, params = connection.calls[0]
    assert (
        action == "send_group_msg" and params["group_id"] == "99887766" and "user_id" not in params
    )
    assert params["message"][0] == {"type": "at", "data": {"qq": PEER}}


def test_image_cannot_quote_another_chat_message(stack, monkeypatch):
    service, receiver, sessions, settings, messages, connection, model = stack
    install_download(monkeypatch)
    enable_images(settings)
    messages.ingest(ACCOUNT, packet(77, kind="group"))
    model.responses = [
        call({"url": URL, "preview": True}),
        call({"url": URL, "replyToMessageId": 77}, "send"),
        result("finish"),
    ]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "noreply")
    assert not connection.calls


def test_disabling_image_send_while_waiting_for_native_queue_blocks_dispatch(stack, monkeypatch):
    service, receiver, sessions, settings, _, connection, model = stack
    install_download(monkeypatch)
    enable_images(settings)
    entered = threading.Event()
    original = service._sender.send_image

    def send(*args):
        entered.set()
        return original(*args)

    monkeypatch.setattr(service._sender, "send_image", send)
    model.responses = [call({"url": URL, "preview": True}), call({"url": URL}, "send")]
    service._native_lock.acquire()
    try:
        service.enable(ACCOUNT, True)
        receiver.receive(ACCOUNT, packet())
        assert entered.wait(2)
        settings.save(ACCOUNT, {"api": {"sendImages": False}})
    finally:
        service._native_lock.release()
    wait(lambda: service.status()["active"] == 0)
    assert not connection.calls and not sessions.list(ACCOUNT)[0]["sent"]


def test_pause_during_native_image_send_preserves_actual_success_receipt(stack, monkeypatch):
    service, receiver, sessions, settings, _, connection, model = stack
    install_download(monkeypatch)
    enable_images(settings)
    entered, release = threading.Event(), threading.Event()
    original = connection.invoke

    def send(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return original(*args, **kwargs)

    connection.invoke = send
    model.responses = [call({"url": URL, "preview": True}), call({"url": URL}, "send")]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet())
    assert entered.wait(2)
    service.pause()
    release.set()
    wait(lambda: service.status()["active"] == 0)
    item = sessions.list(ACCOUNT)[0]
    assert (
        item["status"] == "aborted"
        and item["sent"][0]["type"] == "image"
        and len(connection.calls) == 1
    )


def test_preview_cache_is_not_shared_between_model_runs():
    async def send(*args):
        pytest.fail("a different run must not reuse preview authorization")

    async def run():
        first = OutgoingImages(lambda: True, send, downloader=Download())
        await first.execute({"url": URL, "preview": True})
        first.confirm_previews()
        second = OutgoingImages(lambda: True, send, downloader=Download())
        with pytest.raises(ValueError, match="查看图片"):
            await second.execute({"url": URL})

    asyncio.run(run())


def test_settings_missing_api_fields_are_rejected(tmp_path):
    from qqbot.agent.config import DEFAULTS, SettingsStore
    from qqbot.storage.database import Database

    database = Database(tmp_path / "old-api.sqlite3")
    try:
        old = copy.deepcopy(DEFAULTS)
        old["api"].pop("sendImages")
        old["api"]["apiKey"] = "preserved-key"
        database.connection.execute("INSERT INTO settings VALUES(?,?)", (ACCOUNT, json.dumps(old)))
        database.connection.commit()
        settings = SettingsStore(database)
        with pytest.raises(ValueError, match="原数据已保留"):
            settings.read(ACCOUNT)
        with pytest.raises(ValueError):
            settings.save(ACCOUNT, {"api": {"sendImages": "yes"}})
    finally:
        database.close()
