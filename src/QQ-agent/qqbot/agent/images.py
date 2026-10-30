"""QQ Agent get_message_images 的图片子集：按消息读取、刷新 URL、限量压缩。

工具结果保持文本，图片另作为 user 多模态输入（与原 orchestrator.js 一致）。
不接收模型提供的 URL/路径，不落盘；动图只读第一帧，不解析后续帧。
"""

import asyncio
import base64
import io
import ipaddress
import socket
import warnings
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from ..storage.messages import numeric_id

MAX_DOWNLOAD = 8 * 1024 * 1024
MAX_IMAGE = 512 * 1024
MAX_PIXELS = 25_000_000
MAX_IMAGES = 4  # Per model run, including repeated tool calls.
MAX_DIMENSION = 1568  # Original image-compress.js default.


def image_url(raw):
    """Only native QQ image CDNs; every redirect must pass this same check."""
    if not isinstance(raw, str) or len(raw) > 8192 or any(ord(c) < 33 for c in raw):
        raise ValueError("图片没有可用的 QQ 下载地址")
    try:
        url = urlsplit(raw)
        host = (url.hostname or "").lower()
        trusted = host in ("multimedia.nt.qq.com.cn", "multimedia.nt.qq.com") or any(
            host == suffix or host.endswith("." + suffix) for suffix in ("qpic.cn", "qlogo.cn")
        )
        if (
            url.scheme not in ("http", "https")
            or not trusted
            or url.username
            or url.password
            or url.fragment
            or url.port not in (None, 80 if url.scheme == "http" else 443)
        ):
            raise ValueError()
    except ValueError as error:
        raise ValueError("QQ 图片下载地址暂不受支持，图片尚未提交给识图模型") from error
    # Old QQ image events sometimes contain HTTP URLs. Fetch with TLS, never
    # downgrade or forward cookies / the model API credential to the CDN.
    return urlunsplit(("https", host, url.path or "/", url.query, ""))


async def public_address(host):
    async with asyncio.timeout(5):
        results = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(row[4][0] for row in results))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError("图片地址解析异常，已停止读取")
    return addresses[0]


class ImageDownloader:
    def __init__(
        self,
        *,
        transport=None,
        resolver=public_address,
        url_validator=image_url,
        max_download=None,
        label="图片",
    ):
        self._transport, self._resolver, self._validate = transport, resolver, url_validator
        self._max_download, self._label = max_download, label

    async def fetch(self, raw, permit):
        maximum = self._max_download if self._max_download is not None else MAX_DOWNLOAD
        try:
            async with asyncio.timeout(25):
                current = self._validate(raw)
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=10,
                    follow_redirects=False,
                    trust_env=False,
                    limits=httpx.Limits(max_keepalive_connections=0, max_connections=1),
                ) as client:
                    for _ in range(4):
                        if not permit():
                            raise asyncio.CancelledError()
                        host = urlsplit(current).hostname
                        ip = await self._resolver(host)
                        if not ipaddress.ip_address(ip).is_global:
                            raise ValueError("图片地址解析异常，已停止读取")
                        # Pin the checked IP while retaining Host and verified
                        # TLS SNI. httpcore's sni_hostname extension verifies the
                        # CDN hostname, not its numeric address. No second DNS.
                        pinned = httpx.URL(current).copy_with(host=ip)
                        async with client.stream(
                            "GET",
                            pinned,
                            headers={"host": host, "accept-encoding": "identity"},
                            extensions={"sni_hostname": host},
                        ) as response:
                            if response.status_code in (301, 302, 303, 307, 308):
                                location = response.headers.get("location")
                                if not location:
                                    raise ValueError("图片重定向地址缺失")
                                current = self._validate(urljoin(current, location))
                                continue
                            if response.status_code != 200:
                                raise ValueError(
                                    f"QQ {self._label}下载失败（HTTP {response.status_code}）"
                                )
                            if (
                                response.headers.get("content-encoding", "identity").lower()
                                != "identity"
                            ):
                                raise ValueError(f"QQ {self._label}返回了不支持的传输格式")
                            size = response.headers.get("content-length")
                            if size and (not size.isdigit() or int(size) > maximum):
                                raise ValueError(
                                    f"{self._label}超过 {maximum // 1024 // 1024} MB 下载上限"
                                )
                            data = bytearray()
                            async for chunk in response.aiter_raw():
                                if not permit():
                                    raise asyncio.CancelledError()
                                data.extend(chunk)
                                if len(data) > maximum:
                                    raise ValueError(
                                        f"{self._label}超过 {maximum // 1024 // 1024} MB 下载上限"
                                    )
                            if not data:
                                raise ValueError(f"QQ {self._label}内容为空")
                            return bytes(data)
                    raise ValueError("图片重定向次数过多")
        except (httpx.HTTPError, OSError, TimeoutError) as error:
            # HTTP errors can include a private rkey URL; expose no raw error.
            raise ValueError(f"{self._label}下载失败或超时，请重新发送后再试") from error


