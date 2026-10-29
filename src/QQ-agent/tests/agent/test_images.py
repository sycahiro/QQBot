import asyncio
import base64
import copy
import io
import json
import threading

import httpx
import pytest
from PIL import Image
from qqbot.agent.config import DEFAULTS, SettingsStore
from qqbot.agent.images import (
    ImageDownloader,
    ImageReader,
    image_url,
    prepare_image,
    public_address,
)
from qqbot.agent.llm import ChatClient, ModelError
from qqbot.storage.database import Database
from qqbot.storage.messages import MessageStore
from test_agent import ACCOUNT, OTHER, PEER, packet, result, wait
from test_agent import stack as stack

URL = "https://gchat.qpic.cn/test/image?rkey=private-ticket"
KEY = f"private:{PEER}"


def raster(fmt="PNG", size=(30, 20), **options):
    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, fmt, **options)
    return buffer.getvalue()


def image_packet(mid=1, **fields):
    return packet(
        mid, message=[{"type": "image", "data": {"file": "native-file", "url": URL}}], **fields
    )


async def resolve(_):
    return "8.8.8.8"


@pytest.mark.parametrize(
    "url",
    [
        "file:///D:/private.jpg",
        "http://127.0.0.1/a",
        "https://qpic.cn.evil.test/a",
        "https://evilqpic.cn/a",
        "https://gchat.qpic.cn@localhost/a",
        "https://user:secret@gchat.qpic.cn/a",
        "https://gchat.qpic.cn:444/a",
        "data:image/png;base64,a",
        "https://gchat.qpic.cn/a\n",
        "https://gchat.qpic.cn/a#fragment",
        "https://multimedia.nt.qq.com.cn.evil.test/download",
        "https://evil.multimedia.nt.qq.com.cn/download",
        "https://multimedia.nt.qq.com.cn@localhost/download",
        "https://multimedia.nt.qq.com.cn:444/download",
    ],
)
def test_image_source_rejects_paths_arbitrary_hosts_and_credentials(url):
    with pytest.raises(ValueError):
        image_url(url)


def test_legacy_http_is_upgraded_and_qq_subdomain_is_kept():
    assert image_url("http://gchat.qpic.cn:80/a?x=y") == "https://gchat.qpic.cn/a?x=y"
    assert (
        image_url("http://multimedia.nt.qq.com.cn/download?fileid=test")
        == "https://multimedia.nt.qq.com.cn/download?fileid=test"
    )
    assert (
        image_url("https://multimedia.nt.qq.com/download")
        == "https://multimedia.nt.qq.com/download"
    )


def test_dns_checks_all_results_including_private_ipv6(monkeypatch):
    async def run():
        async def lookup(*args, **kwargs):
            return [(2, 1, 6, "", ("8.8.8.8", 443)), (10, 1, 6, "", ("::1", 443))]

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
        with pytest.raises(ValueError, match="解析"):
            await public_address("gchat.qpic.cn")

    asyncio.run(run())


def test_downloader_pins_ip_keeps_tls_hostname_and_no_credentials():
    data = raster()

    def handler(request):
        assert request.url.host == "8.8.8.8"
        assert request.headers["host"] == request.extensions["sni_hostname"] == "gchat.qpic.cn"
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(200, stream=httpx.ByteStream(data))

    assert (
        asyncio.run(
            ImageDownloader(transport=httpx.MockTransport(handler), resolver=resolve).fetch(
                URL, lambda: True
            )
        )
        == data
    )


@pytest.mark.parametrize(
    "destination", ["https://localhost/a", "http://127.0.0.1/a", "https://example.com/a"]
)
def test_redirects_cannot_escape_qq_cdns(destination):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": destination})

    with pytest.raises(ValueError):
        asyncio.run(
            ImageDownloader(transport=httpx.MockTransport(handler), resolver=resolve).fetch(
                URL, lambda: True
            )
        )
    assert len(calls) == 1


