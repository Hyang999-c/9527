"""引用核查：标识符、标题、来源可访问性、引句可定位性。

claim_supported 表示引句能在原文中逐字定位；语义层面的“是否真的支持结论”
由可选 judge 提供，未提供时不额外拔高结论。
"""

from __future__ import annotations

import re
from collections.abc import Callable

import httpx

from ..schemas import (
    Article,
    Evidence,
    FullTextStatus,
    Verification,
    VerificationStatus,
)

Resolver = Callable[[str | None, str | None], bool]
Judge = Callable[[Evidence, Article], bool]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def quote_supported(quote: str | None, source: str) -> bool | None:
    """quote 为空时返回 None（未提供，不做判定）。"""
    if not quote:
        return None
    return normalize(quote) in normalize(source)


class PubMedResolver:
    """在线校验：有 PMID 查 esummary，只有 DOI 查 Crossref。"""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=20)

    def __call__(self, pmid: str | None, doi: str | None) -> bool:
        try:
            if pmid:
                response = self._client.get(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                    params={"db": "pubmed", "id": pmid, "retmode": "json"},
                )
                response.raise_for_status()
                return bool(response.json().get("result", {}).get(pmid))
            if doi:
                response = self._client.get(
                    f"https://api.crossref.org/works/{doi}", timeout=15
                )
                return response.status_code == 200
        except httpx.HTTPError:
            return False
        return False


def _final_status(
    *,
    article: Article | None,
    identifier_check: bool | None,
    title_check: bool | None,
    source_accessible: bool | None,
    claim_supported: bool | None,
    item: Evidence,
    issues: list[str],
) -> VerificationStatus:
    if (
        article is None
        or identifier_check is False
        or title_check is False
        or claim_supported is False
    ):
        return VerificationStatus.FAILED
    if claim_supported is None:
        return VerificationStatus.NOT_VERIFIABLE
    full_checks = all(
        check is True
        for check in (identifier_check, title_check, source_accessible, claim_supported)
    )
    if (
        full_checks
        and item.source_location.is_locatable
        and article.fulltext_status is FullTextStatus.FULLTEXT_AVAILABLE
        and not issues
    ):
        return VerificationStatus.PASSED
    return VerificationStatus.PARTIAL


def verify_citations(
    evidence: list[Evidence],
    articles: list[Article],
    resolver: Resolver | None = None,
    judge: Judge | None = None,
) -> list[Verification]:
    """逐条核查并回写 evidence.verification_status；返回 Verification 列表。"""
    index = {article.pmid: article for article in articles}
    results: list[Verification] = []

    for item in evidence:
        article = index.get(item.pmid)
        issues: list[str] = []
        identifier_check: bool | None = None
        title_check: bool | None = None
        source_accessible: bool | None = None
        claim_supported: bool | None = None

        if article is None:
            issues.append("文献不在本次检索集中")
        else:
            identifier_check = article.pmid == item.pmid
            if not identifier_check:
                issues.append("PMID 与检索记录不一致")

            if item.source_title:
                title_check = normalize(item.source_title) == normalize(article.title)
                if not title_check:
                    issues.append("证据记录的标题与文献标题不一致")
            else:
                issues.append("缺少抽取时记录的标题，无法核对")

            corpus = "\n".join(
                part for part in (article.abstract, article.fulltext or "") if part
            )
            source_accessible = bool(corpus.strip())
            if not source_accessible:
                issues.append("无可访问的摘要或全文")

            quote_state = quote_supported(item.source_location.quote, corpus)
            if quote_state is False:
                issues.append("引句未能在原文中定位")
            elif quote_state is None:
                issues.append("未提供可核查的原文引句")
            if item.source_location.locator == "none":
                issues.append("来源位置未标注")

            if quote_state is True and judge is not None:
                claim_supported = judge(item, article)
                if not claim_supported:
                    issues.append("引句存在但不足以支持主张")
            else:
                claim_supported = quote_state

            if (
                resolver is not None
                and identifier_check
                and not resolver(item.pmid, item.doi)
            ):
                identifier_check = False
                issues.append("标识符在线校验失败")

        status = _final_status(
            article=article,
            identifier_check=identifier_check,
            title_check=title_check,
            source_accessible=source_accessible,
            claim_supported=claim_supported,
            item=item,
            issues=issues,
        )
        if (
            status is VerificationStatus.PARTIAL
            and article is not None
            and article.fulltext_status is not FullTextStatus.FULLTEXT_AVAILABLE
        ):
            issues.append("证据仅来自摘要或全文缺失，未完成全文核查")
        item.verification_status = status
        results.append(
            Verification(
                evidence_id=item.evidence_id,
                identifier_check=identifier_check,
                title_check=title_check,
                source_accessible=source_accessible,
                claim_supported=claim_supported,
                issues=issues,
                final_status=status,
            )
        )
    return results
