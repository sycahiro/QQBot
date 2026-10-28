"""Validate a whole model action batch before its first side effect."""

import json

from .llm import ModelError


def validate_calls(calls, tools, seen):
    available = {tool["function"]["name"] for tool in tools}
    batch, identifiers = [], set()
    try:
        for index, call in enumerate(calls):
            identifier = call["id"]
            if identifier in seen or identifier in identifiers:
                raise ModelError("模型返回了重复的工具调用编号，整批工具未执行")
            identifiers.add(identifier)
            name = call["function"]["name"]
            if name not in available:
                raise ModelError("模型调用了本次未提供的工具，整批工具未执行")
            if name == "finish" and index != len(calls) - 1:
                raise ModelError("结束处理必须是本批最后一个工具，整批工具未执行")
            args = json.loads(call["function"]["arguments"])
            if not isinstance(args, dict):
                raise ModelError("工具参数必须为对象，整批工具未执行")
            batch.append((identifier, name, args))
    except (KeyError, TypeError, ValueError) as error:
        raise ModelError("模型工具调用格式无效，整批工具未执行") from error
    seen.update(identifiers)
    return batch