@pytest.mark.parametrize("mode", ["header", "stream", "encoding", "status", "empty"])
def test_download_bounds_and_errors_do_not_expose_ticket(mode, monkeypatch):
    monkeypatch.setattr("qqbot.agent.images.MAX_DOWNLOAD", 20)

    def handler(request):
        return httpx.Response(
            403 if mode == "status" else 200,
            headers={"content-length": "100"}
            if mode == "header"
            else {"content-encoding": "gzip"}
            if mode == "encoding"
            else {},
            stream=httpx.ByteStream(b"" if mode == "empty" else b"x" * 21),
        )

    with pytest.raises(ValueError) as error:
        asyncio.run(
            ImageDownloader(transport=httpx.MockTransport(handler), resolver=resolve).fetch(
                URL, lambda: True
            )
        )
    assert "private-ticket" not in str(error.value) and URL not in str(error.value)


def test_pause_prevents_download_and_cancels_stream():
    calls = []
    transport = httpx.MockTransport(
        lambda request: (
            calls.append(request) or httpx.Response(200, stream=httpx.ByteStream(raster()))
        )
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            ImageDownloader(transport=transport, resolver=resolve).fetch(URL, lambda: False)
        )
    assert not calls


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "GIF"])
def test_raster_formats_are_resized_and_metadata_removed(fmt):
    prepared = prepare_image(raster(fmt, size=(2000, 40)))
    assert prepared["info"]["width"] == 1568 and prepared["info"]["bytes"] <= 512 * 1024
    decoded = base64.b64decode(prepared["part"]["image_url"]["url"].split(",")[1])
    with Image.open(io.BytesIO(decoded)) as image:
        assert image.format == "JPEG" and not image.getexif()


def test_gif_only_first_frame_and_corruption_pixel_limit(monkeypatch):
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(
        buffer, "GIF", save_all=True, append_images=[Image.new("RGB", (10, 10), "blue")]
    )
    assert prepare_image(buffer.getvalue())["info"]["firstFrame"]
    with pytest.raises(ValueError):
        prepare_image(b"<svg><script>test</script></svg>")
    monkeypatch.setattr("qqbot.agent.images.MAX_PIXELS", 100)
    with pytest.raises(ValueError, match="像素"):
        prepare_image(raster())


@pytest.fixture
def reader(tmp_path):
    database = Database(tmp_path / "images.sqlite3")
    store = MessageStore(database)
    store.ingest(ACCOUNT, image_packet())
    calls, tracked = [], []

    async def native(account, key, mid):
        calls.append((account, key, mid))
        return {"status": "ok", "data": image_packet()}

    class Downloader:
        async def fetch(self, url, permit):
            assert url == URL
            return raster()

    instance = ImageReader(store, native, tracked.append, lambda: True, downloader=Downloader())
    yield instance, store, calls, tracked
    database.close()


def test_scoped_read_and_repeated_tool_call_has_no_second_fetch(reader):
    instance, store, calls, tracked = reader
    metadata, parts = asyncio.run(instance.read(ACCOUNT, KEY, {"messageId": 1}))
    assert metadata["count"] == len(parts) == len(calls) == 1
    assert "base64" not in json.dumps(metadata) and URL not in json.dumps(metadata)
    assert asyncio.run(instance.read(ACCOUNT, KEY, {"messageId": 1}))[0]["count"] == 0
    assert len(calls) == 1
    for account, key in [(OTHER, KEY), (ACCOUNT, f"private:{OTHER}")]:
        with pytest.raises(ValueError):
            asyncio.run(instance.read(account, key, {"messageId": 1}))
    store.recall(ACCOUNT, KEY, 1)
    with pytest.raises(ValueError):
        asyncio.run(instance.read(ACCOUNT, KEY, {"messageId": 1}))


def test_upstream_nt_download_host_survives_native_refresh_and_pinned_download(reader):
    instance, _, _, _ = reader
    fresh = "https://multimedia.nt.qq.com.cn/download?fileid=synthetic&rkey=synthetic-ticket"

    async def native(*args):
        data = image_packet()
        data["message"][0]["data"]["url"] = fresh
        return {"status": "ok", "data": data}

    requests = []

    def download(request):
        requests.append(request)
        assert request.url.host == "8.8.8.8"
        assert (
            request.headers["host"]
            == request.extensions["sni_hostname"]
            == "multimedia.nt.qq.com.cn"
        )
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(200, stream=httpx.ByteStream(raster()))

    instance._native = native
    instance._downloader = ImageDownloader(
        transport=httpx.MockTransport(download), resolver=resolve
    )
    metadata, parts = asyncio.run(instance.read(ACCOUNT, KEY, {"messageId": 1}))
    assert len(requests) == metadata["count"] == len(parts) == 1
    assert parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "synthetic-ticket" not in json.dumps(metadata)


