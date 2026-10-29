"""窗口外观偏好：无 HTTP origin 时仍可保存主题。"""

import json
import threading

from .paths import save_state


class Appearance:
    def __init__(self, root):
        self._file = root / "appearance.json"
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
