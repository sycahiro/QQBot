# 第三方项目与许可声明

本项目由多个独立组件构成。仓库自身的 [MIT License](LICENSE) 不改变第三方组件各自的许可。

## 参考的第三方项目

### QQ-agent（上游项目）

本项目的机器人业务设计和部分实现参考或改写自 [K0nd1us/QQ-agent](https://github.com/K0nd1us/QQ-agent)。该上游项目已于 2026 年 10 月下旬停止服务：作者删除了其 GitHub 仓库（链接现已 404），随上游一同提供的插件市场页面也已无法访问；上列地址仅作来源标注。原项目使用 MIT License，原版权及许可声明如下：

```text
MIT License

Copyright (c) 2026 Kondius

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

### qq-bridge

[Derpyu520/qq-bridge](https://github.com/Derpyu520/qq-bridge)：QQ 消息接入 DSH agent 的桥接项目。本项目参考了其消息桥接与 QQ 安全边界的设计；其代码未包含在本仓库中。该项目使用 MIT License（Copyright (c) 2026 Derpyu520 and qq-bridge / QSH contributors）。

### AstrBot

[AstrBotDevs/AstrBot](https://github.com/AstrBotDevs/AstrBot)：多平台 LLM 聊天机器人框架。本项目仅出于学习研究目的阅读过其公开源码与文档，重点研究了其中 QQ 官方机器人（QQ 开放平台）与微信官方机器人相关适配器的实现，一度考虑将其引入，但最终没有把这两部分（或其任何其他部分）加入本项目。因此：**未使用其中任何组件，未复制、未引用、未派生其任何代码**，两者在代码层面没有任何关联，本仓库不构成其衍生作品。AstrBot 使用 GNU Affero General Public License v3.0（AGPL-3.0）许可，本仓库不受其约束。

## SnowLuma

[SnowLuma](https://github.com/SnowLuma/SnowLuma) 是独立的第三方运行时，不包含在本仓库中。安装脚本从官方发行页获取其 Windows 发行包；其源代码、二进制与原生组件适用 SnowLuma 自己的许可、最终用户许可协议和隐私说明，并非由本项目的 MIT License 授权。具体条款以下载的发行包和官方项目为准。

## 其他组件

Python、Node.js、pywebview、React 和其他依赖均按各自的许可使用，安装后的依赖包中包含相应许可或版权文件。应用的“系统设置 → 关于”页面可查看本机已安装组件的版本和许可元数据；该列表不是完整的第三方版权与许可文本汇总。Microsoft Edge WebView2 运行时和 QQ 适用各自的服务及许可条款。
