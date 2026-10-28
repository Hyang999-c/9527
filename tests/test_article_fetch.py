from __future__ import annotations

import httpx

from aspirin_agent.schemas import Article, FullTextStatus
from aspirin_agent.tools.article_fetch import fetch_articles, fetch_fulltext
from aspirin_agent.tools.pubmed_search import PubMedSearcher

PMC_XML = """<article>
  <front><abstract><p>Background text.</p></abstract></front>
  <body>
    <sec><title>Results</title><p>Aspirin reduced major events.</p></sec>
  </body>
</article>"""

PUBMED_XML = """<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>7</PMID>
      <Article>
        <ArticleTitle>Fetched by PMID</ArticleTitle>
        <Abstract><AbstractText>Aspirin and platelets.</AbstractText></Abstract>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>"""


def test_fetch_fulltext_marks_available() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["db"] == "pmc"
        assert request.url.params["id"] == "PMC123"
        return httpx.Response(200, text=PMC_XML)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    article = Article(pmid="1", title="t", pmcid="PMC123")
    updated = fetch_fulltext(article, client=client)

    assert "Results" in (updated.fulltext or "")
    assert "reduced major events" in (updated.fulltext or "")
    assert updated.fulltext_status is FullTextStatus.FULLTEXT_AVAILABLE
    assert updated.pmid == "1"


def test_skip_without_pmcid() -> None:
    article = Article(pmid="2", title="t")
    assert fetch_fulltext(article) is article


def test_http_error_marks_unavailable_and_keeps_abstract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    article = Article(pmid="3", title="t", pmcid="PMC9", abstract="keep me")
    updated = fetch_fulltext(article, client=client)

    assert updated.fulltext is None
    assert updated.fulltext_status is FullTextStatus.FULLTEXT_UNAVAILABLE
    assert updated.abstract == "keep me"


def test_fetch_articles_by_pmid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["db"] == "pubmed"
        assert request.url.params["id"] == "7"
        return httpx.Response(200, text=PUBMED_XML)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    articles = fetch_articles(["7"], client=client)

    assert len(articles) == 1
    assert articles[0].pmid == "7"
    assert articles[0].title == "Fetched by PMID"


def test_fetch_articles_empty_list() -> None:
    assert fetch_articles([]) == []


class _NoopLimiter:
    def wait(self) -> float:
        return 0.0


def test_fetch_fulltext_via_searcher_saves_raw(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["db"] == "pmc"
        return httpx.Response(200, text=PMC_XML)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    searcher = PubMedSearcher(
        {"search": {"efetch_batch_size": 5, "retry_backoff_seconds": 0}},
        client=client,
        limiter=_NoopLimiter(),
        raw_dir=tmp_path,
        sleep=lambda _: None,
    )
    updated = fetch_fulltext(
        Article(pmid="4", title="t", pmcid="PMC5"), searcher=searcher
    )

    assert updated.fulltext_status is FullTextStatus.FULLTEXT_AVAILABLE
    assert "reduced major events" in (updated.fulltext or "")
    assert list(tmp_path.glob("pmc_efetch_*.xml"))
