"""合成账号行为与全局服务设置；密钥仅保存在本机，不返回界面。"""

import copy
import json
import math
from urllib.parse import urlsplit

from ..storage.messages import PEER_RE, account_id
from .media_models import DEFAULT_MEDIA, FEATURES, validate_media
from .persona import DEFAULT_PERSONA
from .profiles import check_api, manage_profile, public_config, validate_profiles
from .web import (
    DEFAULT_SEARCH,
    merge_search,
    validate_search,
)

DEFAULTS = {
    "api": {
        "protocol": "chat",
        "sendTemperature": True,
        "maxOutputTokens": 4096,
        "chatTokenLimitField": "max_tokens",
        "baseUrl": "",
        "apiKey": "",
        "model": "",
        "temperature": 0.8,
        "maxRounds": 12,
        "timeoutMs": 90000,
        "vision": False,
        "visionModel": "",
        "sendImages": False,
    },
    "persona": {
        "roleText": DEFAULT_PERSONA,
        "customRules": "",
    },
    "defaultPersona": {"roleText": DEFAULT_PERSONA, "customRules": ""},
    "allow": {"groups": [], "private": []},
    "deny": {"groups": [], "private": []},
    "blockedUsers": [],
    "ownerQQ": "",
    "groupTrigger": "at",
    "groupKeywords": [],
    "groupRandomPercent": 10,
    "contextLimit": 40,
    "profiles": [],
    "activeProfileId": "",
    "mediaOptions": copy.deepcopy(DEFAULT_MEDIA),
    "webSearch": copy.deepcopy(DEFAULT_SEARCH),
    "sticker": {"enabled": False, "collectEnabled": False, "allowPoke": False},
}


GLOBAL_FIELDS = frozenset({"api", "profiles", "activeProfileId", "webSearch", "mediaOptions", "defaultPersona", "ownerQQ"})


def id_list(value):
    if not isinstance(value, list) or len(value) > 1000:
        raise ValueError("名单必须为不超过 1000 项的号码列表")
    if any(not isinstance(item, str) or not PEER_RE.fullmatch(item) for item in value):
        raise ValueError("名单中含有无效号码")
    return list(dict.fromkeys(value))


def validate_api(api):
    if isinstance(api, dict):
        for field in ("protocol", "sendTemperature", "maxOutputTokens", "chatTokenLimitField"):
            api.setdefault(field, DEFAULTS["api"][field])
    if not isinstance(api, dict):
        raise ValueError("模型设置格式无效")
    if api.get("protocol") not in ("chat", "responses", "anthropic"):
        raise ValueError("API 协议无效")
    if type(api.get("sendTemperature")) is not bool:
        raise ValueError("Temperature 选项无效")
    if type(api.get("maxOutputTokens")) is not int or not 1 <= api["maxOutputTokens"] <= 65536:
        raise ValueError("输出 Token 上限应为 1 到 65536")
    if api.get("chatTokenLimitField") not in ("max_tokens", "max_completion_tokens"):
        raise ValueError("Chat 输出 Token 参数无效")
    if not isinstance(api, dict) or set(api) != set(DEFAULTS["api"]):
        raise ValueError("模型设置字段不完整")
    for field, limit in [
        ("baseUrl", 2048),
        ("apiKey", 8192),
        ("model", 256),
        ("visionModel", 256),
    ]:
        if not isinstance(api[field], str) or len(api[field]) > limit:
            raise ValueError("模型设置过长或格式错误")
        api[field] = api[field].strip()
        if field != "baseUrl" and any(ord(char) < 32 for char in api[field]):
            raise ValueError("模型名称和密钥不能包含换行或控制字符")
    if api["baseUrl"]:
        parsed = urlsplit(api["baseUrl"])
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError("API 地址必须是有效的 HTTP/HTTPS 地址，密钥请单独填写")
    if (
        type(api["temperature"]) not in (int, float)
        or not math.isfinite(api["temperature"])
        or not 0 <= api["temperature"] <= 2
    ):
        raise ValueError("Temperature 应在 0 到 2 之间")
    if type(api["maxRounds"]) is not int or not 1 <= api["maxRounds"] <= 20:
        raise ValueError("工具轮数应在 1 到 20 之间")
    if type(api["timeoutMs"]) is not int or not 1000 <= api["timeoutMs"] <= 300000:
        raise ValueError("模型超时应在 1 到 300 秒之间")
    if type(api["vision"]) is not bool:
        raise ValueError("图片理解开关必须为布尔值")
    if type(api["sendImages"]) is not bool:
        raise ValueError("图片发送开关必须为布尔值")
    return api


