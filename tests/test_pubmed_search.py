from __future__ import annotations

import httpx
import pytest

from aspirin_agent.errors import PubMedError, PubMedParseError
from aspirin_agent.parsers.pubmed_xml import parse_articles
from aspirin_agent.schemas import FullTextStatus, PublicationType
from aspirin_agent.tools.pubmed_search import PubMedSearcher, search_pubmed
from aspirin_agent.utils.rate_limit import RateLimiter

SAMPLE_XML = """<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>40000001</PMID>
      <Article>
        <ArticleTitle>Aspirin <i>versus</i> placebo</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">Aspirin is widely used.</AbstractText>
          <AbstractText Label="RESULTS">Aspirin reduced events.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author><LastName>Li</LastName><ForeName>Wei</ForeName></Author>
        </AuthorList>
        <Journal>
          <ISOAbbreviation>Lancet</ISOAbbreviation>
          <JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue>
        </Journal>
        <PublicationTypeList>
          <PublicationType>Randomized Controlled Trial</PublicationType>
        </PublicationTypeList>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">10.1000/xyz</ArticleId>
        <ArticleId IdType="pmc">PMC123</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""


def article_xml(pmid: str) -> str:
    return (
        "<PubmedArticleSet><PubmedArticle><MedlineCitation>"
        f"<PMID>{pmid}</PMID><Article><ArticleTitle>Title {pmid}</ArticleTitle>"
        f"<Abstract><AbstractText>Abstract {pmid}</AbstractText></Abstract>"
        "</Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"
    )


class NoopLimiter:
    def wait(self) -> float:
        return 0.0


def make_searcher(handler, *, search: dict | None = None, **kwargs) -> PubMedSearcher:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    config = {"max_results_per_query": 5, "retry_backoff_seconds": 0}
    config.update(search or {})
    return PubMedSearcher(
        {"search": config},
        client=client,
        limiter=NoopLimiter(),
        sleep=lambda _: None,
        **kwargs,
    )


def test_search_parses_records_and_passes_params() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["40000001"]}})
        return httpx.Response(200, text=SAMPLE_XML)

    searcher = make_searcher(handler)
    records = searcher.search("aspirin AND prevention")

    assert len(records) == 1
    assert captured["term"] == "aspirin AND prevention"
    assert captured["retmax"] == "5"
    assert captured["db"] == "pubmed"
    assert captured["tool"] == "aspirin-research-agent"

    record = records[0]
    assert record.title == "Aspirin versus placebo"
    assert record.doi == "10.1000/xyz"
    assert record.pmcid == "PMC123"
    assert record.year == 2020
    assert record.publication_type is PublicationType.RCT
    assert record.publication_types == ["Randomized Controlled Trial"]
    assert record.fulltext_status is FullTextStatus.ABSTRACT_ONLY
    assert record.authors == ["Li Wei"]
    assert "Aspirin reduced events." in record.abstract


def test_reference_ids_do_not_override_article_ids() -> None:
    xml = """<PubmedArticleSet><PubmedArticle>
      <MedlineCitation><PMID>12345</PMID><Article>
        <ArticleTitle>Own article</ArticleTitle>
        <ReferenceList><Reference><ArticleIdList>
          <ArticleId IdType="pmc">PMC_REFERENCE</ArticleId>
          <ArticleId IdType="doi">10.9999/reference</ArticleId>
        </ArticleIdList></Reference></ReferenceList>
      </Article></MedlineCitation>
      <PubmedData><ArticleIdList>
        <ArticleId IdType="doi">10.1000/own</ArticleId>
        <ArticleId IdType="pmc">PMC_OWN</ArticleId>
      </ArticleIdList></PubmedData>
    </PubmedArticle></PubmedArticleSet>"""

    article = parse_articles(xml)[0]

    assert article.pmcid == "PMC_OWN"
    assert article.doi == "10.1000/own"


def test_search_returns_empty_without_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"esearchresult": {"idlist": []}})

    assert make_searcher(handler).search("no hits") == []


def test_empty_query_rejected() -> None:
    with pytest.raises(ValueError):
        make_searcher(lambda request: httpx.Response(200)).esearch("   ")


def test_max_results_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        make_searcher(lambda request: httpx.Response(200)).esearch("aspirin", retmax=0)


def test_malformed_xml_raises_parse_error() -> None:
    with pytest.raises(PubMedParseError):
        parse_articles("<PubmedArticleSet><broken>")


def test_search_wraps_parse_error_as_pubmed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["1"]}})
        return httpx.Response(200, text="<broken>")

    with pytest.raises(PubMedError):
        make_searcher(handler).search("aspirin")


def test_retry_on_503_then_success() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"esearchresult": {"idlist": ["40000001"]}})

    pmids = make_searcher(handler, search={"retry_attempts": 3}).esearch("aspirin")

    assert pmids == ["40000001"]
    assert calls["count"] == 2


def test_no_retry_on_client_error() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(404, text="not found")

    with pytest.raises(PubMedError):
        make_searcher(handler, search={"retry_attempts": 3}).esearch("aspirin")
    assert calls["count"] == 1


def test_gives_up_after_retries() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(500, text="boom")

    with pytest.raises(PubMedError):
        make_searcher(handler, search={"retry_attempts": 3}).esearch("aspirin")
    assert calls["count"] == 3


def test_efetch_is_chunked_and_deduplicated() -> None:
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["1", "2", "2"]}})
        fetched.append(request.url.params["id"])
        return httpx.Response(200, text=article_xml(request.url.params["id"]))

    records = make_searcher(handler, search={"efetch_batch_size": 1}).search("aspirin")

    assert fetched == ["1", "2"]
    assert [record.pmid for record in records] == ["1", "2"]


def test_efetch_rejects_non_numeric_pmid() -> None:
    with pytest.raises(ValueError):
        make_searcher(lambda request: httpx.Response(200)).efetch(["abc"])


def test_raw_payloads_are_saved(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["40000001"]}})
        return httpx.Response(200, text=SAMPLE_XML)

    make_searcher(handler, raw_dir=tmp_path).search("aspirin")

    assert list(tmp_path.glob("pubmed_esearch_*.json"))
    assert list(tmp_path.glob("pubmed_efetch_*.xml"))


def test_rate_limiter_enforces_interval() -> None:
    class FakeClock:
        def __init__(self) -> None:
            self.now = 0.0
            self.sleeps: list[float] = []

        def monotonic(self) -> float:
            return self.now

        def sleep(self, seconds: float) -> None:
            self.sleeps.append(seconds)
            self.now += seconds

    clock = FakeClock()
    limiter = RateLimiter(4, clock=clock.monotonic, sleep=clock.sleep)

    assert limiter.wait() == 0.0
    assert limiter.wait() == pytest.approx(0.25)
    assert clock.sleeps == [pytest.approx(0.25)]


def test_search_pubmed_tool_wrapper() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["1"]}})
        return httpx.Response(200, text=article_xml("1"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    records = search_pubmed("aspirin", max_results=3, client=client)

    assert len(records) == 1
    assert records[0].pmid == "1"


def test_elink_related_excludes_seeds_and_limits() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("elink.fcgi")
        return httpx.Response(
            200,
            json={
                "linksets": [
                    {
                        "ids": ["1"],
                        "linksetdbs": [
                            {"linkname": "pubmed_pubmed", "dbto": "pubmed", "links": ["1", "2", "3"]}
                        ],
                    }
                ]
            },
        )

    searcher = make_searcher(handler)
    assert searcher.elink_related(["1"]) == ["2", "3"]
    assert searcher.elink_related(["1"], max_results=1) == ["2"]


def test_elink_filters_by_linkname() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["linkname"] == "pubmed_pubmed_refs"
        return httpx.Response(
            200,
            json={
                "linksets": [
                    {
                        "ids": ["1"],
                        "linksetdbs": [
                            {"linkname": "pubmed_pubmed_refs", "dbto": "pubmed", "links": ["10", "11"]},
                            {"linkname": "pubmed_pubmed", "dbto": "pubmed", "links": ["12"]},
                        ],
                    }
                ]
            },
        )

    searcher = make_searcher(handler)
    assert searcher.elink(["1"], "pubmed_pubmed_refs") == ["10", "11"]


def test_esearch_paginates_with_retstart() -> None:
    starts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params.get("retstart", "0"))
        starts.append(start)
        if start == 0:
            return httpx.Response(200, json={"esearchresult": {"idlist": ["1", "2"]}})
        return httpx.Response(200, json={"esearchresult": {"idlist": ["3"]}})

    searcher = make_searcher(handler, search={"page_size": 2})
    ids = searcher.esearch_all("aspirin", 3)

    assert ids == ["1", "2", "3"]
    assert starts == [0, 2]
