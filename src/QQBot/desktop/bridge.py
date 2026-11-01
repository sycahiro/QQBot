"""向自有窗口提供应用信息、只读 QQ 检测和就绪回执。"""

import asyncio
import base64
import json
import logging
import os
import platform
import sqlite3
import threading
import time
import webbrowser
from functools import wraps

from ..agent.config import allowed
from ..agent.images import prepare_image
from ..agent.llm import ModelError
from ..agent.memory_review import MemoryReviews
from ..agent.models import ModelChecks
from ..agent.queries import MessageQueries
from ..agent.sender import DeliveryError
from ..agent.stickers import collect_message
from ..agent.web import (
    SearchError,
    WebClient,
    sanitize_query,
    web_url,
)
from ..qq.discovery import DiscoveryError
from ..qq.engine import EngineError
from ..qq.selection import AccountSelection
from ..qq.snowluma import WEBUI_PORT
from . import contacts, dependencies
from .appearance import Appearance, appearance_file
from .diagnostics import read_log_entries
from .resources import ResourceMonitor
from .storage import StorageManagement

logger = logging.getLogger(__name__)


def _guarded(method):
    """Preserve successful payloads and structure unexpected bridge failures."""

    @wraps(method)
    def run(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except (Exception, asyncio.CancelledError) as error:

            def fail(failure=error):
                raise failure

            return self._business(fail)

    return run


class DesktopBridge:
    def __init__(
        self,
        paths,
        update,
        discovery=None,
        connection=None,
        selection=None,
        messages=None,
        settings=None,
        agent=None,
        sessions=None,
        memory=None,
        *,
        stickers=None,
        residence=None,
        global_settings=None,
        frame=None,
        accounts=None,
    ):
        # pywebview 会递归暴露 public 属性；路径对象和回调必须保持私有。
        self._paths = paths
        self._update = update
        self._started = time.monotonic()
        self._resources = ResourceMonitor()
        self._appearance = Appearance(appearance_file(paths.runtime))
        self._discovery = discovery
        self._selection = selection or AccountSelection(
            paths.runtime / "state" / "account.json"
        )
        self._connection = connection
        self._messages, self._settings = messages, settings
        self._agent, self._sessions = agent, sessions
        self._memory = memory
        self._stickers = stickers
        self._residence = residence
        self._frame = frame
        self._global_settings = global_settings
        self._models = ModelChecks()
        self._reviews = MemoryReviews()
        self._web = WebClient()
        self._native_fallback_lock = threading.Lock()
        self._storage = StorageManagement(paths, accounts, connection, agent)

    def _version(self):
        try:
            return self._paths.version
        except (OSError, ValueError, KeyError, TypeError):
            logger.exception("应用版本信息无法读取，请检查 app/package.json")
            return "unknown"

    @_guarded
    def get_bootstrap(self):
        try:
            snowluma_version = json.loads(
                self._paths.snowluma_entry.with_name("package.json").read_text(encoding="utf-8")
            ).get("version")
        except (OSError, ValueError, AttributeError):
            snowluma_version = None
        return {
            "name": "QQBot",
            "version": self._version(),
            "platform": "Windows x64",
            "python": platform.python_version(),
            "renderer": "WebView2",
            "snowlumaVersion": snowluma_version,
            "uptimeSeconds": round(time.monotonic() - self._started),
            "qqConnected": self.get_qq_status()["connected"],
            "autoReply": self.get_agent_status()["enabled"],
            "module": "desktop",
        }

    def get_dependencies(self):
        return self._business(lambda: dependencies.inventory(self._paths))

    @_guarded
    def mark_ready(self):
        if self._residence:
            self._residence.mark_ready()
        self._update(uiReady=True)
        return {"ok": True}

    def save_theme(self, theme):
        return self._business(lambda: {"theme": self._appearance.save(theme)})

    @_guarded
    def get_resources(self):
        return self._resources.sample()

    @_guarded
    def get_snowluma_status(self):
        if self._discovery is None:
            return {"stage": "stopped", "error": None}
        return self._discovery.service_status()

    def _snowluma_webui_password(self):
        try:
            return json.loads(
                (self._paths.runtime / "secrets" / "snowluma-service.json").read_text(
                    encoding="utf-8"
                )
            )["password"]
        except (OSError, ValueError, KeyError):
            return None

    # -- 密码备忘（用户手动保存的 WebUI 密码，仅存本机） ---------------------

    def _memo_file(self):
        return self._paths.runtime / "secrets" / "webui-password.json"

    @_guarded
    def get_webui_password_memo(self):
        def read():
            try:
                data = json.loads(self._memo_file().read_text(encoding="utf-8"))
            except FileNotFoundError:
                return {"password": None}
            except (OSError, ValueError) as error:
                raise ValueError("密码备忘文件无法读取，请检查 runtime/secrets") from error
            if not isinstance(data, dict) or not isinstance(data.get("password"), str):
                return {"password": None}
            return {"password": data["password"]}

        return self._business(read)

    @_guarded
    def save_webui_password_memo(self, password):
        def save():
            if not isinstance(password, str) or len(password) > 200:
                raise ValueError("密码备忘内容无效")
            file = self._memo_file()
            file.parent.mkdir(parents=True, exist_ok=True)
            temporary = file.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"password": password} if password else {}),
                encoding="utf-8",
            )
            os.replace(temporary, file)
            return {"password": password or None}

        return self._business(save)

    @_guarded
    def start_snowluma(self):
        """应用内手动启动 SnowLuma（与浏览器控制台同模式）；不随检测隐式拉起。"""
        if self._discovery is None:
            return {"ok": False, "error": {"code": "NOT_READY", "message": "QQ 检测服务尚未就绪"}}
        try:
            status = self._discovery.start_service()
            return {"ok": True, "stage": status["stage"]}
        except DiscoveryError as error:
            status = self._discovery.service_status()
            return {"ok": False, "stage": status["stage"], "error": {"code": error.code, "message": str(error)}}

    @_guarded
    def stop_snowluma(self):
        """手动停止常驻的 SnowLuma：先断开 QQ 连接，再退出服务进程。"""
        if self._discovery is None:
            return {"ok": False, "error": {"code": "NOT_READY", "message": "QQ 检测服务尚未就绪"}}
        if self._connection is not None and self._connection.status().get("connected"):
            if self._agent:
                self._agent.pause()
            try:
                self._connection.disconnect()
            except (DiscoveryError, EngineError) as error:
                status = self._discovery.service_status()
                return {"ok": False, "stage": status["stage"], 
                        "error": {"code": error.code, "message": str(error)}}
        status = self._discovery.stop_service()
        return {"ok": True, "stage": status["stage"]}

    @_guarded
    def open_snowluma_webui(self):
        """在系统浏览器打开 SnowLuma 自带控制台；引擎的全部设置都在那里改。"""

        def open_ui():
            if self._discovery is None:
                raise ValueError("QQ 检测服务尚未就绪")
            if not self._discovery.service.running:
                raise ValueError("SnowLuma 服务未启动，请先在「连接」页启动引擎")
            url = f"http://127.0.0.1:{WEBUI_PORT}"
            if not webbrowser.open(url, new=2):
                raise ValueError("无法打开系统浏览器，请检查浏览器设置")
            return {"url": url, "password": self._snowluma_webui_password()}

        return self._business(open_ui)

    @_guarded
    def get_qq_processes(self):
        if self._discovery is None:
            return {"ok": False, "error": {"code": "NOT_READY", "message": "QQ 检测服务尚未就绪"}}
        try:
            processes = self._discovery.list_processes()
            try:
                selected = self._selection.read()
            except DiscoveryError:
                # Keep discovery available so the user can explicitly replace a
                # corrupt saved selection; never treat it as verified identity.
                return {
                    "ok": True,
                    "processes": processes,
                    "selectedUin": None,
                    "warning": "已保存的机器人账号无法读取，请重新选择账号",
                }
            return {"ok": True, "processes": processes, "selectedUin": selected}
        except DiscoveryError as error:
            return {"ok": False, "error": {"code": error.code, "message": str(error)}}

    @_guarded
    def get_qq_status(self):
        return (
            self._connection.status()
            if self._connection
            else {
                "state": "idle",
                "connected": False,
                "account": None,
                "database": None,
                "error": None,
            }
        )

    def get_contacts(self, account):
        def read():
            if not isinstance(account, str):
                raise ValueError("请先连接机器人账号")
            selected = self._account(account)
            if not self._connection:
                raise EngineError("NOT_READY", "QQ 联系人服务尚未就绪")
            # contacts.read 连发两个原生动作，且 connection._operation 是非阻塞
            # 锁：与 agent 发送/读取并发时直接 BUSY 报错。与 agent 的原生操作
            # 共用同一把锁排队，等待而不是失败。
            with self._agent.native_lock if self._agent else self._native_fallback_lock:
                items = contacts.read(self._connection, selected)
            self._account(selected)
            if self._messages is not None:
                self._messages.set_names(
                    selected,
                    {
                        f"{kind}:{entry['id']}": entry["name"]
                        for group, kind in [("groups", "group"), ("private", "private")]
                        for entry in items[group]
                    },
                )
            return {"account": selected, **items}

        return self._business(read)

    def process_archive(self, key, account):
        def run():
            if not isinstance(account, str):
                raise ValueError("请先连接机器人账号")
            selected = self._account(account)
            if self._agent is None:
                raise ValueError("机器人服务尚未就绪")
            return {"account": selected, **self._agent.process_once(selected, key)}

        return self._business(run)

    def stop_session(self, identifier, account):
        def stop():
            if not isinstance(account, str):
                raise ValueError("请先连接机器人账号")
            selected = self._account(account)
            if self._agent is None:
                raise ValueError("机器人服务尚未就绪")
            return {"account": selected, **self._agent.stop_session(selected, identifier)}

        return self._business(stop)

    def rerun_session(self, identifier, account):
        def run():
            if not isinstance(account, str):
                raise ValueError("请先连接机器人账号")
            selected = self._account(account)
            if self._agent is None or self._sessions is None:
                raise ValueError("会话服务尚未就绪")
            item = self._sessions.get(selected, identifier)
            if not item:
                raise ValueError("会话不存在")
            return {
                "account": selected,
                **self._agent.process_once(selected, item["chatKey"], retry_of=identifier),
            }

        return self._business(run)

    def get_desktop_options(self):
        return self._desktop_options()

    def save_desktop_options(self, options):
        return self._desktop_options(options, write=True)

    def resolve_window_close(self, action):
        def run():
            if self._residence is None:
                raise ValueError("桌面驻留服务尚未就绪")
            return self._residence.resolve_close(action)

        return self._business(run)

    def window_control(self, action):
        def run():
            if self._frame is None:
                raise ValueError("窗口尚未就绪")
            return self._frame.control(action)

        return self._business(run)

    def _desktop_options(self, options=None, *, write=False):
        def run():
            if self._residence is None:
                raise ValueError("桌面驻留服务尚未就绪")
            try:
                result = self._residence.save(options) if write else self._residence.read()
            except OSError as error:
                logger.exception("桌面驻留设置操作失败")
                raise ValueError("桌面设置或当前用户启动项操作失败，请查看运行日志") from error
            return {"options": result}

        return self._business(run)

    @_guarded
    def connect_qq_account(self, target):
        if self._connection is None:
            return {"ok": False, "error": {"code": "NOT_READY", "message": "账号连接服务尚未就绪"}}
        try:
            # 点某一行的「连接」就等于选定该账号：先落盘选择，再建立连接。
            if isinstance(target, dict) and isinstance(target.get("uin"), str):
                self._connection.choose(target)
            state = self._connection.connect(target)
            if state["connected"]:
                self._refresh_names(state["account"]["uin"])
            return {"ok": True, "connection": self._connection.status()}
        except (DiscoveryError, EngineError) as error:
            return {"ok": False, "error": {"code": error.code, "message": str(error)}}

    @_guarded
    def disconnect_qq_account(self):
        if self._agent:
            self._agent.pause()
        if self._connection is None:
            return {"ok": False, "error": {"code": "NOT_READY", "message": "账号连接服务尚未就绪"}}
        try:
            return {"ok": True, "connection": self._connection.disconnect()}
        except (DiscoveryError, EngineError) as error:
            return {"ok": False, "error": {"code": error.code, "message": str(error)}}

    def _refresh_names(self, account):
        if self._messages is None:
            return
        names = {}
        for action, kind, field in [
            ("get_group_list", "group", "group_id"),
            ("get_friend_list", "private", "user_id"),
        ]:
            try:
                result = self._connection.invoke(action)
                if result.get("status") != "ok" or not isinstance(result.get("data"), list):
                    continue
                for item in result["data"]:
                    if not isinstance(item, dict):
                        continue
                    peer = str(item.get(field, ""))
                    if peer.isdigit() and len(peer) <= 20 and int(peer) > 0:
                        names[f"{kind}:{peer}"] = (
                            item.get("group_name")
                            if kind == "group"
                            else item.get("nickname") or item.get("remark")
                        )
            except (EngineError, ValueError):
                logger.info("Conversation names unavailable for %s", kind)
        try:
            self._messages.set_names(account, names)
        except (sqlite3.Error, ValueError):
            logger.exception("Conversation names could not be saved")

    def _client_account(self, status):
        account = (status.get("account") or {}).get("uin")
        if not status.get("connected") or status.get("state") != "ready":
            return None
        try:
            selected = self._selection.read()
        except DiscoveryError:
            if not getattr(self, "_selection_unavailable", False):
                logger.exception("保存的账号选择无法读取，暂停账号页面访问")
            self._selection_unavailable = True
            return None
        self._selection_unavailable = False
        return account if account == selected else None

    def _agent_workspace(self):
        """QQ Agent 页：只服务本机已连接的个人 QQ。"""
        connection = self.get_qq_status()
        if not self._client_account(connection):
            connection = {**connection, "connected": False}
        return {"source": "qq", "connection": connection}

    def _active_account(self):
        connection = self._agent_workspace()["connection"]
        return (connection.get("account") or {}).get("uin") if connection.get("connected") else None

    def _account(self, expected=None):
        account = self._active_account()
        if not account:
            raise ValueError("请先在 QQ Agent 页连接并验证机器人账号")
        if expected is not None and expected != account:
            raise ValueError("机器人账号已变化，请刷新页面后再操作")
        return account

    def _business(
        self, operation, *, cancel_code="CANCELLED", cancel_message="操作已停止，请刷新确认当前状态"
    ):
        try:
            return {"ok": True, **operation()}
        except (DiscoveryError, EngineError) as error:
            return {"ok": False, "error": {"code": error.code, "message": str(error)}}
        except ValueError as error:
            return {"ok": False, "error": {"code": "INVALID_INPUT", "message": str(error)}}
        except sqlite3.OperationalError as error:
            code = getattr(error, "sqlite_errorcode", 0) & 255
            if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                return {
                    "ok": False,
                    "error": {
                        "code": "STORAGE_BUSY",
                        "message": "数据正在被其他操作使用，请稍后再试",
                    },
                }
            logger.exception("Business database operation failed")
            return {
                "ok": False,
                "error": {"code": "STORAGE_ERROR", "message": "业务数据操作失败，请查看运行日志"},
            }
        except sqlite3.Error:
            logger.exception("Business database operation failed")
            return {
                "ok": False,
                "error": {"code": "STORAGE_ERROR", "message": "业务数据操作失败，请查看运行日志"},
            }
        except ModelError as error:
            return {"ok": False, "error": {"code": "MODEL_ERROR", "message": str(error)}}
        except DeliveryError as error:
            return {"ok": False, "error": {"code": "DELIVERY_ERROR", "message": str(error)}}
        except asyncio.CancelledError:
            return {"ok": False, "error": {"code": cancel_code, "message": cancel_message}}
        except Exception:
            logger.exception("Business operation failed unexpectedly")
            return {
                "ok": False,
                "error": {"code": "INTERNAL", "message": "操作未完成，请查看运行日志并确认结果"},
            }

    def get_archives(self, unread_only=False):
        def read():
            if type(unread_only) is not bool:
                raise ValueError("未读筛选必须为布尔值")
            account = self._active_account()
            return {
                "account": account,
                **(
                    self._messages.archive_state(account, unread_only=unread_only)
                    if account and self._messages
                    else {"items": [], "unread": 0, "unreadChats": 0, "readThrough": 0}
                ),
            }

        return self._business(read)

    def mark_archive_read(self, key, through, account):
        def mark():
            if not isinstance(account, str):
                raise ValueError("请刷新页面后确认操作账号")
            selected = self._account(account)
            if self._messages is None:
                raise ValueError("聊天存档尚未就绪")
            return {"account": selected, "marked": self._messages.mark_read(selected, key, through)}

        return self._business(mark)

    def get_archive_messages(self, key, query, before, account):
        def read():
            if not isinstance(account, str):
                raise ValueError("请刷新页面后确认操作账号")
            selected = self._account(account)
            if self._messages is None:
                raise ValueError("聊天存档尚未就绪")
            return {
                "account": selected,
                "chatKey": key,
                **self._messages.messages(selected, key, before, query=query),
            }

        return self._business(read)

    def delete_archive(self, key=None, account=None):
        def delete():
            if not isinstance(account, str):
                raise ValueError("请刷新页面后确认操作账号")
            selected = self._account(account)
            if self._messages is None:
                raise ValueError("聊天存档尚未就绪")
            agent = self._agent
            if agent:
                agent.pause_for_data_change(selected)
            return {"account": selected, "deleted": self._messages.delete(selected, key)}

        return self._business(delete)

    def get_bot_settings(self, account=None):
        def read():
            selected = self._active_account()
            if account is not None and account != selected:
                raise ValueError("机器人账号已变化，请刷新页面后再操作")
            agent = self._agent if selected else None
            return {
                "account": selected,
                "config": self._settings.read(selected, public=True)
                if selected and self._settings
                else None,
                "autoReply": bool(agent.status()["enabled"]) if agent else False,
            }

        return self._business(read)

    def get_global_settings(self):
        return self._business(
            lambda: {"scope": "global", "config": self._globals().read(public=True)}
        )

    def _globals(self):
        if self._global_settings is None:
            raise ValueError("全局设置尚未就绪")
        return self._global_settings

    def save_global_settings(self, patch):
        def save():
            if not isinstance(patch, dict):
                raise ValueError("全局设置格式无效")
            if set(patch) == {"media", "profileId"}:
                config = self._globals().save_media(patch["media"], patch["profileId"])
            elif set(patch) in ({"webSearch"}, {"mediaOptions"}, {"defaultPersona"}, {"ownerQQ"}, {"defaultPersona", "ownerQQ"}):
                config = self._globals().save("global", patch)
            else:
                raise ValueError("请通过模型方案操作保存模型配置")
            if self._agent and not set(patch) <= {"defaultPersona", "ownerQQ"}:
                self._pause_all("全局设置已保存，请确认后重新开启自动回复")
            self._reviews.invalidate()
            return {"scope": "global", "config": config}

        return self._business(save)

    def save_bot_settings(self, patch, account=None):
        def save():
            if not isinstance(account, str):
                raise ValueError("请刷新页面后确认操作账号")
            selected = self._account(account)
            if self._settings is None:
                raise ValueError("机器人设置尚未就绪")
            if not isinstance(patch, dict) or set(patch) & {"profiles", "activeProfileId"}:
                raise ValueError("请通过模型方案操作保存配置")
            config = self._settings.save(selected, patch)
            agent = self._agent
            if agent:
                agent.pause("设置已保存，请确认后重新开启自动回复")
            return {"account": selected, "config": config}

        return self._business(save)

    @_guarded
    def get_agent_status(self):
        workspace = self._agent_workspace()
        status = (
            self._agent.status()
            if self._agent and workspace["connection"]["connected"]
            else {
                "enabled": False,
                "account": None,
                "running": 0,
                "queued": 0,
                "active": 0,
                "error": None,
            }
        )
        return self._status_with_model(status, workspace)

    def _pause_all(self, reason):
        """全局设置变更后暂停自动回复，连接本身保留。"""
        if self._agent:
            self._agent.pause(reason)

    def _status_with_model(self, status, workspace=None):
        # Polling and switch acknowledgements must use the same status shape.
        # Only the active model's name crosses the bridge, never the API/key or
        # unsaved profile draft. This also updates while the QQ account is offline.
        try:
            model = self._global_settings.values()["api"]["model"] if self._global_settings else ""
        except (ValueError, OSError):
            model = ""
        return {**status, "model": model, "workspace": workspace or self._agent_workspace()}

    def manage_model_profile(self, operation, data, account=None):
        def manage():
            if account is None:
                config = self._globals().profile("global", operation, data)
                self._pause_all("全局模型已调整，请确认后重新开启自动回复")
                self._reviews.invalidate()
                return {"scope": "global", "config": config}
            if not isinstance(account, str):
                raise ValueError("请刷新页面后确认操作账号")
            selected = self._account(account)
            if self._settings is None:
                raise ValueError("模型设置尚未就绪")
            config = self._settings.profile(selected, operation, data)
            agent = self._agent
            if agent:
                agent.pause("模型配置已调整，请确认后重新开启自动回复")
            return {"account": selected, "config": config}

        return self._business(manage)

    def get_model_list(self, account=None, draft=None, profile_id=None):
        def read():
            if account is None:
                models = asyncio.run(
                    self._models.list_models(self._globals().check_api("global", draft, profile_id))
                )
                return {"scope": "global", "models": models}
            if not isinstance(account, str):
                raise ValueError("请刷新页面后确认操作账号")
            selected = self._account(account)
            if self._settings is None:
                raise ValueError("机器人设置尚未就绪")
            models = asyncio.run(
                self._models.list_models(self._settings.check_api(selected, draft, profile_id))
            )
            self._account(selected)
            return {"account": selected, "models": models}

        return self._business(read)

    def test_model_connection(self, account=None, draft=None, profile_id=None, kind="text"):
        def test():
            if kind not in ("text", "image", "tools"):
                raise ValueError("无效的模型检查类型")
            check = getattr(
                self._models, {"text": "test", "image": "test_image", "tools": "test_tools"}[kind]
            )
            if account is None:
                api = self._globals().check_api("global", draft, profile_id)
                return {
                    "scope": "global",
                    **asyncio.run(check(api)),
                }
            if not isinstance(account, str):
                raise ValueError("请刷新页面后确认操作账号")
            selected = self._account(account)
            if self._settings is None:
                raise ValueError("机器人设置尚未就绪")
            result = asyncio.run(check(self._settings.check_api(selected, draft, profile_id)))
            self._account(selected)
            return {"account": selected, **result}

        return self._business(test)

    def set_auto_reply(self, enabled, account):
        def change():
            if not isinstance(account, str):
                raise ValueError("请刷新页面后确认操作账号")
            selected = self._account(account)
            agent = self._agent
            if agent is None:
                raise ValueError("机器人服务尚未就绪")
            return {"status": self._status_with_model(agent.enable(selected, enabled))}

        return self._business(change)

    def test_web_search(self, account=None, draft=None, probe=None):
        def test():
            values = {"kind": "search", "value": "Python 官方网站"} if probe is None else probe
            if (
                not isinstance(values, dict)
                or set(values) != {"kind", "value"}
                or values["kind"] not in ("search", "fetch")
            ):
                raise ValueError("请选择搜索或网页读取，并填写测试内容")
            kind = values["kind"]
            value = (
                sanitize_query(values["value"]) if kind == "search" else web_url(values["value"])
            )
            if account is None:
                source = self._globals().values()
                config = self._globals().check_search("global", draft)
                scope = {"scope": "global"}

                def permit():
                    return self._globals().values() == source

            else:
                if not isinstance(account, str):
                    raise ValueError("请先连接机器人账号")
                selected = self._account(account)
                if self._settings is None:
                    raise ValueError("机器人设置尚未就绪")
                config = self._settings.check_search(selected, draft)
                scope = {"account": selected}

                def permit():
                    return self._active_account() == selected

            started = time.monotonic()
            try:
                result = asyncio.run(
                    self._web.search(config, value, permit)
                    if kind == "search"
                    else self._web.fetch(value, permit)
                )
                if not permit():
                    raise asyncio.CancelledError()
                if not isinstance(result, dict):
                    raise SearchError("联网结果结构无效，请查看运行日志", [])
                entries = result.get("results", [])
                if not isinstance(entries, list) or any(
                    not isinstance(item, dict) for item in entries
                ):
                    raise SearchError("搜索结果结构无效，请重新测试", [])
                return {
                    **scope,
                    "success": True,
                    "kind": kind,
                    "value": value,
                    "result": result,
                    "count": len(entries),
                    "title": result.get("title")
                    or (entries[0].get("title", "") if entries else ""),
                    "elapsedMs": round((time.monotonic() - started) * 1000),
                }
            except ValueError as error:
                if not permit():
                    raise asyncio.CancelledError()
                return {
                    **scope,
                    "success": False,
                    "kind": kind,
                    "value": value,
                    "message": str(error),
                    "attempts": error.attempts if isinstance(error, SearchError) else [],
                    "elapsedMs": round((time.monotonic() - started) * 1000),
                }

        return self._business(
            test,
            cancel_code="CONFIG_CHANGED" if account is None else "ACCOUNT_CHANGED",
            cancel_message="配置或账号已变化，搜索测试已停止",
        )

    def get_sessions(self, limit=200):
        def read():
            account = self._active_account()
            return {
                "account": account,
                "items": self._sessions.list(account, limit) if account and self._sessions else [],
            }

        return self._business(read)

    def get_session(self, identifier):
        def read():
            account = self._account()
            return {
                "account": account,
                "session": self._sessions.get(account, identifier) if self._sessions else None,
            }

        return self._business(read)

    def delete_session(self, identifier=None, account=None):
        def delete():
            if not isinstance(account, str):
                raise ValueError("请刷新页面后确认操作账号")
            selected = self._account(account)
            if not self._sessions:
                raise ValueError("会话记录尚未就绪")
            return {"account": selected, "deleted": self._sessions.delete(selected, identifier)}

        return self._business(delete)

    def get_usage(self):
        def read():
            account = self._active_account()
            return {
                "account": account,
                "usage": self._sessions.usage(account) if account and self._sessions else None,
            }

        return self._business(read)

    def get_memory_chats(self):
        def read():
            account = self._active_account()
            return {
                "account": account,
                "items": self._memory.chats(account) if account and self._memory else [],
            }

        return self._business(read)

    def get_memories(self, key):
        def read():
            account = self._account()
            return {
                "account": account,
                "chatKey": key,
                "members": self._memory.members(account, key) if self._memory else [],
            }

        return self._business(read)

    def save_memory(self, key, user, target, values, account):
        def save():
            if not isinstance(account, str):
                raise ValueError("请刷新页面后确认操作账号")
            selected = self._account(account)
            if not self._memory:
                raise ValueError("记忆模块尚未就绪")
            agent = self._agent
            if agent:
                agent.pause_for_data_change(selected)
            return {
                "account": selected,
                "saved": self._memory.replace(selected, key, user, target, values),
            }

        return self._business(save)

    def delete_memory(self, key=None, user=None, account=None):
        def delete():
            if not isinstance(account, str):
                raise ValueError("请刷新页面后确认操作账号")
            selected = self._account(account)
            if not self._memory:
                raise ValueError("记忆模块尚未就绪")
            agent = self._agent
            if agent:
                agent.pause_for_data_change(selected)
            return {"account": selected, "deleted": self._memory.delete(selected, key, user)}

        return self._business(delete)

    def preview_memory(self, key, user, account):
        def preview():
            if not isinstance(account, str):
                raise ValueError("请刷新页面确认账号")
            selected = self._account(account)
            if self._memory is None or self._messages is None or self._settings is None:
                raise ValueError("记忆模块尚未就绪")
            result = self._reviews.preview(
                self._memory,
                self._messages,
                self._settings,
                selected,
                key,
                user,
                lambda: self._active_account() == selected,
            )
            self._account(selected)
            return {"account": selected, "preview": result}

        return self._business(preview)

    def apply_memory_preview(self, key, user, token, values, account):
        def apply():
            if not isinstance(account, str):
                raise ValueError("请刷新页面确认账号")
            selected = self._account(account)
            if self._memory is None:
                raise ValueError("记忆模块尚未就绪")
            agent = self._agent
            if agent:
                agent.pause_for_data_change(selected)
            return {
                "account": selected,
                "saved": self._reviews.apply(
                    self._memory,
                    selected,
                    key,
                    user,
                    token,
                    values,
                    lambda: self._active_account() == selected,
                ),
            }

        return self._business(apply)

    def get_storage(self):
        return self._business(lambda: self._storage.overview())

    def save_storage_settings(self, settings):
        return self._business(lambda: self._storage.save(settings))

    def cleanup_storage(self, request):
        def clean():
            result = self._storage.cleanup(request)
            self._reviews.invalidate()
            return result

        return self._business(clean)

    def get_logs(self):
        def read():
            account = self._active_account()
            config = (
                self._global_settings.read()
                if self._global_settings is not None
                else self._settings.read(account)
                if account and self._settings
                else None
            )
            keys = (
                [config["api"]["apiKey"], *(p["api"]["apiKey"] for p in config["profiles"])]
                if config
                else []
            )
            try:
                entries = read_log_entries(self._paths, keys)
            except OSError:
                raise ValueError("运行日志暂时无法读取，请稍后刷新") from None
            return {"lines": [entry["text"] for entry in entries], "entries": entries}

        return self._business(read)

    def get_stickers(self, query, account):
        def read():
            if not isinstance(account, str):
                raise ValueError("请刷新页面确认机器人账号")
            selected = self._account(account)
            if self._stickers is None:
                raise ValueError("表情库尚未就绪")
            result = self._stickers.list(selected, query)
            self._account(selected)
            return {"account": selected, "items": result, "limit": 200}

        return self._business(read)

    def get_sticker_preview(self, item, account):
        def read():
            if not isinstance(account, str):
                raise ValueError("请刷新页面确认机器人账号")
            selected = self._account(account)
            if self._stickers is None:
                raise ValueError("表情库尚未就绪")
            image = self._stickers.get(selected, item)
            self._account(selected)
            return {
                "account": selected,
                "item": image["meta"],
                "image": image["part"]["image_url"]["url"],
            }

        return self._business(read)

    def save_sticker(self, item, note, tags, usage, account):
        def save():
            if not isinstance(account, str):
                raise ValueError("请刷新页面确认机器人账号")
            selected = self._account(account)
            if self._stickers is None:
                raise ValueError("表情库尚未就绪")
            # 与工具侧 sticker_note 口径一致：改备注不影响进行中的自动回复，
            # 不需要为此全局暂停（发送前的 matches 许可按实时数据校验）。
            return {
                "account": selected,
                "item": self._stickers.note(selected, item, note, tags, usage),
            }

        return self._business(save)

    def delete_sticker(self, item, account):
        def delete():
            if not isinstance(account, str):
                raise ValueError("请刷新页面确认机器人账号")
            selected = self._account(account)
            if self._stickers is None:
                raise ValueError("表情库尚未就绪")
            if self._agent:
                self._agent.pause("表情库已调整，请确认后重新开启自动回复")
            return {"account": selected, "deleted": self._stickers.delete(selected, item)}

        return self._business(delete)

    def expand_forward(self, key, mid, account):
        def expand():
            if not isinstance(account, str):
                raise ValueError("请刷新页面确认机器人账号")
            selected = self._account(account)
            if self._messages is None or self._settings is None:
                raise ValueError("聊天存档尚未就绪")
            original = self._messages.message_detail(selected, key, mid)

            def admitted(user):
                kind, peer = key.split(":")
                return allowed(kind, peer, user, self._settings.read(selected))

            def permit():
                if self._active_account() != selected:
                    return False
                try:
                    current = self._messages.message_detail(selected, key, mid)
                    return current["id"] == original["id"] and admitted(current["senderId"])
                except ValueError:
                    return False

            async def native(action, params):
                def read():
                    with self._agent.native_lock if self._agent else self._native_fallback_lock:
                        if not permit():
                            raise ValueError("账号或消息已变化，未读取转发")
                        return self._connection.invoke(action, params, expected_account=selected)

                try:
                    return await asyncio.to_thread(read)
                except EngineError as error:
                    raise ValueError("QQ 转发读取失败，请确认连接或重新发送") from error

            if not permit():
                raise ValueError("只能展开当前白名单内未撤回的转发")
            query = MessageQueries(self._messages, native, lambda _: None, permit, admitted)
            result = asyncio.run(query.execute("read_forward", selected, key, {"messageId": mid}))
            self._account(selected)
            return {"account": selected, **result}

        return self._business(
            expand, cancel_code="SOURCE_CHANGED", cancel_message="账号或消息已变化，展开已停止"
        )

    def collect_sticker(self, key, mid, account):
        def collect():
            if not isinstance(account, str):
                raise ValueError("请刷新页面确认机器人账号")
            selected = self._account(account)
            if self._stickers is None or self._messages is None or self._settings is None:
                raise ValueError("表情库尚未就绪")
            original = self._messages.image_message(selected, key, mid)

            def permit():
                if self._active_account() != selected:
                    return False
                try:
                    source = self._messages.image_message(selected, key, mid)
                    kind, peer = key.split(":")
                    return source["id"] == original["id"] and allowed(
                        kind, peer, source["senderId"], self._settings.read(selected)
                    )
                except ValueError:
                    return False

            async def native(a, k, identifier):
                def read():
                    with self._agent.native_lock if self._agent else self._native_fallback_lock:
                        if not permit():
                            raise ValueError("账号或图片消息已变化，未读取图片")
                        return self._connection.invoke(
                            "get_msg", {"message_id": identifier}, expected_account=selected
                        )

                return await asyncio.to_thread(read)

            if not permit():
                raise ValueError("只能收藏当前账号白名单中未撤回的聊天图片")
            result = asyncio.run(
                collect_message(self._stickers, self._messages, native, permit, selected, key, mid)
            )
            self._account(selected)
            return {"account": selected, "item": result}

        return self._business(
            collect, cancel_code="SOURCE_CHANGED", cancel_message="账号或图片消息已变化，收藏已停止"
        )

    def import_sticker(self, data, note, tags, usage, account):
        """手动导入本地图片到表情库：base64 原始文件字节，清洗与收藏同一管线。"""

        def save():
            if not isinstance(account, str):
                raise ValueError("请刷新页面确认机器人账号")
            selected = self._account(account)
            if self._stickers is None:
                raise ValueError("表情库尚未就绪")
            if not isinstance(data, str) or not data:
                raise ValueError("请先选择图片文件")
            if len(data) > 20 * 1024 * 1024:
                raise ValueError("图片文件超过 20 MB 上限")
            try:
                raw = base64.b64decode(data, validate=True)
            except ValueError as error:
                raise ValueError("图片数据无效，请重新选择文件") from error
            prepared = prepare_image(raw)
            self._account(selected)
            return {
                "account": selected,
                "item": self._stickers.add(selected, prepared, note, tags, usage, source=None),
            }

        return self._business(save)

    def get_diagnostics(self):
        def read():
            account = self._active_account()
            config = (
                self._settings.read(account, public=True) if account and self._settings else None
            )
            return {
                "account": account,
                "connection": self.get_qq_status(),
                "agent": self.get_agent_status(),
                "configuration": {
                    "model": config["api"]["model"],
                    "hasEndpoint": bool(config["api"]["baseUrl"]),
                    "hasKey": config["api"]["apiKeyConfigured"],
                    "allowedGroups": len(config["allow"]["groups"]),
                    "allowedPrivate": len(config["allow"]["private"]),
                }
                if config
                else None,
                "usage": self._sessions.usage(account) if account and self._sessions else None,
            }

        return self._business(read)

    def open_project_page(self, project):
        """Open only fixed official project websites in the system browser."""
        pages = {
            "python": "https://www.python.org/",
            "node": "https://nodejs.org/",
            "snowluma": "https://snowluma.github.io/",
            "author": "https://github.com/sycahiro",
            "repo": "https://github.com/sycahiro/QQBot",
            "issues": "https://github.com/sycahiro/QQBot/issues",
        }

        def launch():
            if not isinstance(project, str) or project not in pages:
                raise ValueError("未知的项目")
            url = pages[project]
            try:
                opened = webbrowser.open(url, new=2)
            except (webbrowser.Error, OSError):
                opened = False
            if not opened:
                raise ValueError("无法打开系统浏览器，请检查浏览器设置")
            return {"url": url}

        return self._business(launch)
