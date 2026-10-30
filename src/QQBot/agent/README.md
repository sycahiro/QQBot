# 机器人业务

本目录负责消息准入、模型调用、会话调度、图片和表情处理，不直接管理桌面窗口。

- `config.py`、`global_settings.py`、`profiles.py`：账号与全局设置、模型方案及校验。
- `receiver.py`、`trigger.py`、`service.py`：消息接收、触发判断和任务调度。
- `llm.py`、`models.py`、`prompt.py`：模型协议、连接检查和工具提示。
- `images.py`、`media_models.py`、`outgoing_images.py`：图片理解和发送。
- `sender.py`、`stickers.py`：消息发送和表情库。
- `web.py`、`web_browser.py`、`web_pages.py`：搜索与网页读取。

自动回复默认关闭。图片理解按需开启，动图只读取首帧；当前不提供视频识别。模型或搜索请求会发送到用户配置的服务。

设置分为全局设置和账号设置；当前不自动迁移旧配置。业务和交互设计参考了 QQ Agent，许可说明见[第三方声明](../../../../THIRD_PARTY_NOTICES.md)。
