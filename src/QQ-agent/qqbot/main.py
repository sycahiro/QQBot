"""桌面启动入口：互斥量 → 内存页面 → 窗口 → 有序退出。"""

import argparse
import ctypes
import logging
import os
import sys
import threading
from importlib.metadata import PackageNotFoundError, metadata

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from .agent.global_settings import GlobalSettings
from .agent.receiver import Receiver
from .agent.service import AgentService
from .desktop.appearance import Appearance
from .desktop.bridge import DesktopBridge
from .desktop.debug import Activity
from .desktop.frame import WindowFrame
from .desktop.frontend import FrontendDocument
from .desktop.paths import DesktopPaths, save_state
from .desktop.resident import Residence
from .desktop.windows import SingleInstance, ensure_shortcut, set_application_identity
from .qq.connection import QqConnection
from .qq.selection import AccountSelection
from .qq.snowluma import SnowLumaDiscovery, SnowLumaEngine
from .storage.accounts import AccountStorage


def check_python_version(version=None):
    version = version or sys.version.split()[0]
    if tuple(int(part) for part in version.split(".")[:2]) < (3, 14):
        raise RuntimeError("需要 Python 3.14 或更新版本，请使用项目自带的 tools\\python\\python.exe")
    try:
        requires = metadata("pythonnet").get("Requires-Python")
        if not requires:
            raise ValueError("缺少 Requires-Python")
        supported = SpecifierSet(requires).contains(version, prereleases=True)
    except (PackageNotFoundError, InvalidSpecifier, ValueError) as error:
        raise RuntimeError("无法读取 pythonnet 支持的 Python 版本，请重新安装项目依赖") from error
    if not supported:
        raise RuntimeError(f"当前 Python {version} 不符合已安装 pythonnet 的版本要求 {requires}")


def _watch_window(paths, window, bridge, stopped):
    focus = paths.runtime / "focus.request"
    delay = 0.25
    failures = 0
    while not stopped.wait(delay):
        failed = False
        for operation in ("prune", "focus"):
            try:
                if operation == "prune":
                    if bridge:
                        bridge._debug_files.prune()
                        bridge._storage.sweep()
                elif focus.exists():
                    ticket = focus.read_bytes()
                    window.restore()
                    window.show()
                    if focus.exists() and focus.read_bytes() == ticket:
                        focus.unlink(missing_ok=True)
            except Exception:
                failed = True
                if failures == 0 or failures % 12 == 0:
                    logging.exception("窗口后台检查失败：%s；稍后继续检查", operation)
        failures = failures + 1 if failed else 0
        delay = min(5, delay * 2) if failed else 0.25


def run(paths):
    instance = SingleInstance(paths.root, paths.runtime)
    try:
        if not instance.primary:
            instance.request_focus()
            logging.info("QQBot 已运行，已请求显示现有窗口")
            return 0
        (paths.runtime / "focus.request").unlink(missing_ok=True)
        return run_primary(paths)
    finally:
        instance.close()


def _cleanup(resources):
    """Release every owned resource, preserving the original failure if any."""
    original = sys.exception()
    failure = None
    for label, close in resources:
        try:
            close()
        except Exception as error:
            logging.exception("退出时释放%s失败，继续清理其他资源", label)
            if failure is None:
                failure = error
    if failure is not None and original is None:
        raise failure


