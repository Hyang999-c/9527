from __future__ import annotations

from aspirin_agent.schemas import Article
from aspirin_agent.tools.deduplication import deduplicate_records


def test_same_pmid_removed() -> None:
    first = Article(pmid="1", title="Aspirin trial")
    duplicate = Article(pmid="1", title="Another title")

    assert deduplicate_records([first, duplicate]) == [first]


def test_same_doi_removed() -> None:
    first = Article(pmid="1", title="A", doi="10.1/abc")
    duplicate = Article(pmid="2", title="B", doi="10.1/ABC")

    assert deduplicate_records([first, duplicate]) == [first]


def test_similar_title_removed() -> None:
    first = Article(pmid="1", title="Aspirin for secondary prevention of cardiovascular events")
    similar = Article(
        pmid="2",
        title="Aspirin for secondary prevention of cardiovascular event",
    )

    assert deduplicate_records([first, similar]) == [first]


def test_distinct_records_kept_in_order() -> None:
    first = Article(pmid="1", title="Aspirin and platelets")
    second = Article(pmid="2", title="Clopidogrel after stenting")

    assert deduplicate_records([first, second]) == [first, second]
