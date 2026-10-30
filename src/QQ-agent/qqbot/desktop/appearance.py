"""窗口外观偏好：无 HTTP origin 时仍可保存主题。"""

import json
import threading
from pathlib import Path

from .paths import adopt, save_state


def appearance_file(runtime):
    """主题偏好文件的位置；老安装的 runtime/appearance.json 自动搬入 settings/。"""
    return adopt(Path(runtime) / "settings" / "appearance.json", Path(runtime) / "appearance.json")


class Appearance:
    def __init__(self, file):
        """file 为偏好文件完整路径（用 appearance_file(runtime) 构造）。"""
        self._file = file
        self._lock = threading.Lock()

    def read(self):
        with self._lock:
            try:
                value = json.loads(self._file.read_text(encoding="utf-8")).get("theme")
            except (OSError, ValueError, AttributeError):
                return "system"
            return value if value in ("light", "dark", "system") else "system"

    def save(self, theme):
        if not isinstance(theme, str) or theme not in ("light", "dark", "system"):
            raise ValueError("无效的主题")
        with self._lock:
            save_state(self._file, {"theme": theme})
        return theme
