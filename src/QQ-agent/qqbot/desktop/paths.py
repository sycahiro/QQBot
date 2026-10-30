import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# 启动会话日志目录名：日期_时间-PID。
SESSION_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}")
# 启动会话日志保留数量；更早的会话目录在启动时清理。
LOG_SESSIONS_KEPT = 10


def prune_logs(runtime: Path, keep: int = LOG_SESSIONS_KEPT):
    """启动会话日志只保留最近 keep 个。"""
    base = runtime / "logs" / "app"
    if not base.is_dir():
        return
    sessions = [
        entry for entry in base.iterdir() if entry.is_dir() and SESSION_DIR.match(entry.name)
    ]
    sessions.sort(key=lambda entry: entry.name)
    for stale in sessions[:-keep] if len(sessions) > keep else ():
        shutil.rmtree(stale, ignore_errors=True)


@dataclass(frozen=True)
class DesktopPaths:
    root: Path
    runtime: Path
    log_session: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d_%H-%M-%S.%f") + f"-{os.getpid()}"
    )

    @property
    def logs(self):
        return self.runtime / "logs" / "app" / self.log_session

    @property
    def webview(self):
        """WebView2 用户数据目录（浏览器缓存，可随时删，删除仅丢失本地 UI 状态）。"""
        return self.runtime / "webview"

    @property
    def snowluma_home(self):
        """SnowLuma 独立服务的家目录（cwd / config / data 都在它下面）。"""
        return self.root / "data" / "services" / "snowluma"

    @property
    def snowluma_data(self):
        """引擎按 cwd/data/<QQ号> 的约定落库；统计与清理必须锚定同一根。"""
        return self.snowluma_home / "data"

    @property
    def snowluma_onebot_config(self):
        """OneBot 受控配置（含状态命令等引擎行为设置）。"""
        return self.snowluma_home / "config" / "onebot.json"

    @classmethod
    def discover(cls, runtime: str | None = None):
        root = Path(__file__).resolve().parents[4]
        return cls(root, Path(runtime).resolve() if runtime else root / "runtime")

    @property
    def entry(self):
        """桌面壳入口脚本（QQBot.bat 与开机自启共用）。"""
        return self.root / "src" / "DesktopShell" / "start.py"

    @property
    def node(self):
        return self.root / "tools" / "node" / "node.exe"

    @property
    def snowluma_entry(self):
        return self.root / "src" / "SnowLuma" / "index.mjs"

    @property
    def frontend(self):
        return self.root / "src" / "DesktopShell" / "frontend"

    @property
    def icon(self):
        return self.frontend / "public" / "qqbot.ico"

    @property
    def version(self):
        return json.loads((self.root / "src" / "DesktopShell" / "package.json").read_text(encoding="utf-8"))[
            "version"
        ]


def save_state(file: Path, value: dict):
    """同目录原子替换，避免重复启动时读到半条状态。"""
    file.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=file.name + "-", dir=file.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, file)
    finally:
        Path(temporary).unlink(missing_ok=True)
