"""全文补全：有 PMCID 就抓 PMC OA XML，失败保留摘要并标记状态。"""

from __future__ import annotations

import httpx

from ..errors import PubMedError
from ..parsers.fulltext import parse_pmc_permissions, parse_pmc_xml
from ..schemas import Article, FullTextStatus
from ..utils.logging_utils import get_logger
from ..utils.retry import http_retry
from .pubmed_search import PubMedSearcher

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
USER_AGENT = "aspirin-research-agent/0.1 (research use)"
MAX_FULLTEXT_CHARS = 20000


@http_retry()
def _get(client: httpx.Client, url: str, params: dict[str, object]) -> httpx.Response:
    response = client.get(url, params=params)
    response.raise_for_status()
    return response


def _pmc_xml(
    pmcid: str,
    *,
    client: httpx.Client | None,
    base_url: str,
    searcher: PubMedSearcher | None,
) -> str:
    """优先走 searcher（共享限速器、重试与原始响应落盘），否则用独立 client。"""
    if searcher is not None:
        return searcher.fetch_pmc_xml(pmcid)

    owned = client is None
    client = client or httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT})
    try:
        response = _get(
            client,
            f"{base_url.rstrip('/')}/efetch.fcgi",
            {"db": "pmc", "id": pmcid, "retmode": "xml"},
        )
        return response.text
    finally:
        if owned:
            client.close()


def fetch_fulltext(
    article: Article,
    client: httpx.Client | None = None,
    base_url: str = DEFAULT_BASE_URL,
    searcher: PubMedSearcher | None = None,
) -> Article:
    """返回补全 fulltext 的新对象；无 PMCID 或抓取失败时保留原状态。"""
    if not article.pmcid:
        return article

    try:
        xml_text = _pmc_xml(
            article.pmcid, client=client, base_url=base_url, searcher=searcher
        )
        sections = parse_pmc_xml(xml_text)
        text = "\n\n".join(f"## {name}\n{body}" for name, body in sections.items() if body)
        if not text:
            logger.info("PMC%s 无可用正文", article.pmcid)
            return article.model_copy(
                update={"fulltext_status": FullTextStatus.FULLTEXT_UNAVAILABLE}
            )
        permissions = parse_pmc_permissions(xml_text)
        return article.model_copy(
            update={
                "fulltext": text[:MAX_FULLTEXT_CHARS],
                "fulltext_status": FullTextStatus.FULLTEXT_AVAILABLE,
                **permissions,
            }
        )
    except (httpx.HTTPError, PubMedError) as exc:
        logger.warning("全文获取失败 PMC%s: %s", article.pmcid, exc)
        return article.model_copy(
            update={"fulltext_status": FullTextStatus.FULLTEXT_UNAVAILABLE}
        )


def fetch_articles(
    pmids: list[str],
    client: httpx.Client | None = None,
    base_url: str = DEFAULT_BASE_URL,
    settings: dict | None = None,
) -> list[Article]:
    """工具入口：按 PMID 列表取回 Article；空列表直接返回空。"""
    if not pmids:
        return []
    config = settings or {"search": {"base_url": base_url}}
    owned = client is None
    searcher = PubMedSearcher(config, client=client)
    try:
        return searcher.fetch_by_pmids(pmids)
    finally:
        if owned:
            searcher.close()


def enrich_articles(
    articles: list[Article],
    client: httpx.Client | None = None,
    limit: int | None = None,
    searcher: PubMedSearcher | None = None,
) -> list[Article]:
    """批量补全全文；limit 控制最多抓几篇，避免频繁请求 NCBI。"""
    budget = len(articles) if limit is None else max(0, limit)
    enriched: list[Article] = []
    for article in articles:
        if budget > 0 and article.pmcid:
            enriched.append(fetch_fulltext(article, client=client, searcher=searcher))
            budget -= 1
        else:
            enriched.append(article)
    return enriched
