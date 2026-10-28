import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class DesktopPaths:
    root: Path
    runtime: Path
    log_session: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d_%H-%M-%S.%f") + f"-{os.getpid()}"
    )

    @property
    def logs(self):
        return self.runtime / "logs" / self.log_session

    @property
    def snowluma_home(self):
        """SnowLuma 独立服务的家目录（cwd / config / data 都在它下面）。"""
        return self.root / "data" / "services" / "snowluma"

    @property
    def snowluma_data(self):
        return self.snowluma_home / "default" / "data"

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
