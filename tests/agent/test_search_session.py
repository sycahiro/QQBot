import asyncio

import httpx

from QQBot.agent.web import WebClient


async def resolve(host):
    return "93.184.216.34"


def test_anonymous_page_reader_does_not_forward_cookies_between_hosts_with_one_pinned_ip():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/first":
            return httpx.Response(
                302,
                headers={
                    "location": "https://other.example/second",
                    "set-cookie": "private=do-not-forward; Path=/",
                },
            )
        assert not request.headers.get("cookie")
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="done")

    reader = WebClient(transport=httpx.MockTransport(handler), resolver=resolve)
    assert (
        asyncio.run(reader.fetch("https://original.example/first", lambda: True))["content"]
        == "done"
    )
    assert len(calls) == 2 and calls[0].url.host == calls[1].url.host == "93.184.216.34"
