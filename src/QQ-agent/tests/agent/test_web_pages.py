import asyncio

import httpx
import pytest
from qqbot.agent.web import WebClient, parse_bing, sanitize_query, search_results
from qqbot.agent.web_pages import read_page


def page(html):
    return {"url": "https://example.com/article", "type": "text/html", "text": html}


def test_results_do_not_borrow_next_result_snippet_or_script_text():
    html = """<li class=b_algo><h2><a href="https://example.com/one">Python one</a></h2></li>
        <li class=b_algo><h2><a href="https://example.com/two">Python two</a></h2><p>second only</p><script>fake</script></li>"""
    results = search_results("bing", html, 6)
    assert [r["snippet"] for r in results] == ["", "second only"]


def test_omitted_li_end_tags_and_malformed_links_do_not_drop_valid_results():
    html = """<li class=b_algo><h2><a href="https://[broken/">Broken</a></h2>
        <li class=b_algo><h2><a href="https://example.com/one">Python one</a></h2><p>one</p>
        <li class=b_algo><h2><a href="https://example.com/two">Python two</a></h2><p>two</p>"""
    assert [r["snippet"] for r in parse_bing(html, 6)] == ["one", "two"]


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


@pytest.mark.parametrize(
    "engine,tag,classes,heading", [("bing", "li", "b_algo", "h2"), ("baidu", "div", "result", "h3")]
)
def test_search_ignores_hidden_results_ancestors_and_inline_summary_text(
    engine, tag, classes, heading
):
    def result(path, extra="", summary="Python documentation"):
        return f'<{tag} class="{classes}" {extra}><{heading}><a href="https://example.com/{path}">Python {path}</a></{heading}><p>{summary}</p></{tag}>'

    html = (
        "<div hidden>"
        + result("hidden-parent")
        + "</div>"
        + result("hidden-result", 'aria-hidden="true"')
    )
    html += result(
        "visible",
        summary='Python documentation<span style="display:none">invisible injection</span>',
    )
    results = search_results(engine, html, 6)
    assert [item["url"] for item in results] == ["https://example.com/visible"]
    assert results[0]["snippet"] == "Python documentation"


def test_bare_html_attributes_do_not_crash_page_or_search_parsing():
    assert (
        read_page(page("<article style><p>Readable text</p></article>"), 12000)["content"]
        == "Readable text"
    )
    html = '<li class><h2>ignored</h2></li><li class=b_algo style><h2><a href="https://example.com/">Python</a></h2></li>'
    assert search_results("bing", html, 6)[0]["title"] == "Python"


def test_search_layout_visibility_does_not_hide_descendant_results_or_drop_a_deferred_layout():
    html = '<div style="visibility:hidden"><li class=b_algo><h2 style="visibility:visible"><a href="https://example.com/">Python</a></h2><p>Python documentation</p></li></div>'
    assert search_results("bing", html, 6)[0]["snippet"] == "Python documentation"


def test_search_still_excludes_explicitly_invisible_text_inside_each_result():
    html = '<li class=b_algo><h2><a href="https://example.com/">Python</a></h2><p>Python documentation<span style="visibility:hidden">invisible words</span></p></li>'
    assert search_results("bing", html, 6)[0]["snippet"] == "Python documentation"