@pytest.mark.parametrize(
    "fields",
    [{"user_id": OTHER}, {"message_id": 999}, {"message_type": "group"}, {"self_id": OTHER}],
)
def test_native_refresh_must_match_chat_message_sender_and_account(reader, fields):
    instance, _, _, _ = reader

    async def wrong(*args):
        return {"status": "ok", "data": image_packet() | fields}

    instance._native = wrong
    with pytest.raises(ValueError, match="不一致"):
        asyncio.run(instance.read(ACCOUNT, KEY, {"messageId": 1}))


def test_native_omits_self_id_as_upstream_does(reader):
    instance, _, _, _ = reader

    async def native(*args):
        data = image_packet()
        data.pop("self_id")
        data.pop("post_type")
        return {"status": "ok", "data": data}

    instance._native = native
    assert asyncio.run(instance.read(ACCOUNT, KEY, {"messageId": 1}))[0]["count"] == 1


def test_duplicate_mid_and_sequence_mismatch_are_rejected(reader):
    instance, store, _, _ = reader
    store.ingest(ACCOUNT, image_packet(message_seq=55))
    with pytest.raises(ValueError, match="歧义"):
        asyncio.run(instance.read(ACCOUNT, KEY, {"messageId": 1}))
    store.delete(ACCOUNT, KEY)
    store.ingest(ACCOUNT, image_packet(message_seq=55))
    with pytest.raises(ValueError, match="不一致"):
        asyncio.run(instance.read(ACCOUNT, KEY, {"messageId": 1}))


def test_per_run_budget_includes_many_images_and_calls(reader):
    instance, store, _, _ = reader
    store.ingest(ACCOUNT, packet(2, message=[{"type": "image", "data": {"url": URL}}] * 6))

    async def native(*args):
        return {
            "status": "ok",
            "data": packet(2, message=[{"type": "image", "data": {"url": URL}}] * 6),
        }

    instance._native = native
    info, parts = asyncio.run(instance.read(ACCOUNT, KEY, {"messageId": 2}))
    assert info["count"] == len(parts) == 4 and info["omitted"] == 2
    with pytest.raises(ValueError, match="最多"):
        asyncio.run(instance.read(ACCOUNT, KEY, {"messageId": 1}))


@pytest.mark.parametrize("response", [None, {}, {"status": "failed"}])
def test_failed_native_refresh_never_uses_stored_image_url(reader, response):
    instance, _, _, _ = reader

    async def native(*args):
        return response

    class Download:
        async def fetch(self, *args):
            pytest.fail("Failed identity refresh must not download using an older URL")

    instance._native = native
    instance._downloader = Download()
    with pytest.raises(ValueError, match="刷新失败"):
        asyncio.run(instance.read(ACCOUNT, KEY, {"messageId": 1}))


def test_saved_settings_preserve_credentials_and_reject_bad_flags(tmp_path):
    db = Database(tmp_path / "settings.sqlite3")
    try:
        old = copy.deepcopy(DEFAULTS)
        old["api"]["apiKey"] = "saved-secret"
        with db.lock, db.connection as connection:
            connection.execute("INSERT INTO settings VALUES(?,?)", (ACCOUNT, json.dumps(old)))
        store = SettingsStore(db)
        assert store.read(ACCOUNT)["api"]["apiKey"] == "saved-secret"
        assert store.read(ACCOUNT)["api"]["vision"] is False
        store.save(ACCOUNT, {"api": {"vision": True, "visionModel": "vision-test"}})
        public = store.read(ACCOUNT, public=True)["api"]
        assert (
            public["vision"] is True
            and public["visionModel"] == "vision-test"
            and "apiKey" not in public
        )
        assert store.read(ACCOUNT)["api"]["apiKey"] == "saved-secret"
        with pytest.raises(ValueError):
            store.save(ACCOUNT, {"api": {"vision": "yes"}})
    finally:
        db.close()

