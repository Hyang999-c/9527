"""真实网络冒烟测试，默认跳过；需要时设置 RUN_LIVE_TESTS=1。"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="需要真实网络，设置 RUN_LIVE_TESTS=1 才执行",
)


def test_live_pubmed_search() -> None:
    from aspirin_agent.tools.pubmed_search import search_pubmed

    articles = search_pubmed("aspirin platelet inhibition", max_results=3)

    assert articles
    assert all(article.pmid.isdigit() for article in articles)
    assert all(article.title for article in articles)
