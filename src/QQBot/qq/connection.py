"""账号连接监督：显式接入、真实身份复核、状态缓存和事件隔离。"""

import copy
import logging
import queue
import threading
from contextlib import contextmanager

from .discovery import DiscoveryError
from .engine import EngineError

logger = logging.getLogger(__name__)


class QqConnection:
    def __init__(
        self,
        paths,
        discovery,
        selection,
        *,
        engine_factory,
        on_status=None,
        on_event=None,
    ):
        self._paths, self._discovery, self._selection = paths, discovery, selection
        self._factory, self._on_status, self._on_event = engine_factory, on_status, on_event
        self._guard = threading.Lock()
        self._operations = threading.Lock()
        self._closed = False
        self._client = None
        self._watcher = None
        self._stop = None
        self._target = None
        self._verified = False
        self._status = {
            "state": "idle",
            "connected": False,
            "account": None,
            "database": None,
            "error": None,
        }

    def status(self):
        with self._guard:
            return copy.deepcopy(self._status)

    def _change(self, **values):
        with self._guard:
            if self._closed and values.get("state") != "closed":
                return
            self._status.update(values)
            snapshot = copy.deepcopy(self._status)
        if self._on_status:
            try:
                self._on_status(snapshot)
            except Exception:
                logger.exception("Connection status callback failed")

    @contextmanager
    def _operation(self):
        if not self._operations.acquire(blocking=False):
            raise EngineError("BUSY", "账号正在执行操作，请稍候")
        try:
            with self._guard:
                if self._closed:
                    raise EngineError("CLOSED", "账号连接服务已关闭")
            yield
        finally:
            self._operations.release()

    def choose(self, target):
        with self._operation():
            with self._guard:
                if self._status["connected"] or self._status["state"] in (
                    "connecting",
                    "disconnecting",
                ):
                    raise EngineError("ACCOUNT_ACTIVE", "请先断开当前 QQ，再更改机器人账号")
                retained = self._client
            if retained:
                # Failed/disconnected sessions may still own a Node pipe/hook.
                # Release them completely before changing the saved identity.
                try:
                    self._release()
                except Exception as error:
                    with self._guard:
                        if self._client is None and not self._closed:
                            self._client = retained
                    self._change(
                        state="error", connected=False, error="旧 QQ 连接未能释放，请退出应用后重试"
                    )
                    raise EngineError(
                        "RELEASE_FAILED", "旧 QQ 连接未能释放，未更改机器人账号"
                    ) from error
                self._change(state="idle", connected=False, account=None, database=None, error=None)
            return self._selection.choose(target, self._discovery)

    @contextmanager
    def storage_maintenance(self):
        """Keep attach/detach excluded for the entire offline data mutation."""
        with self._operation():
            with self._guard:
                if (
                    self._client is not None
                    or self._status["connected"]
                    or self._status["state"] in ("connecting", "disconnecting")
                ):
                    raise EngineError("ACCOUNT_ACTIVE", "请先断开 QQ 连接，再清理存储")
            yield

    def connect(self, target):
        with self._operation():
            if not isinstance(target, dict) or not isinstance(target.get("uin"), str):
                raise EngineError("INVALID_ACCOUNT", "请从当前列表选择要连接的账号")
            if self._selection.read() != target["uin"]:
                raise EngineError("ACCOUNT_NOT_SELECTED", "请先将该账号设为机器人")
            candidates = self._discovery.list_processes()
            matches = [
                item
                for item in candidates
                if item["pid"] == target.get("pid")
                and item["processKey"] == target.get("processKey")
                and item["identityReady"]
                and item["account"]["uin"] == target["uin"]
            ]
            if len(matches) != 1:
                raise EngineError("STALE_PROCESS", "QQ 已变化，请刷新后重新选择")
            with self._guard:
                if self._status["connected"]:
                    raise EngineError("ALREADY_CONNECTED", "当前 QQ 已连接")
            self._release()
            selected = matches[0]
            client = self._factory(self._paths)
            stop = threading.Event()
            with self._guard:
                if self._closed:
                    raise EngineError("CLOSED", "账号连接服务已关闭")
                self._client, self._stop, self._target = client, stop, dict(target)
                self._verified = False
            self._change(
                state="connecting",
                connected=False,
                error=None,
                database=None,
                account={
                    "uin": target["uin"],
                    "pid": target["pid"],
                    "nickname": selected["account"]["nickname"],
                    "version": selected["version"],
                },
            )
            try:
                client.start()
                self._watcher = threading.Thread(
                    target=self._watch, args=(client, stop), name="qq-events", daemon=True
                )
                self._watcher.start()
                state = client.request("account.attach", target, timeout=45)
                login = client.request(
                    "account.action",
                    {"uin": target["uin"], "action": "get_login_info", "params": {}},
                    timeout=15,
                )
                if (
                    not state.get("ready")
                    or login.get("status") != "ok"
                    or str((login.get("data") or {}).get("user_id")) != target["uin"]
                ):
                    raise EngineError("IDENTITY_MISMATCH", "QQ 真实登录身份未通过复核，已停止连接")
                with self._guard:
                    if self._closed or self._client is not client:
                        raise EngineError("CLOSED", "连接已被关闭")
                    self._verified = True
                self._change(
                    state="ready", connected=True, database=state.get("database"), error=None
                )
                return self.status()
            except Exception as error:
                self._release()
                self._change(state="error", connected=False, error=str(error))
                if isinstance(error, (EngineError, DiscoveryError)):
                    raise
                logger.exception("QQ connection failed")
                raise EngineError("CONNECT_FAILED", "QQ 连接失败，请查看运行日志") from error

    def disconnect(self):
        with self._operation():
            self._change(state="disconnecting", connected=False)
            with self._guard:
                self._verified = False
                client = self._client
            warning = None
            try:
                if client:
                    client.request("account.detach", timeout=40)
            except EngineError as error:
                warning = str(error)
                logger.warning("QQ disconnect not confirmed: %s", error)
            finally:
                self._release()
            self._change(state="idle", connected=False, account=None, database=None, error=warning)
            return self.status()

    def invoke(self, action, params=None, *, expected_account=None):
        """仅供应用业务模块调用，不直接暴露任意动作给网页。"""
        with self._operation():
            with self._guard:
                if not self._verified or not self._status["connected"] or not self._client:
                    raise EngineError("NOT_CONNECTED", "QQ 尚未验证连接")
                client, target = self._client, dict(self._target)
                if expected_account is not None and target["uin"] != expected_account:
                    raise EngineError("IDENTITY_MISMATCH", "当前 QQ 账号与业务账号不一致")
            return client.request(
                "account.action",
                {"uin": target["uin"], "action": action, "params": params or {}},
                timeout=45,
            )

    def action_docs(self):
        with self._operation():
            with self._guard:
                if not self._verified or not self._client:
                    raise EngineError("NOT_CONNECTED", "请先连接 QQ")
                client = self._client
            return client.request("engine.action_docs", {}, timeout=20)

    def _watch(self, client, stop):
        while not stop.is_set():
            try:
                event = client.next_event(timeout=0.25)
            except queue.Empty:
                continue
            except EngineError as error:
                if not stop.is_set():
                    with self._guard:
                        self._verified = False
                    self._change(state="error", connected=False, error=str(error))
                return
            kind, data = event.get("event"), event.get("data") or {}
            with self._guard:
                if self._client is not client or self._closed:
                    return
                verified, target = self._verified, self._target
            if kind == "engine.state" and verified:
                selected = data.get("selected") or {}
                if (
                    not data.get("ready")
                    or selected.get("uin") != target["uin"]
                    or selected.get("pid") != target["pid"]
                    or selected.get("processKey") != target["processKey"]
                ):
                    with self._guard:
                        self._verified = False
                    self._change(
                        state="disconnected",
                        connected=False,
                        error=data.get("error") or "QQ 连接已断开，请确认账号后手动重新连接",
                    )
            elif kind == "qq.event" and verified:
                payload = data.get("event") or {}
                if (
                    data.get("accountUin") != target["uin"]
                    or str(payload.get("self_id")) != target["uin"]
                ):
                    logger.warning("Discarded event from a different QQ account")
                    continue
                if self._on_event:
                    try:
                        self._on_event(target["uin"], payload)
                    except Exception:
                        logger.exception("QQ event persistence failed")
                        with self._guard:
                            self._verified = False
                        self._change(
                            state="error",
                            connected=False,
                            error="消息处理失败，已停止接收，请查看运行日志",
                        )

    def _release(self):
        with self._guard:
            client, self._client = self._client, None
            stop, self._stop = self._stop, None
            watcher, self._watcher = self._watcher, None
            self._verified = False
        if stop:
            stop.set()
        try:
            if client:
                client.close()
        finally:
            if watcher and watcher is not threading.current_thread():
                watcher.join(timeout=5)

    def close(self):
        with self._guard:
            self._closed = True
        self._change(state="closed", connected=False)
        self._release()