def test_vision_model_only_used_when_actual_images_are_present():
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = ChatClient(transport=httpx.MockTransport(handler))
    api = copy.deepcopy(DEFAULTS["api"]) | {
        "baseUrl": "https://model.test/v1",
        "model": "text-model",
        "vision": True,
        "visionModel": "image-model",
    }
    plain = [{"role": "user", "content": "[图片]"}]
    multimodal = [{"role": "user", "content": [prepare_image(raster())["part"]]}]
    asyncio.run(client.complete(api, plain, []))
    response = asyncio.run(client.complete(api, multimodal, []))
    assert [c["model"] for c in calls] == ["text-model", "image-model"] and response[
        "model"
    ] == "image-model"
    api["vision"] = False
    with pytest.raises(ModelError, match="关闭"):
        asyncio.run(client.complete(api, multimodal, []))
    assert len(calls) == 2


def image_tool_response():
    response = result("get_recent_messages", "get_message_images")
    response["message"]["tool_calls"][0]["function"]["arguments"] = "{}"
    response["message"]["tool_calls"][1]["function"]["arguments"] = '{"messageId":1}'
    return response


def install_native_images(connection):
    original = connection.invoke

    def invoke(action, params, *, expected_account=None):
        if action == "get_msg":
            assert expected_account == ACCOUNT
            connection.calls.append((action, params))
            return {"status": "ok", "data": image_packet()}
        return original(action, params, expected_account=expected_account)

    connection.invoke = invoke


def test_image_tool_sequence_real_image_parts_and_log_has_no_binary(stack, monkeypatch):
    service, receiver, sessions, settings, _, connection, model = stack

    async def fetch(self, url, permit):
        return raster()

    monkeypatch.setattr(ImageDownloader, "fetch", fetch)
    settings.save(ACCOUNT, {"api": {"vision": True}})
    install_native_images(connection)
    model.responses = [image_tool_response(), result("send_message", "finish")]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, image_packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "done")
    followup = model.calls[1]
    assert [m["role"] for m in followup[-3:]] == ["assistant", "tool", "tool"]
    assert any(p.get("type") == "image_url" for p in model.media_calls[0][-1]["content"])
    assert "understanding" in followup[-1]["content"]
    assert "base64," not in json.dumps(followup) and URL not in json.dumps(followup)
    detail = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert len(detail["records"][0]["messages"]) == 2  # No alias with the live tool loop.
    assert "base64," not in json.dumps(detail) and "private-ticket" not in json.dumps(detail)
    assert [name for name, _ in connection.calls] == ["get_msg", "send_private_msg"]


def test_media_model_failure_skips_understanding_and_continues(stack, monkeypatch):
    service, receiver, sessions, settings, _, connection, model = stack
    original = model.complete

    async def fetch(self, url, permit):
        return raster()

    async def failing_complete(api, messages, tools):
        if not tools and any(isinstance(m.get("content"), list) for m in messages):
            raise ModelError("模型请求超时，本轮已停止")
        return await original(api, messages, tools)

    monkeypatch.setattr(ImageDownloader, "fetch", fetch)
    monkeypatch.setattr(model, "complete", failing_complete)
    settings.save(ACCOUNT, {"api": {"vision": True}})
    install_native_images(connection)
    model.responses = [image_tool_response(), result("send_message", "finish")]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, image_packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "done")
    assert sessions.list(ACCOUNT)[0]["status"] == "done"
    assert "understandingFailed" in model.calls[1][-1]["content"]
    assert "识图模型超时或请求失败" in model.calls[1][-1]["content"]
    detail = json.dumps(sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"]), ensure_ascii=False)
    assert "已跳过图片理解" in detail
    assert [name for name, _ in connection.calls] == ["get_msg", "send_private_msg"]


def test_disabled_image_tool_cannot_fetch_even_if_model_calls_it(stack):
    service, receiver, sessions, _, _, connection, model = stack
    model.responses = [image_tool_response(), result("finish")]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, image_packet())
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "error")
    assert not connection.calls
    detail = sessions.get(ACCOUNT, sessions.list(ACCOUNT)[0]["id"])
    assert "未提供" in detail["reason"] and len(model.calls) == 1


