import pytest

from qqbot.agent.config import SettingsStore
from qqbot.desktop.bridge import DesktopBridge
from qqbot.desktop.debug import (
    ACTION_HELP,
    READ_ACTIONS,
    SEND_ACTIONS,
    Activity,
    catalog,
)
from qqbot.desktop.paths import DesktopPaths
from qqbot.qq.engine import EngineError
from qqbot.storage.database import Database
from qqbot.storage.messages import MessageStore

ACCOUNT, OTHER, PEER = "12345678", "87654321", "11223344"


def test_supported_actions_have_specific_task_names_without_changing_execution_scope():
    assert set(ACTION_HELP) == set(READ_ACTIONS) | SEND_ACTIONS

    class Connection:
        def action_docs(self):
            return [
                {"name": n, "summary": "消息", "params": []}
                for n in [*ACTION_HELP, "set_group_ban"]
            ]

    docs = catalog(Connection())
    supported = [d for d in docs if d["callable"]]
    assert len(supported) == 25 and len({d["summary"] for d in supported}) == 25
    assert all(
        d["description"].endswith("。") and d["summary"] not in ("信息", "消息") for d in supported
    )
    assert docs[-1]["name"] == "set_group_ban" and not docs[-1]["callable"]


@pytest.fixture
def debug(tmp_path):
    class Selection:
        value = ACCOUNT

        def read(self):
            return self.value

    class Connection:
        calls = []
        error = None

        def status(self):
            return {"state": "ready", "connected": True, "account": {"uin": selected.value}}

        def action_docs(self):
            return [
                {"name": "get_login_info", "params": [], "readOnly": True},
                {"name": "set_group_ban", "params": [], "readOnly": False},
            ]

        def invoke(self, action, params, expected_account=None):
            assert expected_account == selected.value
            self.calls.append((action, params))
            if self.error:
                raise self.error
            return {"status": "ok", "data": {"message_id": -len(self.calls)}}

    db = Database(tmp_path / "debug.sqlite3")
    selected = Selection()
    connection = Connection()
    connection.calls = []
    settings = SettingsStore(db)
    settings.save(ACCOUNT, {"allow": {"private": [PEER], "groups": ["99887766"]}})
    messages = MessageStore(db)
    bridge = DesktopBridge(
        DesktopPaths(tmp_path, tmp_path),
        lambda **kwargs: None,
        selection=selected,
        connection=connection,
        settings=settings,
        messages=messages,
    )
    yield bridge, connection, selected, messages
    db.close()


def test_snowluma_summary_docs_fall_back_to_local_action_table():
    class SnowLumaConnection:
        def action_docs(self):
            return {"actions": "OneBot 11 标准动作；业务侧仅允许白名单动作。"}

    docs = catalog(SnowLumaConnection())
    assert {d["name"] for d in docs} == set(READ_ACTIONS) | SEND_ACTIONS
    assert all(d["callable"] for d in docs)
    assert {d["summary"] for d in docs} == {title for title, _ in ACTION_HELP.values()}
    assert all(d["readOnly"] == (d["name"] in READ_ACTIONS) for d in docs)


def test_original_docs_are_browsable_but_unknown_writes_are_not_callable(debug):
    bridge, conn, _, _ = debug
    docs = bridge.get_debug_catalog(ACCOUNT)["actions"]
    assert docs[0]["callable"] is True and docs[1]["callable"] is False
    assert not bridge.run_debug_action("set_group_ban", {}, ACCOUNT)["ok"] and not conn.calls
    assert not bridge.run_debug_action([], {}, ACCOUNT)["ok"]


def test_new_manual_and_contact_methods_reject_stale_account_before_work(debug):
    bridge, connection, selected, _ = debug

    class Agent:
        calls = []

        def process_once(self, *args, **kwargs):
            self.calls.append(args)
            return {"accepted": True, "chatKey": args[1]}

        def stop_session(self, *args):
            self.calls.append(args)
            return {"stopping": True}

    bridge._agent = Agent()
    for operation in [
        lambda: bridge.get_contacts(OTHER),
        lambda: bridge.process_archive(f"private:{PEER}", OTHER),
        lambda: bridge.stop_session("session", OTHER),
        lambda: bridge.rerun_session("session", OTHER),
    ]:
        assert not operation()["ok"]
    assert not bridge._agent.calls and not connection.calls
    assert bridge.process_archive(f"private:{PEER}", ACCOUNT)["ok"]
    assert bridge._agent.calls == [(ACCOUNT, f"private:{PEER}")]


