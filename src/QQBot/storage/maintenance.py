"""Offline category maintenance; never replace an account database or its settings."""

CATEGORIES = {
    "archives": ("messages", "recalls"),
    "sessions": ("sessions",),
    "memories": ("memories",),
    "stickers": ("stickers",),
}


def counts(connection, account):
    if connection.execute("PRAGMA user_version").fetchone()[0] > 6:
        raise ValueError("数据库版本过高，未读取或清理")
    present = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    return {
        category: connection.execute(
            f"SELECT COUNT(*) FROM {tables[0]} WHERE account=?", (account,)
        ).fetchone()[0]
        if tables[0] in present
        else 0
        for category, tables in CATEGORIES.items()
    }


def clear(connection, account, category):
    if category not in CATEGORIES:
        raise ValueError("数据分类无效")
    # Schema verification happens before DELETE so unknown future databases are
    # never partially modified. Imports/receipts and contact names survive.
    if connection.execute("PRAGMA user_version").fetchone()[0] > 6:
        raise ValueError("数据库版本过高，未清理")
    deleted = counts(connection, account)[category]
    with connection:
        for table in CATEGORIES[category]:
            connection.execute(f"DELETE FROM {table} WHERE account=?", (account,))
    return deleted