@pytest.mark.parametrize("stop", ["pause", "recall", "block"])
def test_stop_during_image_download_prevents_followup_model_and_send(stack, monkeypatch, stop):
    service, receiver, sessions, settings, messages, connection, model = stack
    entered, release = threading.Event(), threading.Event()

    async def fetch(self, url, permit):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return raster()

    monkeypatch.setattr(ImageDownloader, "fetch", fetch)
    settings.save(ACCOUNT, {"api": {"vision": True}})
    install_native_images(connection)
    model.responses = [image_tool_response(), result("send_message")]
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, image_packet())
    assert entered.wait(2)
    if stop == "pause":
        service.pause()
    elif stop == "recall":
        messages.recall(ACCOUNT, KEY, 1)
    else:
        settings.save(ACCOUNT, {"blockedUsers": [PEER]})
    release.set()
    wait(lambda: service.status()["active"] == 0)
    assert len(model.calls) == 1 and [name for name, _ in connection.calls] == ["get_msg"]
    assert sessions.list(ACCOUNT)[0]["status"] == "aborted"


def test_withdrawn_historical_image_invalidates_reply_even_when_trigger_still_exists(
    stack, monkeypatch
):
    service, receiver, sessions, settings, messages, connection, _ = stack

    async def fetch(self, url, permit):
        return raster()

    monkeypatch.setattr(ImageDownloader, "fetch", fetch)
    entered, release = threading.Event(), threading.Event()

    class DelayedModel:
        count = 0

        async def complete(self, *args):
            self.count += 1
            if self.count == 1:
                return image_tool_response()
            entered.set()
            while not release.is_set():
                await asyncio.sleep(0.01)
            return result("send_message")

    settings.save(ACCOUNT, {"api": {"vision": True}})
    install_native_images(connection)
    messages.ingest(ACCOUNT, image_packet())
    service._model = DelayedModel()
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, packet(2))
    assert entered.wait(2)
    messages.recall(ACCOUNT, KEY, 1)
    release.set()
    wait(lambda: service.status()["active"] == 0)
    assert messages.has_mid(ACCOUNT, KEY, 2) and sessions.list(ACCOUNT)[0]["status"] == "aborted"
    assert [name for name, _ in connection.calls] == ["get_msg"]


def test_native_image_read_and_other_chat_send_share_queue(stack, monkeypatch):
    service, receiver, sessions, settings, _, connection, _ = stack
    entered, release = threading.Event(), threading.Event()
    reading = threading.Event()

    async def fetch(self, url, permit):
        return raster()

    monkeypatch.setattr(ImageDownloader, "fetch", fetch)

    class BothChats:
        private_calls = 0

        async def complete(self, api, messages, tools):
            if not tools:
                return result(content="测试画面")
            if "【当前聊天】group:" in messages[1]["content"]:
                return result("send_message", "finish")
            self.private_calls += 1
            return image_tool_response() if self.private_calls == 1 else result("finish")

    original = connection.invoke

    def invoke(action, params, *, expected_account=None):
        if action == "get_msg":
            reading.set()
            entered.set()
            assert release.wait(2)
            connection.calls.append((action, params))
            reading.clear()
            return {"status": "ok", "data": image_packet()}
        assert not reading.is_set(), "send must wait for the native image read"
        return original(action, params, expected_account=expected_account)

    connection.invoke = invoke
    service._model = BothChats()
    settings.save(ACCOUNT, {"api": {"vision": True}, "groupTrigger": "all"})
    service.enable(ACCOUNT, True)
    receiver.receive(ACCOUNT, image_packet())
    assert entered.wait(2)
    receiver.receive(ACCOUNT, packet(2, kind="group"))
    wait(lambda: len(sessions.list(ACCOUNT)) == 2)
    release.set()
    wait(lambda: service.status()["active"] == 0)
    assert [name for name, _ in connection.calls] == ["get_msg", "send_group_msg"]
    assert not any(s["status"] == "error" for s in sessions.list(ACCOUNT))
