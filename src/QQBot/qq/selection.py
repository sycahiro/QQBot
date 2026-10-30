"""记住期望使用的机器人 QQ 号；不保存 PID，不建立连接。"""

import json
import re
import threading

from ..desktop.paths import save_state
from ..storage.messages import account_id
from .discovery import DiscoveryError


class AccountSelection:
    def __init__(self, file):
        self._file = file
        self._writing = threading.Lock()
        self._reading = threading.RLock()
        self._signature = None
        self._cached = None

    def read(self):
        try:
            with self._reading:
                try:
                    stat = self._file.stat()
                except FileNotFoundError:
                    self._signature = None
                    self._cached = None
                    return None
                signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
                if signature == self._signature:
                    return self._cached
                with self._file.open("rb") as stream:
                    raw = stream.read(4097)
                if len(raw) > 4096:
                    raise ValueError("too large")
                data = json.loads(raw)
                uin = data["uin"]
                if type(data["version"]) is not int or data["version"] != 1:
                    raise ValueError("invalid selection")
                if uin is not None:
                    account_id(uin)
                self._signature, self._cached = signature, uin
                return uin
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise DiscoveryError(
                "INVALID_SELECTION", "保存的机器人账号配置无法读取，原文件已保留"
            ) from error

    def choose(self, target, discovery):
        if not self._writing.acquire(blocking=False):
            raise DiscoveryError("BUSY", "正在保存机器人账号，请稍候")
        try:
            uin = None
            if target is not None:
                if (
                    not isinstance(target, dict)
                    or type(target.get("pid")) is not int
                    or not isinstance(target.get("processKey"), str)
                    or not isinstance(target.get("uin"), str)
                    or not re.fullmatch(r"[1-9]\d{4,11}", target["uin"], flags=re.ASCII)
                ):
                    raise DiscoveryError("INVALID_SELECTION", "请从检测列表中选择账号")
                matches = [
                    item
                    for item in discovery.list_processes()
                    if item["pid"] == target["pid"]
                    and item["processKey"] == target["processKey"]
                    and item["identityReady"]
                    and item["account"]["uin"] == target["uin"]
                ]
                if len(matches) != 1:
                    raise DiscoveryError("STALE_SELECTION", "QQ 账号或进程已变化，请刷新后重新选择")
                uin = target["uin"]
            try:
                save_state(self._file, {"version": 1, "uin": uin})
                with self._reading:
                    self._signature = None
            except OSError as error:
                raise DiscoveryError(
                    "SAVE_FAILED", "机器人账号保存失败，之前的选择保持不变"
                ) from error
            return uin
        finally:
            self._writing.release()
