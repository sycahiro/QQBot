"""Exercise actual pythonnet controls without displaying or operating the tray."""

import sys
import threading
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native controls")
def test_real_menu_constructs_themes_and_wires_both_callbacks():
    import clr

    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from qqbot.desktop.tray_menu import TrayMenu
    from System import Array, EventArgs, Object
    from System.Reflection import BindingFlags

    preference = ["light"]
    calls = []
    menu = TrayMenu(
        lambda: calls.append("show"), lambda: calls.append("exit"), lambda: preference[0]
    )
    try:
        menu._apply_theme()
        light = menu._form.BackColor.GetBrightness()
        assert menu._form.Region is not None and not menu._form.ShowInTaskbar
        assert menu._form.ClientSize.Width >= 220
        assert [button.Text for button in menu._buttons] == ["打开工作台", "退出 QQBot"]
        preference[0] = "dark"
        menu._apply_theme()
        assert menu._form.BackColor.GetBrightness() < light
        assert menu._buttons[0].ForeColor.GetBrightness() > menu._form.BackColor.GetBrightness()
        # PerformClick intentionally ignores invisible controls. Raise the real
        # managed Click event without putting a test form on the user's screen.
        for button in menu._buttons:
            button.GetType().GetMethod(
                "OnClick", BindingFlags.Instance | BindingFlags.NonPublic
            ).Invoke(button, Array[Object]([EventArgs.Empty]))
        assert calls == ["show", "exit"]
    finally:
        menu.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native controls")
def test_real_tray_repeated_close_releases_thread_without_invoking_disposed_controls(caplog):
    from qqbot.desktop.resident import TrayIcon

    icon = Path(__file__).resolve().parents[4] / "src" / "DesktopShell" / "frontend" / "public" / "qqbot.ico"
    calls = []
    for _ in range(3):
        tray = TrayIcon(icon, lambda: calls.append("show"), lambda: calls.append("exit"))
        try:
            tray.start()
            assert tray.ready
            tray.close()
            assert not tray.ready and tray._stopped.is_set() and not tray._thread.is_alive()
            tray.close()  # Reported failure: the dispatch control was already disposed.
        finally:
            tray.close()
    assert not calls and not caplog.records


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native controls")
def test_real_tray_close_during_initialization_never_leaves_a_message_loop(caplog):
    from qqbot.desktop.resident import TrayIcon

    entered = threading.Event()
    release = threading.Event()
    errors = []

    class DelayedTray(TrayIcon):
        def _run(self):
            entered.set()
            if not release.wait(3):
                return
            super()._run()

    icon = Path(__file__).resolve().parents[4] / "src" / "DesktopShell" / "frontend" / "public" / "qqbot.ico"
    tray = DelayedTray(icon, lambda: None, lambda: None)

    def start():
        try:
            tray.start()
        except Exception as error:
            errors.append(error)

    starter = threading.Thread(target=start)
    closer = threading.Thread(target=tray.close)
    try:
        starter.start()
        assert entered.wait(2)
        closer.start()
        assert tray._closing.wait(2)
        release.set()
        starter.join(5)
        closer.join(5)
        assert not starter.is_alive() and not closer.is_alive()
        assert (
            not errors and not tray.ready and tray._stopped.is_set() and not tray._thread.is_alive()
        )
    finally:
        release.set()
        tray.close()
        starter.join(5)
        if closer.ident is not None:
            closer.join(5)
    assert not caplog.records


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native controls")
def test_real_tray_concurrent_shutdown_is_idempotent(caplog):
    from qqbot.desktop.resident import TrayIcon

    icon = Path(__file__).resolve().parents[4] / "src" / "DesktopShell" / "frontend" / "public" / "qqbot.ico"
    tray = TrayIcon(icon, lambda: None, lambda: None)
    closers = []
    try:
        tray.start()
        closers = [threading.Thread(target=tray.close) for _ in range(4)]
        for thread in closers:
            thread.start()
        for thread in closers:
            thread.join(5)
        assert all(not thread.is_alive() for thread in closers)
        assert tray._stopped.is_set() and not tray._thread.is_alive() and not tray.ready
    finally:
        tray.close()
        for thread in closers:
            thread.join(5)
    assert not caplog.records