def validate(config):
    if set(config) != set(DEFAULTS):
        raise ValueError("机器人设置包含未知字段")
    validate_api(config["api"])
    validate_profiles(config, validate_api)
    validate_media(config)
    validate_search(config["webSearch"])
    if (
        not isinstance(config["sticker"], dict)
        or set(config["sticker"]) != set(DEFAULTS["sticker"])
        or any(type(v) is not bool for v in config["sticker"].values())
    ):
        raise ValueError("表情库开关格式无效")
    for field in ("persona", "defaultPersona"):
        persona = config[field]
        if not isinstance(persona, dict) or set(persona) != set(DEFAULTS[field]):
            raise ValueError("人设设置字段不完整")
        if any(not isinstance(value, str) or len(value) > 20000 for value in persona.values()):
            raise ValueError("人设文本过长或格式错误")
    for field in ("allow", "deny"):
        if not isinstance(config[field], dict) or set(config[field]) != {"groups", "private"}:
            raise ValueError("会话名单格式错误")
        for kind in ("groups", "private"):
            config[field][kind] = id_list(config[field][kind])
    config["blockedUsers"] = id_list(config["blockedUsers"])
    owner = config["ownerQQ"]
    if not isinstance(owner, str) or (owner and not PEER_RE.fullmatch(owner)):
        raise ValueError("管理员 QQ 号格式无效")
    if config["groupTrigger"] not in ("at", "keywords", "random", "all"):
        raise ValueError("群聊触发方式无效")
    if (
        type(config["groupRandomPercent"]) is not int
        or not 0 <= config["groupRandomPercent"] <= 100
    ):
        raise ValueError("群聊触发概率应为 0 到 100 的整数百分比")
    words = config["groupKeywords"]
    if not isinstance(words, list) or len(words) > 100:
        raise ValueError("群聊关键词最多 100 项")
    if any(
        not isinstance(word, str)
        or not 1 <= len(word.strip()) <= 64
        or any(ord(c) < 32 for c in word)
        for word in words
    ):
        raise ValueError("每个群聊关键词应为 1 到 64 字的单行文本")
    normalized = {}
    for word in words:
        normalized.setdefault(word.strip().lower(), word.strip())
    config["groupKeywords"] = list(normalized.values())
    if type(config["contextLimit"]) is not int or not 1 <= config["contextLimit"] <= 200:
        raise ValueError("历史条数应在 1 到 200 之间")
    return config


class SettingsStore:
    def __init__(self, database, *, global_settings=None):
        self._database, self._global_settings = database, global_settings

    def read(self, account, *, public=False):
        account_id(account)
        with self._database.lock:
            row = self._database.connection.execute(
                "SELECT value FROM settings WHERE account=?", (account,)
            ).fetchone()
        try:
            config = json.loads(row["value"]) if row else copy.deepcopy(DEFAULTS)
            if isinstance(config, dict):
                config.setdefault("defaultPersona", copy.deepcopy(DEFAULTS["defaultPersona"]))
            if self._global_settings is not None:
                config = {**copy.deepcopy(DEFAULTS), **config, **self._global_settings.values()}
                config["api"].update({key: config["mediaOptions"][key] for key in FEATURES})
                if not row:
                    config["persona"] = copy.deepcopy(config["defaultPersona"])
            config = validate(config)
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError("机器人设置无法读取，原数据已保留") from error
        return public_config(config) if public else config

    def save(self, account, patch):
        if not isinstance(patch, dict) or set(patch) - set(DEFAULTS):
            raise ValueError("设置包含未知字段")
        if self._global_settings is not None and set(patch) & GLOBAL_FIELDS:
            raise ValueError("模型和联网配置请在系统设置中保存")
        with self._database.transaction() as db:
            config = self.read(account)
            merge_config(config, patch)
            db.execute(
                "INSERT INTO settings(account,value) VALUES(?,?) ON CONFLICT(account) DO UPDATE SET value=excluded.value",
                (
                    account,
                    json.dumps(
                        {
                            k: v
                            for k, v in config.items()
                            if self._global_settings is None or k not in GLOBAL_FIELDS
                        },
                        ensure_ascii=False,
                        allow_nan=False,
                    ),
                ),
            )
        return self.read(account, public=True)

    def profile(self, account, operation, data):
        if self._global_settings is not None:
            raise ValueError("模型方案请在系统设置中保存")
        with self._database.lock:
            return manage_profile(self, account, operation, data, DEFAULTS["api"], validate_api)

    def check_api(self, account, draft=None, profile_id=None):
        return check_api(self.read(account), draft, profile_id, DEFAULTS["api"], validate_api)

    def check_search(self, account, draft):
        config = self.read(account)
        config["webSearch"] = merge_search(config["webSearch"], draft)
        return config["webSearch"]


def merge_config(config, patch):
    for field, value in patch.items():
        if isinstance(DEFAULTS[field], dict):
            if not isinstance(value, dict) or set(value) - set(DEFAULTS[field]):
                raise ValueError("设置字段无效")
            if field == "webSearch":
                value = merge_search(config[field], value)
            config[field].update(copy.deepcopy(value))
        else:
            config[field] = copy.deepcopy(value)
    if "api" in patch and config["activeProfileId"]:
        for profile in config["profiles"]:
            if profile["id"] == config["activeProfileId"]:
                profile["api"] = copy.deepcopy(config["api"])
    validate(config)
    return config


def allowed(kind, peer, sender, config):
    """与原 app.js allowed 一致：拒绝优先；白名单为空时不放行。管理员不受名单限制。"""
    if str(sender) == config.get("ownerQQ") and config.get("ownerQQ"):
        return True
    field = "groups" if kind == "group" else "private"
    return (
        str(peer) not in config["deny"][field]
        and str(peer) in config["allow"][field]
        and str(sender) not in config["blockedUsers"]
    )
