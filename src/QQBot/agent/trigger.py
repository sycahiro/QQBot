"""迁移 QQ Agent prompt.js 的 @ / 关键词 / 随机触发优先级。"""

import json
import re
from random import random


def keyword_text(text):
    text = re.sub(r"\[CQ:at[^\]]*\]", " ", text)
    # Strip whole reply blocks, including nested [图片] placeholders, as upstream.
    while (start := text.find("[引用")) >= 0:
        depth, end = 0, None
        for index in range(start, len(text)):
            if text[index] == "[":
                depth += 1
            elif text[index] == "]":
                depth -= 1
                if depth == 0:
                    end = index
                    break
        if end is None:
            break
        text = text[:start] + " " + text[end + 1 :]
    return re.sub(r"@[^\s]{1,24}", " ", text).lower()


def should_trigger(item, account, config, is_own_message):
    if item.get("self") or item.get("withdrawn"):
        return False
    if not item["chatKey"].startswith("group:") or config["groupTrigger"] == "all":
        return True
    segments = item.get("segments")
    if isinstance(segments, str):
        try:
            segments = json.loads(segments)
        except (ValueError, TypeError):
            pass
    text = []
    if isinstance(segments, list):
        for segment in segments:
            if not isinstance(segment, dict) or not isinstance(segment.get("data"), dict):
                continue
            kind, data = segment.get("type"), segment["data"]
            if kind == "poke":
                return str(data.get("target_id")) == account
            if kind == "at" and str(data.get("qq")) == account:
                return True
            if kind == "reply" and is_own_message(data.get("id")):
                return True
            # Match only message text, never nickname, mention labels, image URL,
            # filenames or quoted text from a different participant.
            text.append(
                data.get("text", "")
                if kind == "text" and isinstance(data.get("text", ""), str)
                else " "
            )
        body = "".join(text)
    else:
        body = segments if isinstance(segments, str) else ""
    if config["groupTrigger"] not in ("keywords", "random"):
        return False
    body = keyword_text(body)
    if any(word.lower() in body for word in config["groupKeywords"]):
        return True
    if config["groupTrigger"] != "random":
        return False
    percent = config["groupRandomPercent"]
    # Upstream resolveContextTier uses roll < randomPercent, after direct calls
    # and keywords. Decide once at admission: the scheduler never rolls again.
    return percent > 0 and (percent == 100 or random() * 100 < percent)
