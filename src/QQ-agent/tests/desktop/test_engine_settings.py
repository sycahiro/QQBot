import json

import pytest

from qqbot.desktop.bridge import DesktopBridge
from qqbot.desktop.paths import DesktopPaths


@pytest.fixture
def instance(tmp_path, monkeypatch):
    # snowluma_home 锚定真实根目录（与生产数据库同位置）；测试必须隔离到 tmp。
    home = tmp_path / "snowluma-home"
    monkeypatch.setattr(DesktopPaths, "snowluma_home", property(lambda self: home))
    return DesktopBridge(DesktopPaths(tmp_path, tmp_path / "runtime"), lambda **_: None)


def seeded_config():
    return {
        "networks": {"wsServers": [{"accessToken": "secret-token"}]},
        "statusCommand": {"enabled": False, "swallow": False, "cooldownSeconds": 5, "trigger": "#sl"},
        "historySync": {"enabled": False},
        "notifications": {"channelIds": []},
    }


def test_missing_config_returns_engine_defaults_without_creating_file(instance):
    result = instance.get_engine_settings()
    assert result["ok"] is True
    assert result["engineConfigured"] is False
    assert result["statusCommand"] == {
        "enabled": False,
        "swallow": False,
        "cooldownSeconds": 5,
        "trigger": "#sl",
    }
    assert result["historySync"] == {"enabled": False}
    assert not instance._paths.snowluma_onebot_config.exists()


def test_save_writes_sections_and_preserves_token_and_other_keys(instance):
    config_file = instance._paths.snowluma_onebot_config
    config_file.parent.mkdir(parents=True)
    config_file.write_text(json.dumps(seeded_config()), encoding="utf-8")

    result = instance.save_engine_settings(
        {"enabled": True, "swallow": True, "cooldownSeconds": 10, "trigger": "#状态"},
        {"enabled": True},
    )
    assert result["ok"] is True
    assert result["statusCommand"]["trigger"] == "#状态"

    stored = json.loads(config_file.read_text(encoding="utf-8"))
    assert stored["networks"]["wsServers"][0]["accessToken"] == "secret-token"
    assert stored["notifications"] == {"channelIds": []}
    assert stored["statusCommand"] == {
        "enabled": True,
        "swallow": True,
        "cooldownSeconds": 10,
        "trigger": "#状态",
    }
    assert stored["historySync"] == {"enabled": True}

    reloaded = instance.get_engine_settings()
    assert reloaded["ok"] is True and reloaded["engineConfigured"] is True
    assert reloaded["statusCommand"]["enabled"] is True


def test_save_from_missing_file_starts_from_managed_defaults(instance):
    result = instance.save_engine_settings(
        {"enabled": True, "swallow": False, "cooldownSeconds": 0, "trigger": "#sl"},
        {"enabled": False},
    )
    assert result["ok"] is True
    stored = json.loads(instance._paths.snowluma_onebot_config.read_text(encoding="utf-8"))
    # 缺省文件按受控默认值补齐网络与 token 字段，引擎首启时接管同一份文件。
    assert stored["networks"]["wsServers"][0]["host"] == "127.0.0.1"
    assert stored["statusCommand"]["cooldownSeconds"] == 0


@pytest.mark.parametrize(
    "status_command,history_sync",
    [
        ({"enabled": True, "swallow": False, "cooldownSeconds": 5}, {"enabled": False}),
        (
            {"enabled": "yes", "swallow": False, "cooldownSeconds": 5, "trigger": "#sl"},
            {"enabled": False},
        ),
        ({"enabled": True, "swallow": False, "cooldownSeconds": -1, "trigger": "#sl"}, {"enabled": False}),
        ({"enabled": True, "swallow": False, "cooldownSeconds": 4000, "trigger": "#sl"}, {"enabled": False}),
        ({"enabled": True, "swallow": False, "cooldownSeconds": 5, "trigger": ""}, {"enabled": False}),
        (
            {"enabled": True, "swallow": False, "cooldownSeconds": 5, "trigger": "x" * 33},
            {"enabled": False},
        ),
        ({"enabled": True, "swallow": False, "cooldownSeconds": 5, "trigger": " #sl "}, {"enabled": False, "extra": 1}),
    ],
)
def test_invalid_settings_are_rejected_without_touching_the_file(
    instance, status_command, history_sync
):
    config_file = instance._paths.snowluma_onebot_config
    config_file.parent.mkdir(parents=True)
    config_file.write_text(json.dumps(seeded_config()), encoding="utf-8")
    before = config_file.read_text(encoding="utf-8")

    result = instance.save_engine_settings(status_command, history_sync)
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_INPUT"
    assert config_file.read_text(encoding="utf-8") == before


def test_trigger_is_trimmed_and_empty_config_is_rejected(instance):
    config_file = instance._paths.snowluma_onebot_config
    config_file.parent.mkdir(parents=True)
    config_file.write_text("not-json", encoding="utf-8")

    broken = instance.get_engine_settings()
    assert broken["ok"] is False
    assert broken["error"]["code"] == "INVALID_INPUT"

    config_file.write_text(json.dumps(seeded_config()), encoding="utf-8")
    result = instance.save_engine_settings(
        {"enabled": True, "swallow": False, "cooldownSeconds": 5, "trigger": "  #SL  "},
        {"enabled": False},
    )
    assert result["ok"] is True
    assert result["statusCommand"]["trigger"] == "#SL"
