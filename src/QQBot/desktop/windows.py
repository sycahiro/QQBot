"""Windows 专用的单实例互斥量、自有子进程作业对象与任务栏应用身份。"""

import ctypes
import hashlib
import json
import logging
import os
import sys
import uuid
from ctypes import byref, wintypes
from pathlib import Path

logger = logging.getLogger(__name__)

_CLSID_SHELL_LINK = "00021401-0000-0000-C000-000000000046"
_IID_SHELL_LINK = "000214F9-0000-0000-C000-000000000046"
_IID_PERSIST_FILE = "0000010B-0000-0000-C000-000000000046"
_IID_PROPERTY_STORE = "886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"
_APPUSERMODEL_FMTID = "9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"
_VT_LPWSTR = 31


def set_application_identity():
    """让任务栏将 QQBot 识别为独立应用，不再归到 Python 图标下。"""
    api = ctypes.WinDLL("shell32", use_last_error=True)
    api.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
    api.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
    result = api.SetCurrentProcessExplicitAppUserModelID("QQBot.Desktop")
    if result < 0:
        raise OSError(result, "无法设置 QQBot 窗口标识")


def _method(instance, index, *argtypes):
    """按 vtable 序号取 COM 方法；COM 均为 stdcall。"""
    vtable = ctypes.cast(instance, ctypes.POINTER(ctypes.c_void_p))[0]
    address = ctypes.cast(vtable, ctypes.POINTER(ctypes.c_void_p))[index]
    return ctypes.WINFUNCTYPE(wintypes.HRESULT, ctypes.c_void_p, *argtypes)(address)


def ensure_shortcut(paths, programs=None):
    """在开始菜单注册带应用标识（AUMID）的 QQBot.lnk。

    进程级 AUMID 只负责分组；任务栏右键菜单里的名称与图标必须来自
    一个注册了同名 AUMID 的快捷方式，否则回退成 python.exe 的
    "Python" 与 Python 图标。快捷方式缺省或指向变更时重建。
    """
    if sys.platform != "win32":
        return None
    if programs is None:
        base = os.environ.get("APPDATA")
        if not base:
            return None
        programs = Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    link = Path(programs) / "QQBot.lnk"
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    target = pythonw if pythonw.is_file() else Path(sys.executable)
    wanted = {
        "target": str(target),
        "args": f'-B "{paths.entry}"',
        "icon": str(paths.icon),
        "aumid": "QQBot.Desktop",
    }
    marker = paths.runtime / "state" / "taskbar-shortcut.json"
    try:
        if link.is_file() and json.loads(marker.read_text(encoding="utf-8")) == wanted:
            return link
    except (OSError, ValueError):
        pass
    try:
        _write_shortcut(link, wanted)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(wanted), encoding="utf-8")
    except OSError as error:
        logger.warning("注册任务栏身份快捷方式失败：%s", error)
        return None
    return link


