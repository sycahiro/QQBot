# 桌面前端

React 和 TypeScript 实现桌面界面，通过 pywebview 桥调用 Python 后端。`prepare.mjs` 在启动时将源码构建为单份内存页面，不启动常驻前端服务。

- `src/shell.tsx`：页面布局、导航与状态。
- `src/agent/`：聊天存档、会话、记忆和机器人设置。
- `src/settings/`：全局配置、存储和关于页面。
- `src/components/`：确认框、通知、展开框等共享组件。
- `src/styles/`：主题、桌面布局与组件样式。
- `tests/`：前端行为测试。

修改源码后重新启动应用。安装和检查命令见[项目首页](../../../README.md)。界面代码为本项目编写；React、motion 和图标组件适用各自的许可，详见项目 README 的[许可与第三方声明](../../../README.md#许可与第三方声明)一节。
