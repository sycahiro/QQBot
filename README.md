# QQBot

QQBot 是一个运行在 Windows 上的个人 QQ 桌面助手。它通过独立运行的 [SnowLuma](https://github.com/SnowLuma/SnowLuma) 引擎连接已登录的 QQ，把你配置的大模型变成一个"住在这台电脑里"的聊天伙伴：自动读消息、按人设回复、管理记忆和表情，全部数据保存在本机。

当前版本：**1.0.0**。

## 功能一览

- **自动回复**：按群聊 / 私聊范围控制回复；处理中收到的新消息会自动攒成一批一起处理，不刷屏也不漏消息。
- **人设系统**：全局默认人设 + 每个账号独立人设；支持设置管理员 QQ（不受会话名单限制）。
- **QQ 自带表情**：收录 QQNT 官方系统表情对照表，按名字发送（如 `[表情:呲牙]`），支持单条纯表情的大表情效果；表外名字会被安全丢弃。
- **聊天存档与记录**：完整消息存档、每轮模型处理记录（调用了什么工具、参数和结果）、模型用量统计。
- **记忆系统**：按成员保存长期记忆，回复时自动带上下文。
- **本地表情库**：收藏图片到表情库，之后可以自主发送。
- **图片理解（可选）**：识图模型看图，支持动图首帧；看图是例外不是默认，未被点名时默认按文字回复。
- **发图（可选）**：发送 HTTPS 图片直链，先预览确认再发送。
- **联网搜索（可选）**：通过 Bing 官方 RSS 通道搜索公开网页并读取正文核实，无需搜索 API 密钥、不依赖浏览器；自动把口语问题提炼成关键词查询，搜索失败或结果无关时如实说明。
- **其他**：拍一拍互动、撤回自己刚发出的错误消息、合并转发展开。

当前版本面向 Windows 桌面版个人 QQ。本项目的功能设计参考了 K0nd1us/QQ-agent（下称"上游"）：上游项目已于 2026 年 10 月下旬停止服务——作者删除了其 GitHub 仓库（<https://github.com/K0nd1us/QQ-agent> 现已 404，作者账号下的公开仓库已全部清空，最后可查的公开活跃记录为 2026 年 10 月 19 日），随上游一同提供的插件市场页面 <https://www.kondius.cn/qq-agent/plugin-market/> 也已无法访问（2026 年 10 月 30 日验证返回 503）。由于插件市场已随上游一起停止服务，本版本移除了插件市场浏览功能："扩展"页面仅作占位展示，目前没有可安装的扩展。

**音频和视频功能当前暂未加入**。如有需要，欢迎 Fork 本仓库自行修改实现，也欢迎通过 Pull Request 提交改进。

## 整体架构

应用由三部分组成，各自独立、通过明确的接口衔接：

```text
QQBot/
├─ DesktopShell   桌面壳（pywebview + React）：连接、系统设置、机器人、聊天存档、
│  │              本地表情库等全部图形界面；前端在启动时内存构建后注入 WebView2，
│  │              不产生构建产物
│  ▼
├─ QQBot 后端     业务核心（Python 包）：人设、记忆、工具调度、存储与用量统计
│  │              ├─ 调用你配置的模型 API（Chat Completions / Responses / Anthropic 三种协议）
│  │              └─ 通过 OneBot 11 接口与 SnowLuma 通信
│  ▼
└─ SnowLuma 引擎  独立 Node 运行时（手动安装）：负责 QQNT 协议连接与收发消息
   ▼
  QQ（已登录的 Windows 桌面版客户端）
```

一条消息的完整旅程：SnowLuma 收到 QQ 消息 → 后端按会话把连发消息攒成一批 → 组装上下文（人设、该成员的长期记忆、最近聊天记录、当前可用的工具）→ 交给模型 → 执行模型决定调用的工具（搜索、发图、看图、存表情等）→ 把回复发回 QQ，同时把这一轮的完整过程（消息、工具调用、参数与结果）写入存档。

## 环境要求

- 64 位 Windows 10 或 Windows 11。
- 已安装并登录的 Windows 桌面版 QQ。QQ 版本与运行环境的兼容性请查看 [SnowLuma 文档](https://snowluma.github.io/)。
- 一个可用的模型 API（地址、模型名称和密钥）。程序支持 Chat Completions、Responses 和 Anthropic 消息协议，具体能力取决于所选服务。
- 安装过程需要网络；联网搜索直接请求 Bing 的 RSS 订阅接口（纯 HTTP），不需要浏览器，也不需要搜索服务的 API 密钥。

## 安装教程

> 全程只需要做一次。项目请放在一个**固定的目录**（建议纯英文路径），运行后不要再移动。

### 第 1 步：获取本项目

```bat
git clone https://github.com/sycahiro/QQBot.git
cd QQBot
```

或者直接在 GitHub 页面下载 ZIP 解压，效果一样。

### 第 2 步：手动安装 SnowLuma 引擎（重要，必做）

SnowLuma 是连接 QQ 的独立引擎。由于许可与分发限制，**它不随本仓库分发，安装脚本也不会替你下载**，需要手动安装：

1. 打开发行页：<https://github.com/SnowLuma/SnowLuma/releases>
2. 在最新发行版的 Assets 里下载 Windows 轻量包，文件名形如：
   **`SnowLuma-vX.X.X-win-x64-lite.zip`**（认准 `win-x64-lite`；本项目已验证 v2.2.1 可用）
3. 解压压缩包，把里面的**全部内容**放进项目目录的 `src\SnowLuma\` 文件夹。

   放好后的结构应该长这样（`index.mjs` 直接在 `SnowLuma` 目录下，**不要多套一层文件夹**）：

   ```text
   QQBot\
   └─ src\
      └─ SnowLuma\
         ├─ index.mjs
         ├─ package.json
         ├─ native\
         └─ …
   ```

4. 如果位置没放对，`Install.bat` 会在一开始就报错并给出同样的提示，按提示放好再重跑即可。

### 第 3 步：运行安装脚本

双击项目根目录的 **`Install.bat`**，等待完成。脚本会自动：

- 下载便携版 CPython 3.14+ 和 Node.js 24 到 `tools\python\`、`tools\node\`（项目专用，不污染系统）；
- 安装 Python 依赖和前端依赖；
- 缺少 WebView2 运行时时安装微软官方运行时；
- 创建启动快捷方式 `QQBot.lnk`。

想先预览每一步会做什么，可以运行 `Install.bat --dry-run`，它不修改任何文件。网络不好导致某一步失败时，修好网络重新运行即可——已完成的步骤会自动跳过。

### 第 4 步：启动

- 双击项目根目录的 **QQBot** 快捷方式启动（无控制台窗口）。
- 排查启动问题时用 **`QQBot.bat`**，它带命令行窗口，能看到启动错误。

## 开始使用

1. **连接 QQ**：进入"连接"页面，启动 SnowLuma，连接并核验已登录的 QQ 账号。
2. **配置模型**：在"系统设置 → 模型 API"里填写 API 地址、模型名称和密钥并保存，可点击测试连接验证。
3. **编辑人设**：在"系统设置 → 默认人设"查看或编辑默认角色卡（内置角色是"小鲸鱼"；它是角色设定，实际模型由你的 API 配置决定）。
4. **配置机器人**：在"机器人 → 机器人设置"里点击"使用默认人设"填入默认值、按需修改后保存，并配置聊天范围（私聊开关、群白名单）与触发方式。
5. **开启自动回复**：确认白名单后打开开关。图片理解、发图、联网搜索等能力需要在相应设置里分别启用。

默认人设用于新账号的初始设置，也可以手动填入已有账号；修改默认人设不会自动覆盖已保存的账号人设。

## 功能细节

### 联网搜索

在"系统设置 → 网络"里开启。搜索通道只有一条：Bing 官方 RSS 订阅接口（`format=rss`，纯 HTTP 请求，无浏览器、无搜索 API 密钥），返回多少条结果就处理多少条。

模型在搜索前会把口语问题提炼成关键词查询：只放 2~5 个关键词、最独特的词放最前、去掉"明天/所以"这类口语虚词和相对时间词——搜索引擎听不懂"明天"是哪天，这类高频词还会劫持整个查询。查对阵、赛程这类问题用"A vs B 时间"的组合。这些规则全部来自对本通道的实测：整句或过长的查询在中文场景下容易被搜索引擎放弃匹配，坍缩成只认其中某个常用词，返回完全无关的结果。

搜索摘要只当线索：同一天多场比赛、时间数字这类细节可能在摘要里被张冠李戴，所以关键细节会再用 `web_fetch` 读取网页正文核实。个别站点有反爬（如百度百科）或没有可读正文时会如实报错并换其他来源，绝不编造；一次搜索没命中就换更短的关键词重搜。如果最终没有可靠结果，机器人会直接说明没搜到，而不是给出看似合理的猜测。

### 模型接入

模型 API 支持 Chat Completions、Responses 和 Anthropic 消息三种协议，填入地址、模型名称和密钥即可，换服务或中转站不需要改代码。每一轮对话调用的模型、消耗的 token 和耗时都会记入用量统计；聊天存档里也会完整保留每轮的工具调用过程，方便回溯机器人的每一步行为。

## SnowLuma 控制台密码

SnowLuma WebUI 的登录密码由本项目首次启动时自动生成，**保存在本机明文文件里，随时可以查看**：

| 文件 | 内容 |
| --- | --- |
| `runtime/secrets/snowluma-service.json` | 首次启动自动生成的初始密码（`password` 字段）。只要没在 WebUI 里改过密码，它就一直有效 |
| `runtime/secrets/webui-password.json` | 在应用设置里手动保存的"密码备忘"（改过密码后自己存一份的备忘） |

- 密码首次生成后固定，重启 SnowLuma 也沿用同一个。
- 如果改过密码又忘了：关闭应用，删除 `data/services/snowluma/config/webui.json`（只删这一个文件），重新启动后会用初始密码重新初始化，再去 `runtime/secrets/snowluma-service.json` 找回它。

## 更新与卸载

- **更新**：在项目目录执行 `git pull`，然后重跑一次 `Install.bat`——已完成的步骤会自动跳过，只补装新增或缺失的依赖。运行数据都在 `runtime/`、`data/` 里，更新不会动它们。
- **卸载**：项目目录就是全部——便携运行时、依赖、数据都在里面，删除整个目录即可干净移除，不写注册表、不装全局依赖。

## 数据与安全

- 设置、聊天存档、记忆、日志和服务凭据都保存在本机 `runtime/` 等运行数据目录，不属于仓库源码。
- 模型处理会把相关聊天上下文发送给你配置的模型服务；启用联网或图片理解后，相关内容也会发送给对应服务。
- 分享日志或提交 Issue 前，请检查并移除账号信息、聊天内容和 API 密钥。

## 项目结构

| 路径 | 内容 |
| --- | --- |
| `src/QQBot/` | Python 机器人后端包（业务、QQ 连接、模型调度、存储） |
| `src/DesktopShell/` | pywebview 桌面入口、React 前端和测试 |
| `src/SnowLuma/` | **手动安装**的独立 SnowLuma 运行时（见安装教程第 2 步），不入库 |
| `tests/` | 后端 pytest 测试，与源码分离 |
| `Install.bat` | 项目依赖安装入口 |
| `QQBot.bat` | 带控制台的启动入口 |
| `tools/requirements.txt` | Python 依赖清单 |
| `tools/python/`、`tools/node/` | 安装后生成的项目专用运行时，不入库 |
| `runtime/`、`data/` | 运行数据，不入库 |

## 运行数据目录

应用运行后的数据全部落在本机，布局如下：

```
runtime/                            本应用的运行数据
├── logs/app/<启动会话>/             每次启动一个目录（desktop/frontend/launcher.log），
│                                   自动只保留最近 10 个会话
├── webview/                        WebView2 浏览器缓存，可随时整个删除，下次启动重建
├── accounts/<QQ号>/                机器人业务数据（agent.sqlite3：人设/会话/记忆/贴纸）
├── settings/                       用户设置（global.json 模型与联网、appearance.json 主题、
│                                   preferences.json 托盘行为、storage.json 存储策略）
├── state/                          程序状态（account.json 当前账号、app.json 运行状态、
│                                   taskbar-shortcut.json 任务栏身份标记）
└── secrets/                        凭据（见「SnowLuma 控制台密码」）

data/services/snowluma/             SnowLuma 引擎的家目录（引擎自己的布局）
├── config/                         引擎配置（onebot.json 由应用首次初始化，其余由引擎 WebUI 写）
├── data/<QQ号>/                    引擎的消息/回应数据库
└── logs/                           引擎日志（按天分文件，引擎自带轮转与总量清理）
```

## 开发检查

先运行安装脚本准备依赖。在项目根目录打开 PowerShell，运行后端测试：

```powershell
tools\python\python.exe -m pytest -q tests
```

运行前端类型检查和测试：

```powershell
cd src\DesktopShell
..\..\tools\node\node.exe node_modules\typescript\bin\tsc -p frontend\tsconfig.json --noEmit
..\..\tools\node\node.exe --test frontend\tests\*.test.mjs
```

前端在应用启动时构建；修改源码后重新启动应用即可加载。

## 许可与第三方声明

本项目以 [MIT License](LICENSE) 发布；仓库内的第三方声明不改变各第三方组件各自的许可。

### 参考的第三方项目

#### QQ-agent

[K0nd1us/QQ-agent](https://github.com/K0nd1us/QQ-agent)：本项目在功能设计上参考过其源码与产品形态（人设、记忆、表情库、存档、插件市场等功能的思路），代码全部为本项目以不同语言（Python / React）重新实现，未使用、未复制、未翻译其任何代码或文本。该上游项目已于 2026 年 10 月下旬停止服务：作者删除了其 GitHub 仓库（链接现已 404），随上游一同提供的插件市场页面也已无法访问；上列地址仅作来源标注。

#### qq-bridge（内置人设卡的来源）

[Derpyu520/qq-bridge](https://github.com/Derpyu520/qq-bridge)：QQ 消息接入 DSH agent 的桥接项目。本项目内置的默认人设（"小鲸鱼"角色卡）改编自该仓库的 `roles/小鲸鱼.md`，并已适配本项目的工具架构。该角色卡按 MIT License 授权，原版权及许可声明如下：

```text
MIT License

Copyright (c) 2026 Derpyu520 and qq-bridge / QSH contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

#### AstrBot

[AstrBotDevs/AstrBot](https://github.com/AstrBotDevs/AstrBot)：多平台 LLM 聊天机器人框架。本项目仅出于学习研究目的阅读过其公开源码与文档，重点研究了其中 QQ 官方机器人（QQ 开放平台）与微信官方机器人相关适配器的实现，一度考虑将其引入，但最终没有把这两部分（或其任何其他部分）加入本项目。因此：**未使用其中任何组件，未复制、未引用、未派生其任何代码**，两者在代码层面没有任何关联，本仓库不构成其衍生作品。AstrBot 使用 GNU Affero General Public License v3.0（AGPL-3.0）许可，本仓库不受其约束。

### SnowLuma

[SnowLuma](https://github.com/SnowLuma/SnowLuma) 是独立的第三方运行时，**不包含在本仓库中，安装脚本也不会替你下载**：需要按上方"安装教程"手动从官方发行页获取其 Windows 发行包并放入 `src/SnowLuma/`。其源代码、二进制与原生组件适用 SnowLuma 自己的许可、最终用户许可协议和隐私说明，并非由本项目的 MIT License 授权。具体条款以下载的发行包和官方项目为准。

### 其他组件

Python、Node.js、pywebview、React 和其他依赖均按各自的许可使用，安装后的依赖包中包含相应许可或版权文件。应用的"系统设置 → 关于"页面可查看本机已安装组件的版本和许可元数据；该列表不是完整的第三方版权与许可文本汇总。Microsoft Edge WebView2 运行时和 QQ 适用各自的服务及许可条款。

QQBot 是独立项目，与腾讯及 QQ 没有隶属关系。使用前请自行确认符合所用平台的相关条款。
