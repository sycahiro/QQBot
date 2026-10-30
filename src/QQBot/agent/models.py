"""手动模型目录、基础连通、两轮工具续接与合成图片检查；不操作 QQ。"""

import asyncio
import copy
import json
import time

import httpx

from .llm import ChatClient, ModelError, endpoint
from .llm import headers as api_headers


class ModelChecks:
    def __init__(self, *, transport=None):
        self._transport = transport

    async def test_tools(self, api):
        """Two explicit, synthetic rounds; never dispatch an agent/QQ action."""
        from .prompt import tool

        if not api["baseUrl"] or not api["model"]:
            raise ValueError("请先填写 API 地址和模型名称")
        api = copy.deepcopy(api)
        api["timeoutMs"] = min(api["timeoutMs"], 30000)
        definition = tool(
            "connection_check",
            "仅验证工具协议，不执行实际操作。",
            {"value": {"type": "string", "enum": ["pong"]}},
            ["value"],
        )
        client = ChatClient(transport=self._transport)
        messages = [
            {
                "role": "user",
                "content": "这是独立的工具协议测试。先调用 connection_check，value 填 pong；收到工具结果后，只回复 pong，不要再调用工具。",
            }
        ]
        started = time.monotonic()
        try:
            async with asyncio.timeout(30):
                first = await client.complete(api, messages, [definition])
                calls = first["message"].get("tool_calls") or []
                if (
                    len(calls) != 1
                    or calls[0]["function"]["name"] != "connection_check"
                    or json.loads(calls[0]["function"]["arguments"]) != {"value": "pong"}
                ):
                    raise ModelError("基础请求已返回，但模型未按要求调用测试工具")
                messages += [
                    first["message"],
                    {
                        "role": "tool",
                        "tool_call_id": calls[0]["id"],
                        "content": '{"value":"pong","ok":true}',
                    },
                ]
                second = await client.complete(api, messages, [definition])
                if (
                    second["message"].get("tool_calls")
                    or not (second["message"].get("content") or "").strip()
                ):
                    raise ModelError("工具调用已返回，但模型未完成工具结果回填测试")
        except TimeoutError as error:
            raise ModelError("工具调用测试超过 30 秒，未自动重试") from error
        return {
            "model": second["model"],
            "reply": "工具调用与结果回填正常",
            "latencyMs": round((time.monotonic() - started) * 1000),
            "tokens": first["usage"]["totalTokens"] + second["usage"]["totalTokens"],
        }

    async def list_models(self, api):
        if not api["baseUrl"]:
            raise ValueError("请先填写 API 地址")
        url = endpoint(api["baseUrl"], api.get("protocol", "chat"), models=True)
        headers = api_headers(api)
        try:
            async with asyncio.timeout(15):
                async with httpx.AsyncClient(
                    transport=self._transport, timeout=15, follow_redirects=False
                ) as client, client.stream("GET", url, headers=headers) as response:
                    if response.status_code != 200:
                        raise ModelError(
                            f"获取模型列表返回 HTTP {response.status_code}；部分服务没有列表接口，仍可手动填写模型名称"
                        )
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 2 * 1024 * 1024:
                            raise ModelError("模型列表超过 2 MB 上限")
            parsed = json.loads(data)
            rows = parsed.get("data") if isinstance(parsed, dict) else parsed
            if not isinstance(rows, list):
                raise ModelError("模型列表格式无效，仍可手动填写模型名称")
            names = set()
            for row in rows[:10000]:
                value = row.get("id", row.get("model")) if isinstance(row, dict) else row
                if (
                    isinstance(value, str)
                    and 0 < len(value.strip()) <= 256
                    and not any(ord(c) < 32 for c in value)
                ):
                    names.add(value.strip())
                if len(names) >= 2000:
                    break
            return sorted(names, key=str.casefold)
        except ModelError:
            raise
        except TimeoutError as error:
            raise ModelError("获取模型列表超时") from error
        except httpx.HTTPError as error:
            raise ModelError("获取模型列表失败，请检查地址和网络") from error
        except (ValueError, TypeError) as error:
            raise ModelError("模型列表格式无效") from error

    async def test_image(self, api):
        if not api["baseUrl"] or not api["model"]:
            raise ValueError("请先填写 API 地址和模型名称")
        api = copy.deepcopy(api)
        api.update(vision=True, visionModel="")
        started = time.monotonic()
        api["timeoutMs"] = min(api["timeoutMs"], 30000)
        result = await ChatClient(transport=self._transport).complete(
            api,
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请只回答这张测试图片的主要颜色。"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEklEQVR4nGP8z4AdMOEQH6QSAM1BAQ/oQeJvAAAAAElFTkSuQmCC"
                            },
                        },
                    ],
                }
            ],
            None,
        )
        reply = result["message"].get("content")
        if not isinstance(reply, str) or not reply.strip():
            raise ModelError("模型未返回图片理解结果")
        return {
            "model": result["model"],
            "reply": reply[:100],
            "latencyMs": round((time.monotonic() - started) * 1000),
            "tokens": result["usage"]["totalTokens"],
        }

    async def test(self, api):
        if not api["baseUrl"] or not api["model"]:
            raise ValueError("请先填写 API 地址和模型名称")
        api = copy.deepcopy(api)
        api["timeoutMs"] = min(api["timeoutMs"], 30000)
        started = time.monotonic()
        result = await ChatClient(transport=self._transport).complete(
            api, [{"role": "user", "content": "请只回复：pong"}], None
        )
        if not (result["message"].get("content") or "").strip():
            raise ModelError("接口返回了空内容，尚不能确认模型可以正常回复")
        return {
            "model": result["model"],
            "reply": (result["message"].get("content") or "")[:100],
            "latencyMs": round((time.monotonic() - started) * 1000),
            "tokens": result["usage"]["totalTokens"],
        }