def test_contact_picker_updates_names_only_after_account_is_rechecked(debug):
    bridge, connection, selected, messages = debug

    def query(action, params=None, expected_account=None):
        assert expected_account == ACCOUNT
        return {
            "status": "ok",
            "data": [{"group_id": "99887766", "group_name": "测试群"}]
            if action == "get_group_list"
            else [{"user_id": PEER, "nickname": "昵称", "remark": "好友备注"}],
        }

    connection.invoke = query
    result = bridge.get_contacts(ACCOUNT)
    assert result["ok"] and result["private"][0]["name"] == "好友备注"
    assert messages.name(ACCOUNT, f"private:{PEER}") == "好友备注"

    def changed(action, params=None, expected_account=None):
        selected.value = OTHER
        return {"status": "ok", "data": [{"user_id": PEER, "nickname": "不应覆盖"}]}

    connection.invoke = changed
    assert not bridge.get_contacts(ACCOUNT)["ok"]
    assert messages.name(ACCOUNT, f"private:{PEER}") == "好友备注"


def test_debug_actions_reject_wrong_account_unknown_params_and_non_whitelisted_group(debug):
    bridge, conn, _, _ = debug
    assert not bridge.run_debug_action("get_login_info", {}, OTHER)["ok"]
    assert not bridge.run_debug_action("get_login_info", {"anything": True}, ACCOUNT)["ok"]
    assert not bridge.run_debug_action("get_group_info", {"group_id": "88776655"}, ACCOUNT)["ok"]
    assert not conn.calls
    assert bridge.run_debug_action("get_login_info", {}, ACCOUNT)["ok"]
    assert bridge.run_debug_action("get_group_info", {"group_id": "99887766"}, ACCOUNT)["ok"]


def test_manual_text_sends_are_scoped_receipted_deduped_and_visible_as_activity(debug):
    bridge, conn, _, messages = debug
    assert not bridge.run_debug_action(
        "send_private_msg", {"user_id": OTHER, "message": "hello"}, ACCOUNT
    )["ok"]
    assert not conn.calls
    args = {"user_id": PEER, "message": "hello"}
    assert bridge.run_debug_action("send_private_msg", args, ACCOUNT)["result"]["sent"] == 1
    assert bridge.run_debug_action("send_private_msg", args, ACCOUNT)["result"]["deduped"] == 1
    assert len(conn.calls) == 1 and messages.list_chats(ACCOUNT)[0]["count"] == 1
    events = bridge.get_debug_activity(ACCOUNT, 0)
    assert len(events["items"]) == 3 and all(e["account"] == ACCOUNT for e in events["items"])
    assert events["items"][0]["kind"] == "error" and all("detail" in e for e in events["items"])
    assert not bridge.get_debug_activity(OTHER, 0)["ok"]


def test_debug_unknown_delivery_is_not_retried(debug):
    bridge, conn, _, _ = debug
    conn.error = EngineError("REQUEST_TIMEOUT", "private-error")
    result = bridge.run_debug_action(
        "send_private_msg", {"user_id": PEER, "message": "hello"}, ACCOUNT
    )
    assert not result["ok"] and "未确认" in result["error"]["message"] and len(conn.calls) == 1


def test_activity_is_memory_bounded_filtered_by_account_and_cursor():
    activity = Activity()
    for i in range(250):
        activity.add(ACCOUNT if i % 2 else OTHER, "message", str(i))
    result = activity.read(ACCOUNT)
    assert len(result["items"]) == 100 and all(e["account"] == ACCOUNT for e in result["items"])
    assert activity.read(ACCOUNT, result["cursor"])["items"] == []
    with pytest.raises(ValueError):
        activity.read(ACCOUNT, True)


@pytest.mark.parametrize(
    "field", ["apiKey", "api_key", "API-KEY", "access_key", "privateKey", "credentials"]
)
def test_rejected_debug_parameters_cannot_echo_credentials_in_activity(debug, field):
    bridge, conn, _, _ = debug
    secret = "synthetic-secret-never-display"
    assert not bridge.run_debug_action("get_login_info", {field: secret}, ACCOUNT)["ok"]
    events = bridge.get_debug_activity(ACCOUNT)
    detail = events["items"][-1]["detail"]
    assert detail["parameters"][field] == "[已隐藏]"
    assert secret not in str(events) and not conn.calls
