import asyncio

import httpx
import pytest

from QQBot.agent.web import WebClient, sanitize_query
from QQBot.agent.web_pages import read_page


def page(html):
    return {"url": "https://example.com/article", "type": "text/html", "text": html}


def test_article_prefers_main_content_and_excludes_hidden_menus_and_scripts():
    body = "实际正文。" * 40
    result = read_page(
        page(
            f"<title>文章</title><div>站点导航广告</div><main><h1>标题</h1><p>{body}</p><p hidden>秘密</p><script>fake</script></main><footer>备案信息</footer>"
        ),
        12000,
    )
    assert result["content"] == "标题\n" + body
    assert result["title"] == "文章" and not result["truncated"]


@pytest.mark.parametrize(
    "html",
    [
        "<title>安全验证</title><p>请完成验证</p>",
        "<title>Just a moment...</title><main>Enable JavaScript</main>",
        '<form id="captcha"><p>Verify your browser</p></form>',
        "<title>登录 - Example</title><p>请登录</p>",
        '<html><div id="app"></div><script>render()</script></html>',
    ],
)
def test_challenges_login_and_script_shells_are_not_returned_as_articles(html):
    with pytest.raises(ValueError):
        read_page(page(html), 12000)


def test_article_discussing_captcha_is_still_readable():
    text = "This article explains CAPTCHA and its history. " * 30
    assert (
        text.strip()
        in read_page(page("<title>CAPTCHA history</title><article>" + text + "</article>"), 12000)[
            "content"
        ]
    )


def test_meta_declared_chinese_encoding_is_decoded_before_extraction():
    async def resolver(host):
        return "93.184.216.34"

    html = '<meta charset="gb2312"><title>新闻</title><p>简体中文内容</p>'
    client = WebClient(
        resolver=resolver,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-type": "text/html"}, content=html.encode("gb18030")
            )
        ),
    )
    result = asyncio.run(client.fetch("https://example.com/", lambda: True))
    assert result["content"] == "简体中文内容" and result["title"] == "新闻"


def test_long_query_is_rejected_instead_of_silently_searching_a_different_query():
    with pytest.raises(ValueError, match="120"):
        sanitize_query("a" * 121)


def test_excessive_nesting_is_rejected_before_building_unbounded_article_candidates():
    html = "<article>" * 300 + "text" + "</article>" * 300
    with pytest.raises(ValueError, match="复杂"):
        read_page(page(html), 12000)


def test_bare_html_attributes_do_not_crash_page_parsing():
    assert (
        read_page(page("<article style><p>Readable text</p></article>"), 12000)["content"]
        == "Readable text"
    )
