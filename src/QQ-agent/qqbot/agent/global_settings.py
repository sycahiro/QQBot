"""Shared model and network configuration, independent of QQ account folders."""

import copy
import json
import threading

from ..desktop.paths import save_state
from .config import DEFAULTS, GLOBAL_FIELDS, merge_config, validate, validate_api
from .media_models import FEATURES
from .profiles import check_api, manage_profile, public_config
from .web import merge_search, resolve_search_api

MEDIA_FIELDS = frozenset({"vision", "visionModel", "sendImages"})


class GlobalSettings:
    def __init__(self, runtime):
        self._file = runtime / "global-settings.json"
        self._lock = threading.RLock()

    def read(self, scope="global", *, public=False):
        if scope != "global":
            raise ValueError("无效的全局配置范围")
        with self._lock:
            config = copy.deepcopy(DEFAULTS)
            if self._file.exists():
                try:
                    raw = json.loads(self._file.read_text(encoding="utf-8"))
                    if not isinstance(raw, dict) or set(raw) != GLOBAL_FIELDS:
                        raise ValueError()
                    config.update(raw)
                    validate(config)
                except (ValueError, TypeError, KeyError, OSError) as error:
                    raise ValueError("全局设置无法读取，原文件已保留。删除 runtime/global-settings.json 可重置全局设置为默认值，原全局设置将丢失") from error
        config["api"].update({k: config["mediaOptions"][k] for k in FEATURES})
        return public_config(config) if public else config

    def values(self):
        config = self.read()
        return {key: config[key] for key in GLOBAL_FIELDS}

    def save(self, scope, patch):
        if scope != "global" or not isinstance(patch, dict) or set(patch) - GLOBAL_FIELDS:
            raise ValueError("全局设置包含未知字段")
        with self._lock:
            config = merge_config(self.read(), patch)
            config["api"].update({k: config["mediaOptions"][k] for k in FEATURES})
            save_state(self._file, {key: config[key] for key in GLOBAL_FIELDS})
            return public_config(config)

    def profile(self, scope, operation, data):
        with self._lock:
            return manage_profile(self, scope, operation, data, DEFAULTS["api"], validate_api)

    def save_media(self, patch, profile_id):
        """Only update media options of the still-active saved profile."""
        with self._lock:
            config = self.read()
            if not isinstance(profile_id, str) or profile_id != config["activeProfileId"]:
                raise ValueError("当前模型方案已变化，请重新打开图片处理设置")
            if not isinstance(patch, dict) or set(patch) - MEDIA_FIELDS:
                raise ValueError("图片处理设置包含未知字段")
            return self.save(
                "global",
                {"api": patch, "mediaOptions": {k: v for k, v in patch.items() if k in FEATURES}},
            )

    def check_api(self, scope="global", draft=None, profile_id=None):
        return check_api(self.read(scope), draft, profile_id, DEFAULTS["api"], validate_api)

    def check_search(self, scope, draft):
        config = self.read(scope)
        config["webSearch"] = merge_search(config["webSearch"], draft)
        resolve_search_api(config)
        return config["webSearch"]
