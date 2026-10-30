# 桌面窗口

桌面入口使用项目自带 Python 和 pywebview 创建 Windows 窗口。正常启动可使用安装脚本生成的根目录 `QQBot` 快捷方式；`QQBot.bat` 保留前台日志，便于诊断。

- `paths.py`：项目、运行时和日志路径。
- `windows.py`、`resident.py`：单实例、任务栏身份、托盘和启动选项。
- `frontend.py`：调用 Node 将前端构建成内存页面。
- `bridge.py`：限定界面可调用的业务接口。
- `storage.py`、`diagnostics.py`、`resources.py`：存储管理、日志和资源统计。
- `dependencies.py`：关于页的本地组件清单。

窗口与前端不依赖常驻网页服务。账号数据、全局设置和日志保存在 `runtime/`；SnowLuma 服务数据保存在 `data/`。QQ 连接需要用户显式操作。
