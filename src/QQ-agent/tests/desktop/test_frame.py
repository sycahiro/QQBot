import ctypes
import sys
from ctypes import wintypes
from types import SimpleNamespace

import pytest
from qqbot.desktop.bridge import DesktopBridge
from qqbot.desktop.frame import WindowFrame
from qqbot.desktop.paths import DesktopPaths


def test_controls_are_explicit_and_close_uses_normal_window_lifecycle(tmp_path):
    frame = WindowFrame()
    calls = []
    maximized = [False]

    def change(value):
        maximized[0] = value

    frame._hwnd = 1
    frame._user = SimpleNamespace(IsZoomed=lambda _: maximized[0])
    frame._window = SimpleNamespace(
        destroy=lambda: calls.append("close"),
        minimize=lambda: calls.append("minimize"),
        maximize=lambda: change(True),
        restore=lambda: change(False),
    )
    assert frame.control("toggle_maximize") == {"maximized": True}
    assert frame.control("toggle_maximize") == {"maximized": False}
    frame.control("minimize")
    frame.control("close")
    assert calls == ["minimize", "close"]
    for value in [None, "execute", "resize_unknown", {}, True]:
        with pytest.raises(ValueError):
            frame.control(value)
    bridge = DesktopBridge(DesktopPaths(tmp_path, tmp_path), lambda **_: None, frame=frame)
    try:
        assert bridge.window_control("state") == {"ok": True, "maximized": False}
        assert not bridge.window_control("execute")["ok"]
    finally:
        bridge._reviews.close()
        bridge._debug_files.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native frame")
def test_hidden_native_frame_removes_caption_preserves_resize_and_unhooks_on_destroy():
    import clr

    clr.AddReference("System.Windows.Forms")
    from System.Windows.Forms import Form

    form = Form()
    frame = WindowFrame()
    handle = form.Handle.ToInt64()
    try:
        before = form.Height - form.ClientSize.Height
        assert before > 0
        frame._install(handle)
        assert form.ClientSize.Height == form.Height
        assert form.ClientSize.Width == form.Width
        rect = wintypes.RECT()
        frame._user.GetWindowRect(handle, ctypes.byref(rect))

        def hit(x, y):
            return frame._user.SendMessageW(handle, 0x84, 0, (x & 0xFFFF) | ((y & 0xFFFF) << 16))

        assert hit(rect.left + 1, rect.top + 1) == 13
        assert hit(rect.right - 1, rect.bottom - 1) == 17
        assert hit(rect.left + form.Width // 2, rect.top + form.Height // 2) == 1
        # Style bits that power native sizing/system menu/docking remain intact.
        get_style = ctypes.windll.user32.GetWindowLongW
        get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        assert get_style(handle, -16) & 0x40000  # WS_THICKFRAME
        assert get_style(handle, -16) & 0x80000  # WS_SYSMENU
    finally:
        form.Dispose()
    assert frame._hwnd is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native frame")
def test_initial_window_is_fitted_inside_monitor_work_area_without_showing_it():
    import clr

    clr.AddReference("System.Windows.Forms")
    from System.Drawing import Size
    from System.Windows.Forms import Form, Screen

    form = Form()
    frame = WindowFrame()
    try:
        form.Size = Size(8000, 6000)
        frame._window = SimpleNamespace(native=form)
        frame._install(form.Handle.ToInt64())
        frame._fit_initial_bounds()
        area = Screen.FromControl(form).WorkingArea
        assert area.Contains(form.Bounds)
        assert form.Width <= area.Width and form.Height <= area.Height
        assert form.MinimumSize.Width <= form.Width and form.MinimumSize.Height <= form.Height
    finally:
        form.Dispose()
