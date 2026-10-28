"""Storage overview, closed-launch log policy and explicit offline cleanup."""

import copy
import json
import logging
import re
import sqlite3
import threading
import time
from contextlib import nullcontext
from datetime import datetime

from ..storage.files import (
    ACCOUNT,
    INDEX_FILES,
    LOG_FILES,
    LOG_SESSION,
    children,
    file_size,
    managed,
    remove_files,
    tree_files,
)
from .paths import save_state

# SnowLuma 引擎日志：snowluma-YYYY-MM-DD.log，滚动后追加 .1/.2。
ENGINE_LOG = re.compile(r"snowluma-(\d{4}-\d{2}-\d{2})(?:\.\d+)?\.log\Z")
DEFAULT_POLICY = {"logMaxTotalMb": 256, "logRetainDays": 30, "engineRetainDays": 30}
DATA_CATEGORIES = {"archives", "sessions", "memories", "stickers", "indexes"}


def policy(value):
    if not isinstance(value, dict) or value.keys() != DEFAULT_POLICY.keys():
        raise ValueError("日志策略格式无效")
    for field, lower, upper in (("logMaxTotalMb", 1, 65536), ("logRetainDays", 0, 36500), ("engineRetainDays", 0, 36500)):
        if type(value[field]) is not int or not lower <= value[field] <= upper:
            raise ValueError("日志容量应为 1～65536 MB，保留天数应为 0～36500 的整数")
    return dict(value)