def _write_shortcut(link, wanted):
    def iid(text):
        return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)

    class PropertyKey(ctypes.Structure):
        _fields_ = [("fmtid", ctypes.c_ubyte * 16), ("pid", wintypes.DWORD)]

    class PropVariant(ctypes.Structure):
        _fields_ = [
            ("vt", ctypes.c_ushort),
            ("reserved1", ctypes.c_ushort),
            ("reserved2", ctypes.c_ushort),
            ("reserved3", ctypes.c_ushort),
            ("pointer", ctypes.c_void_p),
            ("padding", ctypes.c_uint64),
        ]

    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = wintypes.HRESULT
    ole32.CoCreateInstance.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = wintypes.HRESULT

    # S_OK/S_FALSE 表示本线程已可用；RPC_E_CHANGED_MODE 说明已是 MTA，直接沿用。
    changed = ole32.CoInitializeEx(None, 2) == -2147417850  # RPC_E_CHANGED_MODE
    shell_link = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(
        byref(iid(_CLSID_SHELL_LINK)),
        None,
        1,  # CLSCTX_INPROC_SERVER
        byref(iid(_IID_SHELL_LINK)),
        byref(shell_link),
    )
    if hr != 0 or not shell_link:
        raise OSError(hr, "无法创建 IShellLink")
    try:
        set_description = _method(shell_link, 7, wintypes.LPCWSTR)
        set_working_dir = _method(shell_link, 9, wintypes.LPCWSTR)
        set_arguments = _method(shell_link, 11, wintypes.LPCWSTR)
        set_icon_location = _method(shell_link, 17, wintypes.LPCWSTR, ctypes.c_int)
        set_path = _method(shell_link, 20, wintypes.LPCWSTR)
        for call, arguments in (
            (set_path, (wanted["target"],)),
            (set_arguments, (wanted["args"],)),
            (set_icon_location, (wanted["icon"], 0)),
            (set_description, ("QQBot 桌面端",)),
            (set_working_dir, (str(Path(wanted["target"]).parent),)),
        ):
            if call(shell_link, *arguments) != 0:
                raise OSError("IShellLink 属性写入失败")

        # 属性必须先 Commit 再 Save：Save 时才会把属性序列化进 .lnk 文件。
        store = ctypes.c_void_p()
        query_interface = _method(shell_link, 0, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
        if (
            query_interface(shell_link, byref(iid(_IID_PROPERTY_STORE)), byref(store)) != 0
            or not store
        ):
            raise OSError("无法获取 IPropertyStore")
        try:
            key = PropertyKey(iid(_APPUSERMODEL_FMTID), 5)  # PKEY_AppUserModel_ID
            value = PropVariant(vt=_VT_LPWSTR)
            # 缓冲区必须活到 SetValue 之后：c_wchar_p 临时对象会在语句结束被回收。
            text = ctypes.create_unicode_buffer(wanted["aumid"])
            value.pointer = ctypes.cast(text, ctypes.c_void_p).value
            set_value = _method(store, 6, ctypes.c_void_p, ctypes.c_void_p)
            commit = _method(store, 7)
            if set_value(store, byref(key), byref(value)) != 0 or commit(store) != 0:
                raise OSError("应用标识属性写入失败")
        finally:
            _method(store, 2)(store)

        persist = ctypes.c_void_p()
        if (
            query_interface(shell_link, byref(iid(_IID_PERSIST_FILE)), byref(persist)) != 0
            or not persist
        ):
            raise OSError("无法获取 IPersistFile")
        try:
            save = _method(persist, 6, wintypes.LPCWSTR, wintypes.BOOL)
            if save(persist, str(link), True) != 0:
                raise OSError("快捷方式保存失败")
        finally:
            _method(persist, 2)(persist)
    finally:
        _method(shell_link, 2)(shell_link)
    if not changed:
        ole32.CoUninitialize()


def kernel():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    return api


class SingleInstance:
    def __init__(self, root: Path, runtime: Path):
        self.api = kernel()
        self.api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateMutexW.restype = wintypes.HANDLE
        key = hashlib.sha256(
            (
                os.path.normcase(str(root.resolve()))
                + "|"
                + os.path.normcase(str(runtime.resolve()))
            ).encode()
        ).hexdigest()[:24]
        ctypes.set_last_error(0)
        self.handle = self.api.CreateMutexW(None, False, "Local\\QQBotDesktop-" + key)
        error = ctypes.get_last_error()
        if not self.handle:
            raise ctypes.WinError(error)
        self.primary = error != 183  # ERROR_ALREADY_EXISTS
        self.runtime = runtime

    def request_focus(self):
        save = self.runtime / ("focus-" + uuid.uuid4().hex + ".tmp")
        self.runtime.mkdir(parents=True, exist_ok=True)
        try:
            save.write_text("focus", encoding="utf-8")
            os.replace(save, self.runtime / "focus.request")
        finally:
            save.unlink(missing_ok=True)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class OwnedProcessJob:
    """Python 异常退出时，由 Windows 清理本应用启动的 Node 及其子进程。"""

    def __init__(self):
        api = self.api = kernel()

        class Basic(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_longlong),
                ("job_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD),
                ("minimum", ctypes.c_size_t),
                ("maximum", ctypes.c_size_t),
                ("active", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class Counters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong)
                for name in [
                    "read_ops",
                    "write_ops",
                    "other_ops",
                    "read_bytes",
                    "write_bytes",
                    "other_bytes",
                ]
            ]

        class Limits(ctypes.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", Counters),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        api.CreateJobObjectW.restype = wintypes.HANDLE
        api.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        api.SetInformationJobObject.restype = wintypes.BOOL
        api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        api.AssignProcessToJobObject.restype = wintypes.BOOL
        self.handle = api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Limits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)

    def assign(self, process):
        # Popen 持有刚创建进程的精确句柄，避免依赖可能被复用的 PID。
        if not self.api.AssignProcessToJobObject(
            self.handle, wintypes.HANDLE(int(process._handle))
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None
