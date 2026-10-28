"""User-selected debug attachments. Only opaque, account-bound handles leave Python."""

import base64
import hashlib
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from ..agent.images import prepare_image
from ..storage.messages import account_id

MAX_FILE = 8 * 1024 * 1024


def container(data):
    """按文件头判断容器格式；调试上传只关心能不能当成视频发出去。"""
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "mov"
    if data[:4] == b"\x1aE\xdf\xa3":
        return "matroska"
    raise ValueError("媒体格式不支持；支持 GIF、MP4/MOV 与 WebM/MKV，不读取播放列表或外部文件")


class DebugFiles:
    def __init__(self, root):
        self._root = Path(root)
        self._id = uuid.uuid4().hex
        self._items = {}
        self._dirs = set()
        self._lock = threading.RLock()
        self._closed = False

    def _remove(self, token):
        item = self._items[token]
        if item["uses"]:
            item["valid"] = False
            return
        item["valid"] = False
        try:
            item["path"].unlink(missing_ok=True)
        except OSError:
            logging.warning("调试附件暂时无法删除，将由临时文件清理回收", exc_info=True)
        self._items.pop(token, None)
        if self._closed:
            try:
                item["path"].parent.rmdir()
            except OSError:
                pass

    def clear(self):
        with self._lock:
            for token in list(self._items):
                self._remove(token)

    def prune(self):
        with self._lock:
            for token, item in list(self._items.items()):
                if time.monotonic() - item["created"] >= 900:
                    self._remove(token)

    def close(self):
        with self._lock:
            self._closed = True
            self.clear()
            for directory in self._dirs:
                try:
                    directory.rmdir()
                except OSError:
                    pass

    def stage(self, account, kind, name, encoded):
        account_id(account)
        if kind not in ("image", "record", "video", "file"):
            raise ValueError("附件类型无效")
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 120
            or any(c in name for c in "/\\")
            or any(ord(c) < 32 for c in name)
        ):
            raise ValueError("附件名称无效")
        if not isinstance(encoded, str) or not encoded or len(encoded) > ((MAX_FILE + 2) // 3) * 4:
            raise ValueError("附件最大为 8 MB")
        try:
            data = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise ValueError("附件编码无效") from None
        if not data or len(data) > MAX_FILE:
            raise ValueError("附件为空或超过 8 MB")
        extension = ".bin"
        if kind == "image":
            clean = prepare_image(data)
            prefix, separator, payload = clean["part"]["image_url"]["url"].partition(",")
            if prefix != "data:image/jpeg;base64" or not separator:
                raise ValueError("图片预处理未返回有效的 JPEG 数据")
            data = base64.b64decode(payload, validate=True)
            extension = ".jpg"
        elif kind == "video":
            fmt = container(data)
            if fmt == "gif":
                raise ValueError("GIF 请按图片选择；视频支持 MP4/MOV 和 WebM/MKV")
            extension = ".mp4" if fmt == "mov" else ".mkv"
        elif kind == "record":
            if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
                extension = ".wav"
            elif data.startswith((b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
                extension = ".mp3"
            elif data.startswith(b"OggS"):
                extension = ".ogg"
            elif data.startswith((b"#!SILK", b"\x02#!SILK")):
                extension = ".silk"
            elif data.startswith(b"#!AMR"):
                extension = ".amr"
            else:
                raise ValueError("语音格式不支持，请选择 WAV、MP3、OGG、SILK 或 AMR")
        with self._lock:
            if self._closed:
                raise ValueError("附件服务已关闭")
            self.prune()
            if len(self._items) >= 8:
                raise ValueError("最多暂存 8 个附件，请先移除不再使用的附件")
            directory = self._root / account / "debug-files" / self._id
            # resolve() also checks pre-existing parent account/debug-files links;
            # the random final directory is not the only component protected.
            if directory.resolve() != directory.absolute():
                raise ValueError("附件目录不能指向其他位置")
            directory.mkdir(parents=True, exist_ok=True)
            self._dirs.add(directory)
            token = uuid.uuid4().hex
            path = directory / (token + extension)
            path.write_bytes(data)
            item = {
                "account": account,
                "kind": kind,
                "name": name,
                "path": path,
                "digest": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "created": time.monotonic(),
                "uses": 0,
                "valid": True,
            }
            self._items[token] = item
            return {"token": token, "name": name, "kind": kind, "bytes": len(data)}

    def discard(self, account, token):
        with self._lock:
            item = self._items.get(token) if isinstance(token, str) else None
            if item and item["account"] == account:
                self._remove(token)

    def valid(self, account, tokens):
        with self._lock:
            for token in tokens:
                item = self._items.get(token)
                if (
                    not item
                    or not item["valid"]
                    or item["account"] != account
                    or time.monotonic() - item["created"] >= 900
                ):
                    return False
                try:
                    if (
                        item["path"].stat().st_size != item["bytes"]
                        or hashlib.sha256(item["path"].read_bytes()).hexdigest() != item["digest"]
                    ):
                        return False
                except OSError:
                    return False
            return not self._closed

    @contextmanager
    def use(self, account, tokens):
        tokens = set(tokens)
        with self._lock:
            if not self.valid(account, tokens):
                raise ValueError("附件已过期、变化或不属于当前账号，请重新选择")
            items = {token: self._items[token] for token in tokens}
            for item in items.values():
                item["uses"] += 1
        try:
            yield items
        finally:
            with self._lock:
                for token, item in items.items():
                    item["uses"] -= 1
                    if not item["valid"] or self._closed:
                        self._remove(token)
