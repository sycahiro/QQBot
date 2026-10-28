"""复用 QQ Agent market.js 的公开目录地址，只读取元数据，不含登录、下载和执行能力。"""

import json
import threading
import time
import zlib

import httpx

MARKET_API = "https://www.kondius.cn/api/community"
# 官方市场只有「插件 / Skill」两张列表页，没有单条条目的详情路由，
# 所以所有跳转都固定落在对应类型的列表页上。
MARKET_PAGES = {
    "plugin": "https://www.kondius.cn/qq-agent/plugin-market/",
    "skill": "https://www.kondius.cn/qq-agent/skill-market/",
}


def page_url(kind):
    if kind not in MARKET_PAGES:
        raise ValueError("未知的扩展类型")
    return MARKET_PAGES[kind]


class MarketCatalog:
    def __init__(self, *, transport=None):
        self._transport = transport
        self._lock, self._cache = threading.Lock(), {}

    def read(self, kind):
        if kind not in ("plugin", "skill"):
            raise ValueError("未知的扩展类型")
        if not self._lock.acquire(blocking=False):
            raise ValueError("市场目录正在读取，请稍候")
        try:
            cached = self._cache.get(kind)
            if cached and time.monotonic() - cached[0] < 300:
                return cached[1]
            try:
                with httpx.Client(
                    timeout=15,
                    follow_redirects=False,
                    transport=self._transport,
                    headers={"accept-encoding": "gzip, deflate"},
                ) as client:
                    with client.stream(
                        "GET", MARKET_API + ("/plugins" if kind == "plugin" else "/skills")
                    ) as response:
                        if response.status_code != 200:
                            raise ValueError(
                                f"市场暂时无法访问（HTTP {response.status_code}），请稍后重试"
                            )
                        payload = bytearray()
                        downloaded = 0
                        deadline = time.monotonic() + 15
                        encoding = response.headers.get("content-encoding", "identity").lower()
                        if encoding not in ("identity", "gzip", "deflate"):
                            raise ValueError("市场目录的传输编码不支持")
                        decoder = (
                            None
                            if response.is_stream_consumed or encoding == "identity"
                            else zlib.decompressobj(
                                16 + zlib.MAX_WBITS if encoding == "gzip" else zlib.MAX_WBITS
                            )
                        )
                        chunks = (
                            (response.content,)
                            if response.is_stream_consumed
                            else response.iter_raw()
                        )
                        for chunk in chunks:
                            downloaded += len(chunk)
                            if downloaded > 2 * 1024 * 1024 or time.monotonic() > deadline:
                                raise ValueError("市场目录超出大小或读取时间限制")
                            # iter_bytes can inflate one compressed chunk without
                            # a limit before our size check gets control again.
                            try:
                                piece = (
                                    decoder.decompress(chunk, 2 * 1024 * 1024 + 1 - len(payload))
                                    if decoder
                                    else chunk
                                )
                            except zlib.error as error:
                                raise ValueError("市场目录压缩内容损坏") from error
                            payload.extend(piece)
                            if len(payload) > 2 * 1024 * 1024 or (
                                decoder and (decoder.unconsumed_tail or decoder.unused_data)
                            ):
                                raise ValueError("市场目录超出大小或压缩格式限制")
                        if decoder and not decoder.eof:
                            raise ValueError("市场目录压缩内容不完整")
                raw = json.loads(payload)
                if (
                    not isinstance(raw, dict)
                    or not isinstance(raw.get("items"), list)
                    or len(raw["items"]) > 1000
                ):
                    raise ValueError("市场目录格式不正确")
                items = []
                for entry in raw["items"]:
                    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                        raise ValueError("市场条目格式不正确")
                    fields = {
                        "id": 128,
                        "name": 128,
                        "description": 2000,
                        "version": 64,
                        "author": 128,
                        "category": 128,
                    }
                    if any(
                        entry.get(field) is not None and not isinstance(entry[field], str)
                        for field in fields
                    ):
                        raise ValueError("市场条目格式不正确")
                    items.append(
                        {
                            field: str(entry.get(field) or "")[:limit]
                            for field, limit in fields.items()
                        }
                    )
                result = {"kind": kind, "items": items, "readOnly": True, "compatible": False}
                self._cache[kind] = time.monotonic(), result
                return result
            except httpx.HTTPError as error:
                raise ValueError("市场网络连接失败，请稍后重试") from error
            except (UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("市场目录无法解析") from error
        finally:
            self._lock.release()
