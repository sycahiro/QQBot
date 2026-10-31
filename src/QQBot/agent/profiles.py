"""模型方案；桌面端使用全局存储，密钥仅保存在本机，检查草稿不会改变当前模型。"""

import copy
import re
import uuid
from urllib.parse import urlsplit


def validate_profiles(config, validate_api):
    profiles, active = config["profiles"], config["activeProfileId"]
    if not isinstance(profiles, list) or len(profiles) > 30 or not isinstance(active, str):
        raise ValueError("模型方案格式无效或超过 30 个")
    ids = set()
    for profile in profiles:
        if not isinstance(profile, dict) or set(profile) != {"id", "name", "api"}:
            raise ValueError("模型方案字段无效")
        if (
            not isinstance(profile["id"], str)
            or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", profile["id"])
            or profile["id"] in ids
        ):
            raise ValueError("模型方案编号无效")
        if not isinstance(profile["name"], str) or not 1 <= len(profile["name"].strip()) <= 64:
            raise ValueError("配置名称应为 1 到 64 字")
        profile["name"] = profile["name"].strip()
        validate_api(profile["api"])
        ids.add(profile["id"])
    if active and active not in ids:
        raise ValueError("当前模型方案不存在")


def public_config(config):
    config = copy.deepcopy(config)
    for api in [config["api"], *(p["api"] for p in config["profiles"])]:
        api["apiKeyConfigured"] = (
            bool(api.pop("apiKey")) if "apiKey" in api else bool(api.get("apiKeyConfigured"))
        )
    return config


def merge_api(base, patch, defaults, validate_api):
    if not isinstance(patch, dict) or set(patch) - set(defaults):
        raise ValueError("模型设置含未知字段")
    api = copy.deepcopy(base)
    # An omitted key retains this profile's key; an explicit empty key clears it.
    if (
        "baseUrl" in patch
        and "apiKey" not in patch
        and api["apiKey"]
        and (urlsplit(str(patch["baseUrl"])).scheme, urlsplit(str(patch["baseUrl"])).netloc)
        != (urlsplit(api["baseUrl"]).scheme, urlsplit(api["baseUrl"]).netloc)
    ):
        raise ValueError(
            "API 地址的协议或主机已改变，请重新填写密钥，或点击清除已保存的密钥并保存"
        )
    api.update(copy.deepcopy(patch))
    return validate_api(api)


def check_api(config, draft, profile_id, defaults, validate_api):
    if draft is None:
        if profile_id and profile_id != "current":
            selected = next((p["api"] for p in config["profiles"] if p["id"] == profile_id), None)
            if selected is None:
                raise ValueError("模型方案不存在，请重新选择")
            return selected
        return config["api"]
    if profile_id == "current":
        base = config["api"]
    elif profile_id:
        base = next((p["api"] for p in config["profiles"] if p["id"] == profile_id), None)
        if base is None:
            raise ValueError("模型方案不存在，请重新选择")
    else:
        base = defaults
    return merge_api(base, draft, defaults, validate_api)


def manage_profile(store, account, operation, data, defaults, validate_api):
    if not isinstance(data, dict):
        raise ValueError("模型方案参数无效")
    config = store.read(account)
    profiles = config["profiles"]
    identifier = data.get("id")
    profile = next((p for p in profiles if p["id"] == identifier), None)
    if operation in ("save", "store"):
        if set(data) - {"id", "name", "api"}:
            raise ValueError("模型方案参数无效")
        if identifier and profile is None:
            raise ValueError("模型方案不存在，请重新选择")
        base = profile["api"] if profile else config["api"] if identifier == "" else defaults
        api = merge_api(base, data.get("api"), defaults, validate_api)
        updated = {"id": identifier or uuid.uuid4().hex, "name": data.get("name"), "api": api}
        if profile:
            profiles[profiles.index(profile)] = updated
        else:
            profiles.append(updated)
        return store.save(
            account,
            {
                "profiles": profiles,
                **(
                    {"activeProfileId": updated["id"], "api": api}
                    if operation == "save"
                    else {"api": api}
                    if updated["id"] == config["activeProfileId"]
                    else {}
                ),
            },
        )
    if set(data) != {"id"} or profile is None:
        raise ValueError("模型方案不存在或参数无效")
    if operation == "use":
        return store.save(account, {"activeProfileId": identifier, "api": profile["api"]})
    if operation == "delete":
        if identifier == config["mediaOptions"]["imageProfileId"]:
            raise ValueError("此配置正被图片理解使用，请先更换对应配置")
        if identifier == config["activeProfileId"]:
            raise ValueError("请先启用另一套配置，再删除当前配置")
        return store.save(account, {"profiles": [p for p in profiles if p["id"] != identifier]})
    raise ValueError("不支持此模型方案操作")
