"""复用原 collect/list/get/note/send_sticker 的工具语义，接入本地账号库。

收藏必须复用已读消息图片；发图复用已有预览、发送队列、回执和去重。
不调用 QQ 收藏管理接口，不提供路径或 URL 输入，不自动重发。
"""

import asyncio
import logging
import sqlite3

from ..storage.messages import numeric_id
from ..storage.stickers import identifier
from .images import ImageReader

logger = logging.getLogger(__name__)


class StickerTools:
    def __init__(self, account, key, config, store, images, permit, collect, note, send):
        self._account, self._key, self._config, self._store, self._images = (
            account,
            key,
            config,
            store,
            images,
        )
        self._permit, self._collect, self._note, self._send = permit, collect, note, send
        self._reviewed_sources, self._cache = set(), {}
        self._views, self._collects = 0, 0

    def confirm_previews(self):
        self._reviewed_sources = self._images.prepared_ids()
        for image in self._cache.values():
            image["reviewed"] = True

    async def execute(self, name, args):
        if self._store is None:
            raise ValueError("表情库尚未就绪")
        if not self._config["sticker"]["enabled"]:
            raise ValueError("表情库当前关闭")
        if not self._permit():
            raise asyncio.CancelledError()
        if name == "list_stickers":
            if set(args) - {"query", "limit"}:
                raise ValueError("表情查询参数无效")
            return {
                "stickers": self._store.list(
                    self._account, args.get("query", ""), args.get("limit", 24)
                )
            }, []
        if name == "sticker_note":
            if set(args) - {"stickerId", "note", "tags", "usage"}:
                raise ValueError("表情备注参数无效")
            result = self._note(
                args.get("stickerId"), args.get("note", ""), args.get("tags"), args.get("usage", "")
            )
            return {"updated": True, **result}, []
        if not self._config["api"]["vision"]:
            raise ValueError("请先开启模型看图功能")
        if name == "collect_sticker":
            if not self._config["sticker"]["collectEnabled"]:
                raise ValueError("模型收藏图片当前关闭")
            if set(args) - {"messageId", "note"} or numeric_id(args.get("messageId")) is None:
                raise ValueError("收藏仅接受当前聊天的 messageId 和简短备注")
            item, prepared = self._images.prepared(self._account, self._key, args["messageId"])
            if item["id"] not in self._reviewed_sources:
                raise ValueError("请先看图，在下一次模型回应确认图片后再收藏")
            if self._collects >= 2:
                raise ValueError("一次处理最多收藏 2 张表情")
            self._collects += 1
            result = self._collect(
                prepared,
                args.get("note", ""),
                {"chatKey": self._key, "id": item["id"], "mid": item["mid"]},
            )
            return {
                **result,
                "localSaved": True,
                "qqSaved": False,
                "message": "已保存到当前机器人账号的本地表情库，不修改 QQ 客户端收藏。",
            }, []
        if name == "get_sticker_image":
            if set(args) != {"stickerId"}:
                raise ValueError("看表情只接受 stickerId")
            item = identifier(args["stickerId"])
            if item in self._cache:
                return {
                    "id": item,
                    "count": 0,
                    "message": "表情图片已提供，请使用前面的图片输入",
                }, []
            if self._views >= 4:
                raise ValueError("一次处理最多查看 4 张表情")
            # Count actual supplied views; missing library rows do not decode
            # bytes or call a model, unlike failed network download attempts.
            image = self._store.get(self._account, item)
            self._views += 1
            image["reviewed"] = False
            self._cache[item] = image
            return {
                "id": item,
                "count": 1,
                **image["meta"],
                "message": "已提供表情真实图片，动图只保留第一帧。",
            }, [image["part"]]
        if name == "send_sticker":
            if set(args) - {"stickerId", "replyToMessageId", "atUserId"}:
                raise ValueError("表情发送仅限当前聊天，不接受路径或地址")
            if not self._config["api"]["sendImages"]:
                raise ValueError("请先开启机器人图片发送")
            item = identifier(args.get("stickerId"))
            image = self._cache.get(item)
            if not image or not image["reviewed"]:
                raise ValueError("请先用 get_sticker_image 看表情，在下一次模型回应后再发送")
            # 发送配额由 service._send 对 session["sent"] 统一判定（图片+表情
            # 共享额度），这里不再另记计数。
            current = self._store.get(self._account, item)
            if current["digest"] != image["digest"]:
                raise ValueError("表情图片已经变化，请重新查看")
            if not self._permit():
                raise asyncio.CancelledError()
            values = {k: v for k, v in args.items() if k != "stickerId"}
            values["note"] = ""  # A sticker is a separate image, without an injected caption.
            result = await self._send(values, image, item)
            if result["sent"]:
                try:
                    self._store.mark_used(self._account, item)
                except sqlite3.Error:
                    logger.warning(
                        "Sticker use count could not be updated after confirmed delivery"
                    )
            return {"message": "发送结果以 QQ 回执为准", **result, "stickerId": item}, []
        raise ValueError("未提供此表情工具")


async def collect_message(
    stickers, messages, native, permit, account, key, mid, note="", *, downloader=None
):
    """Manual archive button: no model request, no native favorite mutation."""
    source = {}

    def track(item):
        source.update(chatKey=key, id=item["id"], mid=item["mid"])

    images = ImageReader(messages, native, track, permit, downloader=downloader, max_images=1)
    result, _ = await images.read(account, key, {"messageId": mid})
    if not result["count"]:
        raise ValueError(result.get("message") or "这条消息没有可收藏的图片")
    _item, prepared = images.prepared(account, key, mid)
    if not permit():
        raise asyncio.CancelledError()
    return stickers.add(account, prepared, note, source=source)