class StorageManagement:
    def __init__(self, paths, accounts=None, connection=None, agent=None):
        self._paths, self._accounts = paths, accounts
        self._connection, self._agent = connection, agent
        self._lock = threading.RLock()
        self._last_cleanup = None
        self._next_sweep = 0

    def _policy(self):
        file = managed(self._paths.runtime / "storage-settings.json", self._paths.runtime)
        if not file.exists():
            return dict(DEFAULT_POLICY)
        if file_size(file, self._paths.runtime) > 4096:
            raise ValueError("存储设置文件过大，请检查文件")
        try:
            return policy(json.loads(file.read_text(encoding="utf-8")))
        except json.JSONDecodeError, UnicodeError:
            raise ValueError("存储设置无法读取，请检查文件") from None

    def _log_groups(self):
        root = self._paths.runtime
        groups = []
        for folder in children(root / "logs", root):
            if not LOG_SESSION.fullmatch(folder.name):
                continue
            managed(folder, root)
            if not folder.is_dir():
                continue
            files = [folder / name for name in sorted(LOG_FILES) if (folder / name).exists()]
            size = sum(file_size(file, root) for file in files)
            # Launch date, rather than latest write time, defines retention.
            try:
                started = datetime.strptime(
                    folder.name.rsplit("-", 1)[0], "%Y-%m-%d_%H-%M-%S.%f"
                ).timestamp()
            except ValueError:
                continue  # Unrecognized folders are outside the log policy.
            groups.append(
                {
                    "folder": folder,
                    "files": files,
                    "bytes": size,
                    "started": started,
                    "active": folder.name == self._paths.log_session,
                }
            )
        return sorted(groups, key=lambda item: (item["started"], item["folder"].name))

    def _engine_files(self):
        """SnowLuma 引擎日志按天滚动，文件名里的日期决定保留；当天的视为活跃。"""
        root = self._paths.runtime
        folder = root / "logs" / "snowluma"
        today = datetime.now().strftime("%Y-%m-%d")
        items = []
        for file in children(folder, root):
            match = ENGINE_LOG.fullmatch(file.name)
            if not match or not file.is_file():
                continue
            try:
                started = datetime.strptime(match[1], "%Y-%m-%d").timestamp()
            except ValueError:
                continue
            items.append(
                {
                    "folder": None,
                    "files": [file],
                    "bytes": file_size(file, root),
                    "started": started,
                    "active": match[1] >= today,
                }
            )
        return items

    def _account_items(self):
        roots = (self._paths.runtime / "accounts", self._paths.snowluma_data)
        values = set()
        for root in roots:
            for directory in children(root, root.parent):
                if ACCOUNT.fullmatch(directory.name):
                    managed(directory, root.parent)
                    if directory.is_dir():
                        values.add(directory.name)
        return sorted(values, key=int)

    def _index_files(self, account):
        root = self._paths.snowluma_data
        directory = managed(root / account, root)
        return [directory / name for name in sorted(INDEX_FILES) if (directory / name).exists()]

    def _temporary(self):
        root = self._paths.runtime
        values = {}
        for account in self._account_items():
            files = []
            for name in ("debug-files", "media-tmp"):
                directory = root / "accounts" / account / name
                if directory.exists():
                    files.extend(tree_files(directory, root))
            values[account] = files
        return values

    def overview(self):
        with self._lock:
            settings = self._policy()
            logs = self._log_groups()
            status = self._connection.status() if self._connection else {}
            busy = bool(status.get("account")) or status.get("state") in (
                "connecting",
                "disconnecting",
            )
            agent = self._agent.status() if self._agent else {}
            busy = busy or bool(agent.get("active") or agent.get("queued"))
            temporary = self._temporary()
            accounts = []
            for account in self._account_items():
                item = (
                    self._accounts.storage_snapshot(account)
                    if self._accounts
                    else {
                        "databaseBytes": 0,
                        "counts": dict.fromkeys(DATA_CATEGORIES - {"indexes"}, 0),
                    }
                )
                indexes = self._index_files(account)
                index_bytes = sum(file_size(file, self._paths.snowluma_data) for file in indexes)
                temp_bytes = sum(
                    file_size(file, self._paths.runtime) for file in temporary[account]
                )
                accounts.append(
                    {
                        "account": account,
                        **item,
                        "indexBytes": index_bytes,
                        "temporaryBytes": temp_bytes,
                        "indexFiles": len(indexes),
                    }
                )
            engine = self._engine_files()
            engine_bytes = sum(item["bytes"] for item in engine)
            log_bytes = sum(item["bytes"] for item in logs) + engine_bytes
            database_bytes = sum(item["databaseBytes"] + item["indexBytes"] for item in accounts)
            temp_bytes = sum(item["temporaryBytes"] for item in accounts)
            home = self._paths.snowluma_home
            service_bytes = sum(file_size(file, home) for file in tree_files(home, home))
            service_bytes -= sum(item["indexBytes"] for item in accounts)
            return {
                "settings": settings,
                "busy": busy,
                "accounts": accounts,
                "logs": {
                    "bytes": log_bytes,
                    "launches": len(logs),
                    "activeBytes": sum(item["bytes"] for item in logs if item["active"]),
                    "closedLaunches": sum(not item["active"] for item in logs),
                    "engineBytes": engine_bytes,
                    "engineFiles": len(engine),
                    "engineActiveBytes": sum(item["bytes"] for item in engine if item["active"]),
                    "engineClosedFiles": sum(not item["active"] for item in engine),
                },
                "totals": {
                    "logsBytes": log_bytes,
                    "accountBytes": database_bytes,
                    "temporaryBytes": temp_bytes,
                    "serviceBytes": service_bytes,
                    "managedBytes": log_bytes + database_bytes + temp_bytes + service_bytes,
                },
                "lastCleanup": copy.deepcopy(self._last_cleanup),
            }

    def save(self, value):
        with self._lock:
            settings = policy(value)
            file = managed(self._paths.runtime / "storage-settings.json", self._paths.runtime)
            save_state(file, settings)
            result = self._prune_logs(settings)
            return {"overview": self.overview(), "cleanup": result}

    def _prune_logs(self, settings, *, all_closed=False):
        groups = sorted(self._log_groups() + self._engine_files(), key=lambda item: item["started"])
        total = sum(item["bytes"] for item in groups)
        now = time.time()
        cap = settings["logMaxTotalMb"] * 1024 * 1024
        result = {"deletedFiles": 0, "deletedRows": 0, "freedBytes": 0, "failures": []}
        for item in groups:
            days = settings["engineRetainDays"] if item["folder"] is None else settings["logRetainDays"]
            expired = days > 0 and item["started"] < now - days * 86400
            if item["active"] or not (all_closed or expired or total > cap):
                continue
            cleaned = remove_files(item["files"], self._paths.runtime)
            for key in ("deletedFiles", "freedBytes"):
                result[key] += cleaned[key]
            result["failures"].extend(cleaned["failures"])
            total -= cleaned["freedBytes"]
            if item["folder"] is None:
                continue  # 引擎日志与当天的文件共用一个目录，只删文件不删目录。
            try:
                item["folder"].rmdir()
            except OSError:
                pass  # Unknown files remain untouched; never recursively remove a launch.
        return result

    def sweep(self):
        with self._lock:
            if time.monotonic() < self._next_sweep:
                return
            self._next_sweep = time.monotonic() + 60
            try:
                result = self._prune_logs(self._policy())
                if result["failures"]:
                    logging.warning("旧日志清理遇到 %d 个占用或权限问题", len(result["failures"]))
            except OSError, ValueError:
                logging.exception("日志保留策略检查失败，保留原文件")

    def cleanup(self, request):
        if not isinstance(request, dict):
            raise ValueError("清理请求无效")
        scope = request.get("scope")
        if not isinstance(scope, str):
            raise ValueError("清理范围无效")
        expected = (
            {"scope", "category", "account"}
            if scope == "account"
            else {"scope", "category", "accounts"}
            if scope == "allAccounts"
            else {"scope"}
        )
        if request.keys() != expected or scope not in (
            "logs",
            "temporary",
            "account",
            "allAccounts",
        ):
            raise ValueError("清理范围无效")
        category = request.get("category")
        if scope in ("account", "allAccounts") and (
            not isinstance(category, str) or category not in DATA_CATEGORIES
        ):
            raise ValueError("清理分类无效")
        if scope == "allAccounts" and (
            not isinstance(request["accounts"], list)
            or not request["accounts"]
            or any(
                not isinstance(item, str) or not ACCOUNT.fullmatch(item)
                for item in request["accounts"]
            )
            or len(set(request["accounts"])) != len(request["accounts"])
        ):
            raise ValueError("清理账号列表无效")
        if scope == "account" and (
            not isinstance(request["account"], str) or not ACCOUNT.fullmatch(request["account"])
        ):
            raise ValueError("清理账号无效")
        # Hold the same connection operation gate as attach/detach through the
        # entire cleanup. A status check alone would race a concurrent attach.
        gate = (
            self._connection.storage_maintenance()
            if scope != "logs" and self._connection
            else nullcontext()
        )
        with self._lock, gate:
            if scope != "logs" and self._agent:
                state = self._agent.status()
                if state.get("active") or state.get("queued"):
                    raise ValueError("机器人仍有任务，请等待处理停止后清理")
            result = {"deletedFiles": 0, "freedBytes": 0, "deletedRows": 0, "failures": []}
            if scope == "logs":
                result.update(self._prune_logs(self._policy(), all_closed=True))
            elif scope == "temporary":
                files = [file for group in self._temporary().values() for file in group]
                result.update(remove_files(files, self._paths.runtime))
            else:
                targets = [request["account"]] if scope == "account" else request["accounts"]
                if scope == "allAccounts" and set(targets) != set(self._account_items()):
                    raise ValueError("账号列表已变化，请刷新并重新确认清理范围")
                if any(account not in self._account_items() for account in targets):
                    raise ValueError("账号存储已变化，请刷新后重试")
                # Preflight all targets before the first mutation.
                for account in targets:
                    if category == "indexes":
                        for file in self._index_files(account):
                            file_size(file, self._paths.snowluma_data)
                    elif self._accounts:
                        self._accounts.storage_snapshot(account)
                for account in targets:
                    try:
                        if category == "indexes":
                            cleaned = remove_files(self._index_files(account), self._paths.snowluma_data)
                        elif self._accounts:
                            cleaned = self._accounts.storage_clear(account, category)
                        else:
                            raise ValueError("账号存储尚未就绪")
                    except OSError, sqlite3.Error:
                        logging.exception("清理账号 %s 的 %s 未完成", account, category)
                        result["failures"].append(f"QQ {account} 的数据被占用或无法写入")
                        continue
                    for key in ("deletedFiles", "freedBytes", "deletedRows"):
                        result[key] += cleaned.get(key, 0)
                    result["failures"].extend(cleaned.get("failures", []))
            self._last_cleanup = {
                "at": int(time.time() * 1000),
                "scope": scope,
                "category": category,
                "account": request.get("account"),
                **result,
            }
            return {
                "success": not result["failures"],
                "cleanup": result,
                "overview": self.overview(),
            }