def run_primary(paths):
    import webview

    state = {
        "pid": os.getpid(),
        "phase": "starting",
        "uiReady": False,
        "frontendMode": "embedded",
        "qqConnected": False,
        "modelEnabled": False,
    }
    state_lock = threading.Lock()

    def update(**changes):
        with state_lock:
            state.update(changes)
            save_state(paths.runtime / "state.json", state)

    update()
    document = FrontendDocument(paths)
    discovery = SnowLumaDiscovery(paths)
    selection = AccountSelection(paths.runtime / "account.json")
    database = connection = agent = None
    activity = Activity()
    stopped = threading.Event()
    window = None
    watcher = None
    residence = None
    bridge = None
    try:
        global_settings = GlobalSettings(paths.runtime)
        database = AccountStorage(paths.runtime / "accounts", global_settings=global_settings)
        messages, settings = database.messages, database.settings
        sessions, memory = database.sessions, database.memory
        def connection_status(status):
            update(qqConnected=status["connected"])
            activity.add((status.get("account") or {}).get("uin"), "connection", status["state"])
            if agent and not status["connected"]:
                agent.pause()
            if bridge and not status["connected"]:
                bridge._debug_files.clear()
                bridge._reviews.invalidate()

        def receive_event(account, event):
            item = receiver.receive(account, event)
            if item:
                activity.add(
                    account, "message", f"{item['chatKey']} · {item['senderName']}: {item['text']}"
                )

        connection = QqConnection(
            paths,
            discovery,
            selection,
            # 引擎每次连接新建，但 SnowLuma 服务是全局单例（discovery 持有），随应用退出统一回收。
            engine_factory=lambda _paths: SnowLumaEngine(paths, service=discovery.service),
            on_status=connection_status,
            on_event=receive_event,
        )
        agent = AgentService(
            settings,
            messages,
            sessions,
            connection,
            memory=memory,
            stickers=database.stickers,
            on_status=lambda status: update(modelEnabled=status["enabled"]),
        )
        receiver = Receiver(settings, messages, agent)
        set_application_identity()
        ensure_shortcut(paths)
        page = document.prepare(Appearance(paths.runtime).read())
        residence = Residence(paths)
        frame = WindowFrame()
        update(frontendPid=None, phase="opening")
        webview.settings["ALLOW_FILE_URLS"] = False
        bridge = DesktopBridge(
            paths,
            update,
            discovery,
            connection,
            selection,
            messages,
            settings,
            agent,
            sessions,
            memory,
            activity,
            stickers=database.stickers,
            residence=residence,
            global_settings=global_settings,
            frame=frame,
            accounts=database,
        )
        window = webview.create_window(
            "QQBot",
            html=page,
            js_api=bridge,
            width=1520,
            height=980,
            min_size=(1080, 720),
            text_select=True,
            easy_drag=False,
            shadow=True,
            background_color="#f8fbfd",
        )
        if window is None:
            raise RuntimeError("桌面窗口未创建")
        residence.attach(window)
        frame.attach(window)
        window.events.shown += lambda: update(phase="running")
        window.events.closed += lambda: stopped.set()

        watcher = threading.Thread(
            target=_watch_window,
            args=(paths, window, bridge, stopped),
            name="desktop-watch",
            daemon=True,
        )
        watcher.start()
        webview.start(
            gui="edgechromium",
            private_mode=False,
            http_server=False,
            storage_path=str(paths.runtime / "webview-profile"),
            debug=False,
            icon=str(paths.icon),
        )
        return 0
    except Exception as error:
        update(phase="failed", error=str(error), uiReady=False)
        raise
    finally:
        stopped.set()

        def finish_state():
            update(
                phase="failed" if state["phase"] == "failed" else "stopped",
                frontendPid=None,
                uiReady=False,
                qqConnected=False,
                modelEnabled=False,
            )

        resources = []
        if bridge:
            resources.extend(
                [("记忆预览", bridge._reviews.close), ("调试附件", bridge._debug_files.close)]
            )
        if residence:
            resources.append(("托盘", residence.close))
        if watcher:
            resources.append(("窗口观察线程", lambda: watcher.join(timeout=2)))
        for label, resource in [
            ("机器人", agent),
            ("QQ 连接", connection),
            ("QQ 检测", discovery),
            ("前端", document),
            ("账号数据库", database),
        ]:
            if resource:
                resources.append((label, resource.close))
        resources.append(("窗口状态", finish_state))
        _cleanup(resources)


def main():
    parser = argparse.ArgumentParser(description="QQBot 桌面窗口")
    # Old saved Windows startup commands may contain this flag. It is ignored;
    # the desktop never starts an HTTP listener, including during startup.
    parser.add_argument("--port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--foreground", action="store_true", help="将启动错误输出到当前终端")
    parser.add_argument("--runtime", help=argparse.SUPPRESS)
    parser.add_argument("--no-dialog", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    paths = DesktopPaths.discover(args.runtime)
    paths.runtime.mkdir(parents=True, exist_ok=True)
    paths.logs.mkdir(parents=True, exist_ok=False)
    log_file = paths.logs / "desktop.log"
    handler = logging.FileHandler(log_file, mode="x", encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    # pythonw 没有终端，将第三方异常输出也保存在本应用的数据目录。
    logging.info("QQBot 启动")
    stream = None
    original_stderr, original_stdout = sys.stderr, sys.stdout
    if sys.stderr is None or sys.stdout is None:
        stream = (paths.logs / "launcher.log").open("x", encoding="utf-8", buffering=1)
        sys.stderr = sys.stderr or stream
        sys.stdout = sys.stdout or stream
    try:
        if sys.platform != "win32":
            raise RuntimeError("本应用只支持 Windows")
        check_python_version()
        return run(paths)
    except Exception as error:
        logging.exception("QQBot 启动或运行失败")
        if not args.no_dialog:
            ctypes.windll.user32.MessageBoxW(
                None,
                str(error)
                + "\n\n原配置和数据已保留。请检查上述错误，修复后重新启动。\n本次详细日志："
                + str(log_file),
                "QQBot 启动失败",
                0x10,
            )
        else:
            print(str(error), file=sys.stderr)
        return 1
    finally:
        logging.info("QQBot 本次运行结束")
        logging.shutdown()
        if stream:
            sys.stderr, sys.stdout = original_stderr, original_stdout
            stream.close()
