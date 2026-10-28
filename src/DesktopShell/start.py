"""专用 Conda 环境的源码入口；不激活或修改 base。"""

import os
import sys
from pathlib import Path

_dll_directories = []
if sys.platform == "win32":
    library_bin = Path(sys.prefix) / "Library" / "bin"
    if library_bin.is_dir():
        _dll_directories.append(os.add_dll_directory(str(library_bin)))
        os.environ["PATH"] = str(library_bin) + os.pathsep + os.environ.get("PATH", "")

# Native libraries must be discoverable before importing application modules.
# 壳模块只持有入口与前端；py 后端包（qqbot）在 QQ-agent 模块里。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "QQ-agent"))

from qqbot.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
