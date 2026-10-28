# QQBot

**Windows 上的个人 QQ AI 助手** · 当前版本 **0.1.0**

QQBot 是一个本地桌面工作台：通过独立的 [SnowLuma](https://github.com/SnowLuma/SnowLuma) 运行时连接电脑上已登录的个人 QQ，并使用你配置的模型处理消息。桌面界面由 React、pywebview 和 WebView2 构成。

## 功能

- 为个人 QQ 配置自动回复、人设、聊天范围和模型方案。
- 查看聊天存档、模型会话及用量，管理记忆和表情库。
- 按需开启图片理解和联网搜索；动图仅读取首帧。
- 查看连接状态、运行日志和本地存储占用，使用调试工具排查问题。

当前版本连接个人 QQ；不提供 QQ 开放平台官方机器人或微信渠道。扩展市场用于浏览信息，暂不支持直接安装原项目的扩展。

## 系统要求

- 64 位 Windows 10 或 11。
- 已安装并登录的 Windows 桌面版 QQ；QQ 与 SnowLuma 的版本兼容性以 [SnowLuma 官方说明](https://snowluma.github.io/)为准。
- 联网搜索需要系统安装 Microsoft Edge；模型调用需要自行准备兼容的 API 服务及凭据。
- 首次安装需要联网。安装脚本准备项目专用的 Python、Node.js、前端依赖、SnowLuma；缺少 WebView2 时会尝试安装微软官方运行时。

## 安装与启动

1. 克隆或下载本仓库，解压到固定目录。
2. 双击项目根目录的 `Install.bat`，等待依赖安装完成。也可以在 PowerShell 中运行：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
   ```

3. 双击根目录生成的 `QQBot` 快捷方式启动。`QQBot.bat` 是带命令行日志的诊断入口。
4. 在“连接”页启动 SnowLuma 并选择本机已登录的 QQ，在“系统设置”里配置模型，再按需开启自动回复。

安装脚本从 SnowLuma 官方发行页下载 Windows x64 Lite 包并验证摘要；已有 `src/SnowLuma/` 目录会保留，不会自动覆盖。GitHub 发行信息暂时不可用时，脚本会提示并使用内置的已验证版本。SnowLuma 是独立第三方运行时，其发行包不包含在本仓库内。

## 数据与隐私

应用设置、聊天存档、日志及服务凭据保存在本机 `runtime/` 和 `data/`；这两个目录默认不会提交到 Git。模型调用和联网搜索会将相关请求发送给你配置的模型服务或搜索服务。分享日志或提交问题前，请自行移除账号信息、聊天内容、密钥和其他敏感数据。

## 开发与测试

| 路径 | 说明 |
| --- | --- |
| `src/QQ-agent/` | Python 后端、存储与测试 |
| `src/DesktopShell/` | 桌面入口和 React 前端 |
| `setup.ps1` / `Install.bat` | 根目录一键安装入口 |
| `tools/setup.ps1` | 便携 Python、Node.js 和 Python 依赖安装 |
| `tools/python/requirements.txt` | Python 依赖清单 |

在仓库根目录运行后端测试：

```powershell
cd src\QQ-agent
..\..\tools\python\python.exe -m pytest -q
```

前端检查：

```powershell
cd src\DesktopShell
..\..\tools\node\node.exe node_modules\typescript\bin\tsc -p frontend\tsconfig.json --noEmit
..\..\tools\node\node.exe --test frontend\tests\*.test.mjs
```

## 许可与致谢

本项目以 [MIT License](LICENSE) 发布。项目参考了 [QQ Agent](https://github.com/K0nd1us/QQ-agent) 和 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 等项目；第三方版权、许可及来源说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。SnowLuma 和其他第三方组件适用各自的许可，项目自身的 MIT 许可不改变这些条款。

QQBot 是独立项目，与腾讯及 QQ 没有隶属关系。使用前请自行确认符合所用平台的相关条款。
