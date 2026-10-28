from qqbot.agent.config import SettingsStore
from qqbot.agent.global_settings import GlobalSettings
from qqbot.agent.persona import DEFAULT_PERSONA
from qqbot.agent.prompt import prompt
from qqbot.storage.database import Database


def test_default_persona_is_used_in_settings_and_model_prompt(tmp_path):
    database = Database(tmp_path / "agent.sqlite3")
    try:
        config = SettingsStore(database).read("12345678")
        assert config["persona"]["roleText"] == DEFAULT_PERSONA
        messages = prompt(config, "12345678", "private:87654321", [], [])
        assert DEFAULT_PERSONA in messages[0]["content"]
    finally:
        database.close()


def test_global_default_initializes_new_accounts_without_overwriting_existing(tmp_path):
    globals_ = GlobalSettings(tmp_path)
    database = Database(tmp_path / "agent.sqlite3")
    try:
        store = SettingsStore(database, global_settings=globals_)
        store.save("12345678", {"persona": {"roleText": "自己的角色", "customRules": "自己的规则"}})
        default = {"roleText": "新的默认角色", "customRules": "新的默认规则"}
        globals_.save("global", {"defaultPersona": default})
        assert GlobalSettings(tmp_path).read()["defaultPersona"] == default
        assert store.read("87654321")["persona"] == default
        assert store.read("12345678")["persona"] == {
            "roleText": "自己的角色", "customRules": "自己的规则"
        }
        assert store.read("12345678")["defaultPersona"] == default
    finally:
        database.close()
