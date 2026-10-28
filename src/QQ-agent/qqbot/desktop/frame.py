"""Custom HTML caption over a native resizable Windows frame, only for our window."""

import ctypes
from ctypes import wintypes


class WindowFrame:
    EDGES = {"n": 12, "s": 15, "w": 10, "e": 11, "nw": 13, "ne": 14, "sw": 16, "se": 17}

    def __init__(self):
        self._window = None
        self._hwnd = None
        self._callback = None

    def attach(self, window):
        self._window = window
        # before_show is synchronous on the owning WinForms UI thread.
        window.events.before_show += self._prepare

    def _prepare(self):
        self._install(self._window.native.Handle.ToInt64())
        self._fit_initial_bounds()

    def _fit_initial_bounds(self):
        from System.Drawing import Point, Size
        from System.Windows.Forms import Screen

        form = self._window.native
        area = Screen.FromControl(form).WorkingArea
        scale = self._user.GetDpiForWindow(form.Handle.ToInt64()) / 96
        margin = round(16 * scale)
        width = min(form.Width, max(1, area.Width - 2 * margin))
        height = min(form.Height, max(1, area.Height - 2 * margin))
        form.MinimumSize = Size(min(round(1080 * scale), width), min(round(720 * scale), height))
        form.Size = Size(width, height)
        form.Location = Point(
            area.Left + (area.Width - width) // 2, area.Top + (area.Height - height) // 2
        )

    def _install(self, handle):
        self._user = ctypes.WinDLL("user32", use_last_error=True)
        self._common = ctypes.WinDLL("comctl32", use_last_error=True)
        result = ctypes.c_ssize_t
        self._proc_type = ctypes.WINFUNCTYPE(
            result,
            wintypes.HWND,
            wintypes.UINT,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
            ctypes.c_size_t,
            ctypes.c_size_t,
        )
        self._common.SetWindowSubclass.argtypes = [
            wintypes.HWND,
            self._proc_type,
            ctypes.c_size_t,
            ctypes.c_size_t,
        ]
        self._common.SetWindowSubclass.restype = wintypes.BOOL
        self._common.RemoveWindowSubclass.argtypes = [
            wintypes.HWND,
            self._proc_type,
            ctypes.c_size_t,
        ]
        self._common.DefSubclassProc.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        self._common.DefSubclassProc.restype = result
        self._user.IsZoomed.argtypes = [wintypes.HWND]
        self._user.IsZoomed.restype = wintypes.BOOL
        self._user.GetDpiForWindow.argtypes = [wintypes.HWND]
        self._user.GetDpiForWindow.restype = wintypes.UINT
        self._user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self._user.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]
        self._user.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        self._user.SendMessageW.restype = result
        self._user.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        self._callback = self._proc_type(self._message)
        if not self._common.SetWindowSubclass(handle, self._callback, 1, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        self._hwnd = handle
        self._user.SetWindowPos(
            handle, None, 0, 0, 0, 0, 0x0037
        )  # FRAMECHANGED, no move/resize/activate/z-order.

    def _message(self, hwnd, message, wparam, lparam, subclass_id, reference):
        if message == 0x0083:  # NCCALCSIZE: replace the OS caption with HTML.
            if self._user.IsZoomed(hwnd):
                # Windows maximizes a sizeable frame slightly beyond the work
                # area. Keep the HTML caption/buttons inside the visible area.
                rect = ctypes.cast(lparam, ctypes.POINTER(wintypes.RECT)).contents
                dpi = self._user.GetDpiForWindow(hwnd)
                x = self._user.GetSystemMetricsForDpi(32, dpi) + self._user.GetSystemMetricsForDpi(
                    92, dpi
                )
                y = self._user.GetSystemMetricsForDpi(33, dpi) + self._user.GetSystemMetricsForDpi(
                    92, dpi
                )
                rect.left += x
                rect.right -= x
                rect.top += y
                rect.bottom -= y
            return 0
        if message == 0x0084:  # NCHITTEST: retain all native resize edges/corners.
            if self._user.IsZoomed(hwnd):
                return 1
            rect = wintypes.RECT()
            self._user.GetWindowRect(hwnd, ctypes.byref(rect))
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            border = max(5, round(6 * self._user.GetDpiForWindow(hwnd) / 96))
            edge = ("n" if y < rect.top + border else "s" if y >= rect.bottom - border else "") + (
                "w" if x < rect.left + border else "e" if x >= rect.right - border else ""
            )
            return self.EDGES.get(edge, 1)
        if message == 0x0082:  # NCDESTROY: no callback into a destroyed window.
            self._common.RemoveWindowSubclass(hwnd, self._callback, 1)
            self._hwnd = None
        return self._common.DefSubclassProc(hwnd, message, wparam, lparam)

    def control(self, action):
        if action not in (
            "state",
            "minimize",
            "toggle_maximize",
            "close",
            "drag",
            *("resize_" + edge for edge in self.EDGES),
        ):
            raise ValueError("无效的窗口操作")
        if self._window is None or self._hwnd is None:
            raise ValueError("窗口尚未就绪")
        if action == "close":
            self._window.destroy()
        elif action == "minimize":
            self._window.minimize()
        elif action == "toggle_maximize":
            if self._user.IsZoomed(self._hwnd):
                self._window.restore()
            else:
                self._window.maximize()
        elif action == "drag" or action.startswith("resize_"):
            hit = 2 if action == "drag" else self.EDGES[action[7:]]
            # Dispatch native moving/sizing on its UI thread, preserving Windows
            # docking and drag-to-restore. Ignore mouse requests already released.
            from System import Action

            def move():
                if self._hwnd and self._user.GetAsyncKeyState(1) & 0x8000:
                    self._user.ReleaseCapture()
                    self._user.SendMessageW(self._hwnd, 0x00A1, hit, 0)

            self._window.native.Invoke(Action(move))
        return {"maximized": bool(self._hwnd and self._user.IsZoomed(self._hwnd))}
