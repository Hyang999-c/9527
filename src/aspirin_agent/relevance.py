"""扩展文献的轻量相关性打分：查询词在标题/摘要中的覆盖率。"""

from __future__ import annotations

import re

from .schemas import Article

STOPWORDS = {
    "and", "or", "not", "the", "with", "for", "from", "into", "that", "this",
    "these", "those", "are", "was", "were", "has", "have", "had", "its", "their",
    "after", "before", "during", "among", "between", "versus", "vs",
}

FIELD_TAG = re.compile(r"\[[^\]]*\]")
TOKEN = re.compile(r"[a-z][a-z0-9-]{2,}")


def query_tokens(terms: list[str]) -> set[str]:
    text = FIELD_TAG.sub(" ", " ".join(terms)).lower()
    return {word for word in TOKEN.findall(text) if word not in STOPWORDS}


def relevance_score(article: Article, terms: list[str]) -> float:
    """查询词覆盖率；查询里没有可用的英文词时返回 1.0（不过滤）。"""
    wanted = query_tokens(terms)
    if not wanted:
        return 1.0
    text = f"{article.title} {article.abstract}".lower()
    found = wanted & set(TOKEN.findall(text))
    return len(found) / len(wanted)
