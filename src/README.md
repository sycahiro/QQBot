# 源码目录

- `QQBot/`：Python 后端包（机器人业务、QQ 连接、模型调度、存储）。
- `DesktopShell/`：pywebview 桌面入口和 React 前端。
- `SnowLuma/`：安装时下载的第三方运行时，不包含在本仓库中。

后端测试在仓库根目录的 `tests/`，与源码分离；桌面入口将 `src/` 加入 Python 路径后导入 `QQBot` 包。后端通过独立的 SnowLuma 进程与本机 QQ 通信；业务数据和服务数据分别保存在仓库根目录的 `runtime/` 与 `data/`。

安装、运行与测试方法见[项目首页](../README.md)。