def prepare_image(data):
    """Decode supported raster bytes, bound pixels, strip metadata and shrink."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP", "GIF"]) as original:
                if original.width * original.height > MAX_PIXELS:
                    raise ValueError("图片像素超过 2500 万上限")
                animated = bool(getattr(original, "is_animated", False))
                original.seek(0)
                image = ImageOps.exif_transpose(original)
                image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
                # Flatten transparency on white, remove EXIF/GPS/text metadata.
                rgba = image.convert("RGBA")
                clean = Image.new("RGB", rgba.size, "white")
                clean.paste(rgba, mask=rgba.getchannel("A"))
                for quality in (85, 70, 55):
                    output = io.BytesIO()
                    clean.save(output, "JPEG", quality=quality)
                    if output.tell() <= MAX_IMAGE:
                        payload = output.getvalue()
                        return {
                            "part": {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/jpeg;base64,"
                                    + base64.b64encode(payload).decode("ascii")
                                },
                            },
                            "info": {
                                "width": clean.width,
                                "height": clean.height,
                                "bytes": len(payload),
                                "firstFrame": animated,
                            },
                        }
                raise ValueError("图片压缩后仍超过 512 KB 上限，请发送较小的图片")
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise ValueError("图片损坏或格式不支持；支持 JPEG、PNG、WebP 和 GIF 首帧") from error


class ImageReader:
    """One run owns its image budget and byte buffers; logs contain only info."""

    def __init__(
        self, store, native_read, track, permit, *, downloader=None, max_images=MAX_IMAGES
    ):
        self._store, self._native, self._track, self._permit = store, native_read, track, permit
        self._downloader = downloader or ImageDownloader()
        self._max_images = min(MAX_IMAGES, max(1, max_images))
        self._used = 0
        self._seen = set()
        self._prepared = {}

    def prepared_ids(self):
        return set(self._prepared)

    def prepared(self, account, key, mid):
        item = self._store.image_message(account, key, mid)
        if not self._permit():
            raise asyncio.CancelledError()
        prepared = self._prepared.get(item["id"])
        if prepared is None:
            raise ValueError("请先调用 get_message_images 看图，并在下一次模型回应后再收藏")
        return item, prepared

    async def read(self, account, key, args):
        if set(args) != {"messageId"}:
            raise ValueError(
                "参数缺少 messageId：从当前聊天记录里找到图片消息前的 #数字编号，"
                '以 {"messageId": "#编号"} 重新调用，一次只看一条消息的图片'
            )
        if numeric_id(args.get("messageId")) is None:
            raise ValueError(
                "messageId 必须是当前聊天记录里图片消息的 #数字编号，不要编造或使用其他聊天的编号"
            )
        item = self._store.image_message(account, key, args["messageId"])
        if not self._permit():
            raise asyncio.CancelledError()
        segments = item["segments"]
        images = (
            [
                s
                for s in segments
                if isinstance(s, dict)
                and s.get("type") == "image"
                and isinstance(s.get("data"), dict)
            ]
            if isinstance(segments, list)
            else []
        )
        if not images:
            return {"messageId": item["mid"], "count": 0, "message": "这条消息没有可读取的图片"}, []
        if item["id"] in self._seen:
            return {
                "messageId": item["mid"],
                "count": 0,
                "message": "这条消息的图片已提供，请使用前面的图片输入",
            }, []
        if self._used >= self._max_images:
            raise ValueError(f"每次处理最多查看 {self._max_images} 张图片")
        self._track(item)
        if not self._permit():
            raise asyncio.CancelledError()
        # get_msg is the upstream URL refresh path; validate the returned peer,
        # sender, sequence and message ID before accepting refreshed segments.
        response = await self._native(account, key, item["mid"])
        if not self._permit():
            raise asyncio.CancelledError()
        if not isinstance(response, dict) or response.get("status") != "ok":
            raise ValueError("QQ 图片地址刷新失败，未使用旧地址；请确认连接后重新发送图片")
        if response.get("status") == "ok":
            native = response.get("data")
            kind, peer = key.split(":")
            if not isinstance(native, dict):
                raise ValueError("QQ 图片消息返回格式错误")
            native_peer = (
                native.get("group_id")
                if kind == "group"
                else native.get("target_id")
                if item["self"]
                else native.get("user_id")
            )
            if (
                native.get("message_type") != kind
                or str(native_peer) != peer
                or numeric_id(native.get("message_id", native.get("real_id"))) != item["mid"]
                or str(native.get("user_id")) != item["senderId"]
                or ("self_id" in native and str(native["self_id"]) != account)
                or (item["sequence"] and numeric_id(native.get("message_seq")) != item["sequence"])
            ):
                raise ValueError("QQ 返回的图片消息与当前聊天不一致，已停止读取")
            refreshed = native.get("message")
            if not isinstance(refreshed, list):
                raise ValueError("QQ 图片消息返回格式错误")
            images = [
                s
                for s in refreshed
                if isinstance(s, dict)
                and s.get("type") == "image"
                and isinstance(s.get("data"), dict)
            ]
        parts, info, failures = [], [], []
        selected = images[: self._max_images - self._used]
        for segment in selected:
            self._used += 1  # Failed downloads also consume budget.
            try:
                data = await self._downloader.fetch(segment["data"].get("url"), self._permit)
                if not self._permit():
                    raise asyncio.CancelledError()
                prepared = await asyncio.to_thread(prepare_image, data)
                if not self._permit():
                    raise asyncio.CancelledError()
                parts.append(prepared["part"])
                info.append(prepared["info"])
                if item["id"] not in self._prepared:
                    self._prepared[item["id"]] = prepared
            except ValueError as error:
                failures.append(str(error))
        if not self._permit():
            raise asyncio.CancelledError()
        if not parts:
            raise ValueError(failures[0] if failures else "这条消息的图片已失效，请重新发送")
        self._seen.add(item["id"])
        return {
            "messageId": item["mid"],
            "count": len(parts),
            "images": info,
            "failed": len(failures),
            "warnings": failures,
            "omitted": max(0, len(images) - len(selected)),
            "note": "动图只提供第一帧；请根据实际图片回答",
        }, parts
