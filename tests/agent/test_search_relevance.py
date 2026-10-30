import asyncio

import httpx
import pytest

from QQBot.agent.web import DEFAULT_SEARCH, WebClient, search_results


@pytest.mark.parametrize("engine", ["bing", "baidu"])
def test_results_are_not_filtered_reordered_or_rejected_by_keyword_matching(engine):
    def block(name):
        return (
            f'<li class="b_algo"><h2><a href="https://example.com/{name.replace(" ", "-")}">{name}</a></h2><p>正文</p></li>'
            if engine == "bing"
            else f'<div class="result"><h3><a href="https://example.com/{name.replace(" ", "-")}">{name}</a></h3><p>正文</p></div>'
        )

    html = '<input name="q" value="更正后的词">' + block("2026年放假安排") + block("Python 官网")
    assert [i["title"] for i in search_results(engine, html, 6)] == [
        "2026年放假安排",
        "Python 官网",
    ]
    assert len(search_results(engine, html, 1)) == 1


def test_full_query_is_submitted_and_normal_results_stop_fallback_even_if_engine_rewrites_query():
    calls = []

    class Browser:
        async def render(self, engine, url, permit):
            calls.append(httpx.URL(url).params["q"])
            return {
                "url": "https://cn.bing.com/search?q=corrected",
                "text": '<li class=b_algo><h2><a href="https://example.com/">2026年日历</a></h2></li>',
            }

    result = asyncio.run(
        WebClient(browser=Browser()).search(
            DEFAULT_SEARCH, "2026年英雄联盟世界赛瑞士轮", lambda: True
        )
    )
    assert result["engine"] == "bing" and calls == ["2026年英雄联盟世界赛瑞士轮"]
