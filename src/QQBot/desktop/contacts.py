"""复用 QQ 原生好友/群查询，为白名单提供可勾选的账号目录。"""

import re

from ..qq.engine import EngineError


def read(connection, account):
    result = {}
    for kind, action, field in [
        ("groups", "get_group_list", "group_id"),
        ("private", "get_friend_list", "user_id"),
    ]:
        response = connection.invoke(action, expected_account=account)
        if (
            not isinstance(response, dict)
            or response.get("status") != "ok"
            or not isinstance(response.get("data"), list)
        ):
            raise EngineError("CONTACTS_FAILED", "QQ 联系人列表读取失败，请稍后手动刷新")
        entries = {}
        for item in response["data"][:20000]:
            if not isinstance(item, dict):
                continue
            identifier = str(item.get(field, ""))
            if not re.fullmatch(r"[1-9]\d{0,19}", identifier):
                continue
            name = (
                item.get("group_name")
                if kind == "groups"
                else item.get("remark") or item.get("nickname")
            )
            name = str(name or "")[:256]
            entries[identifier] = {"id": identifier, "name": name or identifier}
        result[kind] = sorted(
            entries.values(), key=lambda item: (item["name"].casefold(), item["id"])
        )
    return result


def group_members(connection, account, group_id):
    """读取群成员列表（群名片优先），供记忆页手动挑选成员新建记忆。"""
    if not isinstance(group_id, str) or not re.fullmatch(r"[1-9]\d{0,19}", group_id):
        raise ValueError("群号格式无效")
    response = connection.invoke(
        "get_group_member_list", {"group_id": group_id}, expected_account=account
    )
    if (
        not isinstance(response, dict)
        or response.get("status") != "ok"
        or not isinstance(response.get("data"), list)
    ):
        raise EngineError("CONTACTS_FAILED", "群成员列表读取失败，请稍后手动刷新")
    entries = {}
    for item in response["data"][:20000]:
        if not isinstance(item, dict):
            continue
        identifier = str(item.get("user_id", ""))
        if not re.fullmatch(r"[1-9]\d{0,19}", identifier):
            continue
        name = item.get("card") or item.get("nickname")
        name = str(name or "")[:256]
        entries[identifier] = {"id": identifier, "name": name or identifier}
    return sorted(entries.values(), key=lambda item: (item["name"].casefold(), item["id"]))
