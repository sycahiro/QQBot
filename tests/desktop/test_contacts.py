"""群成员列表读取（记忆页手动新建记忆的选人数据源）。"""

import pytest

from QQBot.desktop import contacts
from QQBot.qq.engine import EngineError


class FakeConnection:
    def __init__(self, data):
        self._data = data
        self.calls = []

    def invoke(self, action, params=None, *, expected_account=None):
        self.calls.append((action, params, expected_account))
        if action == "fail":
            return {"status": "failed"}
        return {"status": "ok", "data": self._data}


def test_group_members_prefers_card_and_sorts_by_name():
    connection = FakeConnection(
        [
            {"user_id": 20003, "card": "阿泠", "nickname": "原始昵称"},
            {"user_id": 20001, "card": "", "nickname": "波奇"},
            {"user_id": 20002, "card": "阿泠"},  # 与 20003 同名，按号码排序
            {"user_id": "bad-id"},  # 非数字跳过
            {"nickname": "没有号码"},  # 缺 user_id 跳过
            "not-a-dict",  # 异常项跳过
        ]
    )
    items = contacts.group_members(connection, "10001", "88776655")
    assert [item["id"] for item in items] == ["20001", "20002", "20003"]
    assert [item["name"] for item in items] == ["波奇", "阿泠", "阿泠"]
    assert connection.calls == [("get_group_member_list", {"group_id": "88776655"}, "10001")]


def test_group_members_validates_group_id():
    connection = FakeConnection([])
    with pytest.raises(ValueError, match="群号"):
        contacts.group_members(connection, "10001", "not-a-number")
    assert not connection.calls


def test_group_members_reports_engine_error_on_bad_response():
    connection = FakeConnection([])
    connection._data = None
    with pytest.raises(EngineError, match="群成员列表读取失败"):
        contacts.group_members(connection, "10001", "88776655")
