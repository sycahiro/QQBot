import gzip
import zlib

import httpx
import pytest
from qqbot.desktop.bridge import DesktopBridge
from qqbot.desktop.paths import DesktopPaths
from qqbot.extensions.market import MARKET_API, MARKET_PAGES, MarketCatalog


def test_market_is_get_only_fixed_destination_bounded_metadata_and_cached():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and str(request.url) == MARKET_API + "/plugins"
        assert "authorization" not in request.headers and not request.content
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "legacy",
                        "name": "旧扩展",
                        "description": "说明",
                        "downloadUrl": "https://untrusted.test/run.js",
                        "installCode": "NEVER-USE",
                    }
                ]
            },
        )

    client = MarketCatalog(transport=httpx.MockTransport(handler))
    result = client.read("plugin")
    assert result["readOnly"] is True and result["compatible"] is False
    assert "downloadUrl" not in result["items"][0] and "installCode" not in result["items"][0]
    assert client.read("plugin") == result and len(calls) == 1
    with pytest.raises(ValueError):
        client.read("../other")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403, text="sensitive server body"),
        httpx.Response(200, json={"items": [{"id": 12}]}),
        httpx.Response(200, text="not-json"),
    ],
)
def test_market_failure_does_not_expose_response_body(response):
    client = MarketCatalog(transport=httpx.MockTransport(lambda request: response))
    with pytest.raises(ValueError) as error:
        client.read("plugin")
    assert "sensitive server body" not in str(error.value)


@pytest.mark.parametrize("encoding,compress", [("gzip", gzip.compress), ("deflate", zlib.compress)])
def test_compressed_market_stream_is_bounded_before_expansion_and_normal_data_still_loads(
    encoding, compress, monkeypatch
):
    def forbid_unbounded(*args, **kwargs):
        raise AssertionError("Do not use the unbounded HTTP decoder")

    monkeypatch.setattr(httpx.Response, "iter_bytes", forbid_unbounded)

    def reader(payload):
        return MarketCatalog(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    headers={"content-encoding": encoding},
                    stream=httpx.ByteStream(compress(payload)),
                )
            )
        )

    assert reader(b'{"items":[]}').read("plugin")["items"] == []
    with pytest.raises(ValueError, match="限制"):
        reader(b"x" * (3 * 1024 * 1024)).read("plugin")


def test_open_market_page_only_reaches_whitelisted_official_pages(tmp_path, monkeypatch):
    bridge = DesktopBridge(DesktopPaths(tmp_path, tmp_path / "runtime"), lambda **_: None)
    opened = []

    def fake_open(url, new=0):
        opened.append((url, new))
        return True

    monkeypatch.setattr("webbrowser.open", fake_open)
    assert bridge.open_market_page("plugin") == {"ok": True, "url": MARKET_PAGES["plugin"]}
    assert bridge.open_market_page("skill")["url"] == MARKET_PAGES["skill"]
    assert opened == [(MARKET_PAGES["plugin"], 2), (MARKET_PAGES["skill"], 2)]

    # 前端只能选类型，不能传任意地址；未知类型直接拒绝且不打开浏览器。
    for kind in ("../evil", "https://untrusted.test/", None, 3):
        assert bridge.open_market_page(kind)["error"]["code"] == "INVALID_INPUT"
    assert len(opened) == 2

    monkeypatch.setattr("webbrowser.open", lambda *a, **k: False)
    failed = bridge.open_market_page("plugin")
    assert failed["ok"] is False and "浏览器" in failed["error"]["message"]
