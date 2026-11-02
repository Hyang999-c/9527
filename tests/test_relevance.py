from __future__ import annotations

from aspirin_agent.relevance import query_tokens, relevance_score
from aspirin_agent.schemas import Article


def test_query_tokens_strip_field_tags_and_stopwords() -> None:
    tokens = query_tokens(["aspirin[Title/Abstract] AND platelet inhibition"])

    assert "aspirin" in tokens
    assert "platelet" in tokens
    assert "and" not in tokens


def test_relevance_score_counts_query_coverage() -> None:
    article = Article(
        pmid="1",
        title="Aspirin platelet inhibition trial",
        abstract="Aspirin reduces platelet aggregation.",
    )

    assert relevance_score(article, ["aspirin platelet inhibition"]) == 1.0
    assert relevance_score(article, ["aspirin cancer"]) == 0.5


def test_non_ascii_query_does_not_filter() -> None:
    article = Article(pmid="1", title="Anything", abstract="anything")

    assert relevance_score(article, ["阿司匹林 机制"]) == 1.0
