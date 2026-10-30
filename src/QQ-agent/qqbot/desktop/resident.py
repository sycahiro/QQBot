"""个人桌面驻留选项；启动项仅写当前用户，托盘使用现有 WinForms。"""

import ctypes
import hashlib
import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

from .appearance import Appearance, appearance_file
from .paths import adopt, save_state

DEFAULTS = {"trayEnabled": False, "startup": False}


class UserStartup:
    def __init__(self, paths):
        self.name = (
            "QQBot.Desktop."
            + hashlib.sha256(
                (str(paths.root) + "|" + str(paths.runtime)).casefold().encode()
            ).hexdigest()[:12]
        )
        self.entry = paths.entry
        prefix = [
            str(Path(sys.executable).with_name("pythonw.exe")),
            "-B",
            str(self.entry),
            "--no-dialog",
        ]
        suffix = ["--runtime", str(paths.runtime)]
        self.command = subprocess.list2cmdline(prefix + suffix)

    def enabled(self):
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"
            ) as key:
                value = winreg.QueryValueEx(key, self.name)[0]
                # Older releases registered a dead entry path; treat those as off
                # so the UI never claims autostart works when it would not.
                return value == self.command and self.entry.exists()
        except FileNotFoundError:
            return False

    def set(self, enabled):
        import winreg

        if enabled and not self.entry.exists():
            raise ValueError(f"启动入口不存在，无法开启开机自启：{self.entry}")

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            if enabled:
                winreg.SetValueEx(key, self.name, 0, winreg.REG_SZ, self.command)
            else:
                try:
                    winreg.DeleteValue(key, self.name)
                except FileNotFoundError:
                    pass


class TrayIcon:
    def __init__(self, icon, show, exit_app, theme=lambda: "system"):
        self._icon, self._show, self._exit = icon, show, exit_app
        self._theme = theme
        self._ready, self._closing, self._stopped = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        self._thread = None
        self._error = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="desktop-tray", daemon=True)
        self._thread.start()
        if not self._ready.wait(5) or self._error:
            self.close()
            raise ValueError("托盘图标未就绪，窗口仍按正常方式关闭，请查看日志")

    @property
    def ready(self):
        return (
            self._ready.is_set()
            and not self._closing.is_set()
            and not self._stopped.is_set()
            and self._error is None
        )

    def _run(self):
        initialized = False
        notify = image = context = menu = timer = None
        try:
            initialized = ctypes.windll.ole32.CoInitializeEx(None, 2) in (0, 1)
            import clr

            clr.AddReference("System.Windows.Forms")
            clr.AddReference("System.Drawing")
            from System.Drawing import Icon
            from System.Windows.Forms import (
                Application,
                ApplicationContext,
                MouseButtons,
                NotifyIcon,
                Timer,
            )

            from .tray_menu import TrayMenu

            context = ApplicationContext()
            menu = TrayMenu(self._show, self._exit, self._theme)
            image = Icon(str(self._icon))
            notify = NotifyIcon()
            notify.Icon = image
            notify.Text = "QQBot"
            notify.MouseUp += lambda _, event: (
                menu.show() if event.Button == MouseButtons.Right else None
            )
            notify.DoubleClick += lambda *_: self._show()
            # A WinForms timer runs on this owning UI thread. Shutdown needs no
            # cross-thread Invoke or control handle (which may already be gone).
            timer = Timer()
            timer.Interval = 50
            timer.Tick += lambda *_: context.ExitThread() if self._closing.is_set() else None
            timer.Start()
            notify.Visible = True
            self._ready.set()
            if not self._closing.is_set():
                Application.Run(context)
        except Exception as error:
            self._error = error
            logging.exception("托盘初始化失败")
            self._ready.set()
        finally:
            try:
                for resource in (timer, notify, menu, image, context):
                    if resource is None:
                        continue
                    try:
                        if resource is timer:
                            resource.Stop()
                        if resource is notify:
                            resource.Visible = False
                        if resource is menu:
                            resource.close()
                        else:
                            resource.Dispose()
                    except Exception:
                        logging.exception("托盘资源释放失败")
            finally:
                try:
                    if initialized:
                        ctypes.windll.ole32.CoUninitialize()
                finally:
                    self._stopped.set()

    def close(self):
        self._closing.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)


