"""任务栏应用身份（AUMID 快捷方式注册）的回归测试。"""

import json
import sys
from types import SimpleNamespace

import pytest

from qqbot.desktop.windows import ensure_shortcut

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="任务栏身份仅在 Windows 上注册"
)


@pytest.fixture
def paths(tmp_path):
    icon = tmp_path / "assets" / "qqbot.ico"
    icon.parent.mkdir()
    icon.write_bytes(b"\x00\x00\x01\x00")  # 仅占位；SetIconLocation 不校验文件存在
    runtime = tmp_path / "runtime"
    return SimpleNamespace(
        entry=tmp_path / "src" / "DesktopShell" / "start.py",
        icon=icon,
        runtime=runtime,
    )


def test_shortcut_registers_with_aumid_and_is_idempotent(paths, tmp_path):
    programs = tmp_path / "programs"
    programs.mkdir()

    link = ensure_shortcut(paths, programs=programs)
    assert link is not None and link.is_file()
    marker = json.loads((paths.runtime / "taskbar-shortcut.json").read_text(encoding="utf-8"))
    assert marker["aumid"] == "QQBot.Desktop"
    assert marker["target"].endswith("pythonw.exe") or marker["target"].endswith("python.exe")
    assert '-B "' in marker["args"]

    # 已注册且配置未变时不得重复写入（避免每次启动都动开始菜单）。
    before = link.stat().st_mtime_ns
    assert ensure_shortcut(paths, programs=programs) == link
    assert link.stat().st_mtime_ns == before


def test_shortcut_rebuilds_when_entry_changes(paths, tmp_path):
    programs = tmp_path / "programs"
    programs.mkdir()
    ensure_shortcut(paths, programs=programs)

    paths.entry = tmp_path / "moved" / "start.py"
    assert ensure_shortcut(paths, programs=programs) is not None
    marker = json.loads((paths.runtime / "taskbar-shortcut.json").read_text(encoding="utf-8"))
    assert str(paths.entry) in marker["args"]
