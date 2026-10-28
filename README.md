# QQBot

QQBot 是一个运行在 Windows 上的个人 QQ 桌面助手。它通过独立运行的 [SnowLuma](https://github.com/SnowLuma/SnowLuma) 连接已登录的 QQ，使用你配置的模型处理消息，并在桌面界面中管理聊天、记忆和设置。

当前版本：**0.1.0**。

## 能做什么

- 设置模型 API、默认人设和每个账号的人设；按群聊或私聊范围控制自动回复。
- 查看聊天存档、处理记录和模型用量，管理成员记忆与本地表情库。
- 按需启用图片理解、图片发送和联网搜索；图片理解支持动图首帧。
- 在连接页面管理 SnowLuma 与 QQ 连接，查看运行状态、日志和本地存储占用。

当前版本面向 Windows 桌面版个人 QQ。扩展页面用于浏览信息，暂不支持直接安装原项目的扩展。

**音频和视频功能当前暂未加入。**如有需要，欢迎 Fork 本仓库，自行修改代码实现，也可以通过 Pull Request 提交改进。

## 使用前准备

- 64 位 Windows 10 或 Windows 11。
- 已安装并登录的 Windows 桌面版 QQ。QQ 版本和运行环境的兼容性请查看 [SnowLuma 文档](https://snowluma.github.io/)。
- 可用的模型 API 地址、模型名称和凭据。程序支持 Chat Completions、Responses 和 Anthropic 消息协议，具体能力取决于所选服务。
- 首次安装需要网络连接。联网搜索使用系统 Microsoft Edge，需另行启用。

## 安装

1. 下载或克隆本仓库，将文件放到一个固定目录。
2. 双击根目录的 `Install.bat`，等待安装完成。
3. 在项目根目录双击安装时生成的 `QQBot` 快捷方式启动。

安装脚本会在项目内准备 Python、Node.js 和前端依赖，下载 SnowLuma Windows x64 Lite 发行包，并在缺少 WebView2 时尝试安装微软运行时。已有完整的 SnowLuma 目录会保留；下载的 SnowLuma 压缩包会校验 SHA-256。网络无法访问发行页时可能需要检查网络后重试。

`QQBot.bat` 是带命令行窗口的启动入口，可用于查看启动错误。需要预览安装步骤时，可在项目目录运行 `Install.bat --dry-run`。

## 开始使用

1. 在“连接”页面启动 SnowLuma，连接并核验已登录的 QQ 账号。
2. 在“系统设置 → 模型 API”中填写模型服务信息并保存，按需测试连接。
3. 在“系统设置 → 默认人设”中查看或编辑默认角色卡。内置角色是“小鲸鱼”；它是角色设定，实际模型由你的 API 配置决定。
4. 在“机器人 → 机器人设置”中配置聊天范围和人设。可以点击“使用默认人设”填入默认值，继续修改后点击保存。
5. 确认聊天白名单和其他选项后，开启自动回复。图片、表情和联网能力需要在相应设置中启用。

默认人设用于新账号的初始设置，也可以手动填入已有账号；修改默认人设不会自动覆盖已保存的账号人设。

## 数据与网络

程序的设置、聊天存档、记忆、日志和服务凭据保存在本机的 `runtime/` 等运行数据目录，不属于仓库源码。模型处理会将相关聊天上下文发送给你配置的模型服务；启用联网或图片处理后，相关内容也可能发送给对应服务。分享日志或提交问题前，请检查并移除账号信息、聊天内容和密钥。

## 项目结构

| 路径 | 内容 |
| --- | --- |
| `src/QQ-agent/` | Python 机器人后端、存储和测试 |
| `src/DesktopShell/` | pywebview 桌面入口、React 前端和测试 |
| `src/SnowLuma/` | 安装时下载的独立 SnowLuma 运行时，不随源码仓库分发 |
| `Install.bat` | 项目依赖安装入口 |
| `tools/requirements.txt` | Python 依赖清单 |
| `tools/python/`、`tools/node/` | 安装后生成的项目专用运行时 |

## 开发检查

先运行安装脚本准备依赖。在项目根目录打开 PowerShell，运行后端测试：

```powershell
cd src\QQ-agent
..\..\tools\python\python.exe -m pytest -q
```

运行前端类型检查和测试：

```powershell
cd src\DesktopShell
..\..\tools\node\node.exe node_modules\typescript\bin\tsc -p frontend\tsconfig.json --noEmit
..\..\tools\node\node.exe --test frontend\tests\*.test.mjs
```

前端在应用启动时构建；修改源码后重新启动应用即可加载。

## 许可与来源

本项目以 [MIT License](LICENSE) 发布。机器人业务设计和部分实现参考或改写自 [QQ Agent](https://github.com/K0nd1us/QQ-agent)，原项目版权及许可声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。SnowLuma 和其他第三方组件适用各自的许可。

QQBot 是独立项目，与腾讯及 QQ 没有隶属关系。使用前请自行确认符合所用平台的相关条款。
