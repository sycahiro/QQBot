"""移植 send_image：限量下载 → 真实图片预览 → 当前聊天发送。

图片只在本轮内存中保存；发送与预览使用同一份压缩字节，避免二次下载换图。
"""

import asyncio
from urllib.parse import urlsplit

import httpx

from .images import ImageDownloader, prepare_image

MAX_PREVIEWS, MAX_SENDS = 3, 3


def public_image_url(raw):
    if not isinstance(raw, str) or not 1 <= len(raw) <= 8192 or any(ord(c) < 33 for c in raw):
        raise ValueError("请提供 HTTPS 图片直链，不支持本地文件或内嵌图片")
    try:
        parsed = urlsplit(raw)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.port not in (None, 443)
        ):
            raise ValueError()
        return str(httpx.URL(raw))
    except (ValueError, httpx.InvalidURL) as error:
        raise ValueError("仅支持标准 HTTPS 图片直链，不支持本地文件或内嵌图片") from error


class OutgoingImages:
    def __init__(self, permit, send, *, downloader=None):
        self._permit, self._send = permit, send
        self._downloader = downloader or ImageDownloader(url_validator=public_image_url)
        self._cache, self._previews, self._sends = {}, 0, 0

    def confirm_previews(self):
        # Called only after a subsequent model response. A parallel tool batch
        # cannot preview and send before the model has received the actual image.
        for image in self._cache.values():
            image["reviewed"] = True

    async def execute(self, args):
        if set(args) - {"url", "preview", "note", "replyToMessageId", "atUserId"}:
            raise ValueError("图片发送仅支持当前聊天，不接受跨会话或未知参数")
        if type(args.get("preview", False)) is not bool:
            raise ValueError("preview 必须为布尔值")
        if not isinstance(args.get("note", ""), str) or len(args.get("note", "")) > 1000:
            raise ValueError("图片说明不能超过 1000 字")
        url = public_image_url(args.get("url"))
        if not self._permit():
            raise asyncio.CancelledError()
        if args.get("preview", False):
            if url in self._cache:
                return {
                    "preview": True,
                    "count": 0,
                    "message": "此图片已提供，请使用前面的图片输入",
                }, []
            if self._previews >= MAX_PREVIEWS:
                raise ValueError("每次处理最多预览 3 张待发送图片")
            self._previews += 1  # Failed downloads consume budget too.
            data = await self._downloader.fetch(url, self._permit)
            if not self._permit():
                raise asyncio.CancelledError()
            prepared = await asyncio.to_thread(prepare_image, data)
            if not self._permit():
                raise asyncio.CancelledError()
            prepared["reviewed"] = False
            self._cache[url] = prepared
            return {
                "preview": True,
                "count": 1,
                "image": prepared["info"],
                "message": "已提供实际待发送图片；确认合适后另一次调用 send_image，preview=false。动图只发送第一帧。",
            }, [prepared["part"]]
        prepared = self._cache.get(url)
        if prepared is None or not prepared["reviewed"]:
            raise ValueError("请先用 preview=true 查看图片，收到图片输入并确认合适后再发送")
        if self._sends >= MAX_SENDS:
            raise ValueError("每次处理最多发送 3 张图片")
        if not self._permit():
            raise asyncio.CancelledError()
        result = await self._send(args, prepared)
        self._sends += result["sent"]
        return {**result, "preview": False}, []