class Residence:
    def __init__(self, paths, *, startup=None, tray_factory=TrayIcon):
        self._file, self._icon = adopt(
            paths.runtime / "settings" / "preferences.json", paths.runtime / "preferences.json"
        ), paths.icon
        self._startup = startup or UserStartup(paths)
        self._factory, self._tray, self._window = tray_factory, None, None
        self._lock = threading.RLock()
        self._operations = threading.RLock()
        self._exiting = False
        self._prompting = False
        self._prompt_checked_at = 0.0
        self._prompt_checking = False
        self._ui_ready = False
        self._prompt_thread = None
        self._appearance = Appearance(appearance_file(paths.runtime))
        self._options = dict(DEFAULTS)
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text(encoding="utf-8"))
                # Previous versions silently hid the window; that preference is retired.
                if isinstance(data, dict):
                    data = {key: value for key, value in data.items() if key != "closeToTray"}
                self._validate(data)
                self._options = data
            except (OSError, ValueError, TypeError):
                logging.exception(
                    "桌面驻留设置损坏或无法读取，使用默认设置；原文件保留：%s", self._file
                )

    @staticmethod
    def _validate(options):
        if (
            not isinstance(options, dict)
            or set(options) != set(DEFAULTS)
            or any(type(v) is not bool for v in options.values())
        ):
            raise ValueError("桌面驻留设置格式无效")

    def read(self):
        with self._lock:
            return {
                **self._options,
                "startup": self._startup.enabled(),
                "trayReady": self._tray is not None and self._tray.ready,
            }

    def attach(self, window):
        self._window = window
        window.events.closing += self.on_closing
        window.events.shown += self._on_shown

    def _on_shown(self):
        try:
            with self._operations:
                with self._lock:
                    needed = (
                        self._options["trayEnabled"] and self._tray is None and not self._exiting
                    )
                if needed:
                    self._start_tray()
        except ValueError:
            logging.exception("托盘不可用；仍可在关闭选择框退出")

    def _start_tray(self):
        # Operations serialize changes, but never hold the state lock while a
        # tray thread starts/joins: its show/exit callbacks need that lock.
        with self._lock:
            if self._window is None:
                raise ValueError("窗口尚未就绪")
            if self._exiting:
                raise ValueError("应用正在退出")
        tray = self._factory(self._icon, self.show, self.exit, self._appearance.read)
        tray.start()
        with self._lock:
            exiting = self._exiting
            if not exiting:
                self._tray = tray
        if exiting:
            tray.close()
            raise ValueError("应用正在退出")

    def _drop_tray(self):
        with self._lock:
            tray, self._tray = self._tray, None
        if tray:
            tray.close()

    def save(self, options):
        self._validate(options)
        with self._operations:
            with self._lock:
                if self._exiting:
                    raise ValueError("应用正在退出")
                stale = self._tray is not None and not self._tray.ready
            old_startup = self._startup.enabled()
            if stale:
                self._drop_tray()
            with self._lock:
                created = options["trayEnabled"] and self._tray is None
            if created:
                self._start_tray()
            try:
                if options["startup"] != old_startup:
                    self._startup.set(options["startup"])
                save_state(self._file, options)
            except Exception:
                try:
                    if self._startup.enabled() != old_startup:
                        self._startup.set(old_startup)
                finally:
                    if created:
                        self._drop_tray()
                raise
            with self._lock:
                self._options = dict(options)
            if not options["trayEnabled"]:
                self._drop_tray()
            return self.read()

    def on_closing(self):
        with self._lock:
            if self._exiting or not self._ui_ready:
                return True
            if self._prompting:
                if not self._prompt_checking and time.monotonic() - self._prompt_checked_at >= 2:
                    self._prompt_checking = True
                    self._prompt_thread = threading.Thread(
                        target=self._check_prompt, name="desktop-close-health", daemon=True
                    )
                    self._prompt_thread.start()
                return False
            self._prompting = True
            self._prompt_checked_at = time.monotonic()
        # WinForms invokes closing synchronously on its UI thread. evaluate_js
        # needs that same thread; dispatch only after returning Cancel=True.
        self._prompt_thread = threading.Thread(
            target=self._request_close, name="desktop-close-prompt", daemon=True
        )
        self._prompt_thread.start()
        return False

    def mark_ready(self):
        with self._lock:
            self._ui_ready = True

    def _request_close(self):
        try:
            # The native close has already been cancelled. If no dialog is
            # mounted, leave through the normal shutdown path instead.
            shown = self._window.evaluate_js(
                "typeof window.__qqbotRequestClose === 'function' && window.__qqbotRequestClose()"
            )
            if shown is True:
                return
        except Exception:
            logging.exception("关闭选择框不可用，正常退出")
        with self._lock:
            self._prompting = False
        self.exit()

    def _check_prompt(self):
        present = False
        try:
            present = (
                self._window.evaluate_js("typeof window.__qqbotRequestClose === 'function'") is True
            )
        except Exception:
            logging.exception("关闭选择框已不可用，正常退出")
        finally:
            with self._lock:
                self._prompt_checked_at = time.monotonic()
                self._prompt_checking = False
                should_exit = self._prompting and not self._exiting and not present
                if should_exit:
                    self._prompting = False
        if should_exit:
            self.exit()

    def resolve_close(self, action):
        if action not in ("cancel", "hide", "exit"):
            raise ValueError("无效的窗口关闭操作")
        with self._operations:
            with self._lock:
                if self._exiting or not self._prompting:
                    raise ValueError("窗口关闭请求已结束")
                stale = self._tray is not None and not self._tray.ready
            if action == "hide":
                if stale:
                    self._drop_tray()
                with self._lock:
                    needed = self._tray is None
                if needed:
                    self._start_tray()
                with self._lock:
                    if self._exiting:
                        raise ValueError("应用正在退出")
                    if not self._tray.ready:
                        raise ValueError("托盘不可用，请选择退出或取消")
                self._window.hide()
            with self._lock:
                self._prompting = False
                if action == "exit":
                    self._exiting = True
        if action == "exit" and self._window:
            self._window.destroy()
        return {"action": action}

    def show(self):
        if self._window and not self._exiting:
            self._window.restore()
            self._window.show()

    def exit(self):
        with self._lock:
            self._exiting = True
        if self._window:
            self._window.destroy()

    def close(self):
        with self._lock:
            self._exiting = True
            tray, self._tray = self._tray, None
        if tray:
            tray.close()
