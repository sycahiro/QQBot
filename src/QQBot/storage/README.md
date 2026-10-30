# 业务存储

本目录负责账号数据库和业务数据的读写与维护。

- `accounts.py`：为每个账号管理独立数据库和存储接口。
- `database.py`：SQLite 连接、事务和数据库版本管理。
- `messages.py`、`sessions.py`、`memory.py`、`stickers.py`：聊天、处理会话、记忆和表情库。
- `maintenance.py`、`files.py`：受限的数据清理与文件路径检查。

账号业务数据库位于 `runtime/accounts/<QQ号>/agent.sqlite3`，全局设置和日志单独保存。存储管理提供按分类清理，清理前应确认所选内容。
