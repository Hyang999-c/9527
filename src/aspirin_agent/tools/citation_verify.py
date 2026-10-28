"""引用核查：标识符、标题、来源可访问性、引句可定位性，以及可选的语义判定。

默认全部离线：
- resolver 不传，就不做 NCBI/Crossref 在线校验
- judge 不传，claim_supported 只表示“引句能在原文中逐字定位”
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path

import httpx

from ..schemas import (
    Article,
    Evidence,
    FullTextStatus,
    Verification,
    VerificationStatus,
)
from ..utils.logging_utils import get_logger

logger = get_logger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
CROSSREF_URL = "https://api.crossref.org/works/"
USER_AGENT = "aspirin-research-agent/0.1 (research use)"

Resolver = Callable[[str | None, str | None], bool | None]
Judge = Callable[[Evidence, Article], bool | None]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def quote_supported(quote: str | None, source: str) -> bool | None:
    """quote 为空时返回 None（未提供，不做判定）。"""
    if not quote:
        return None
    return normalize(quote) in normalize(source)


class PubMedResolver:
    """在线校验：有 PMID 查 esummary，只有 DOI 查 Crossref。

    返回 True/False/None：
    - True：标识符存在
    - False：明确不存在
    - None：网络或服务异常，不能据此判定文献无效
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        limiter=None,
        timeout: float = 20.0,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=timeout, headers={"User-Agent": USER_AGENT}
        )
        self.limiter = limiter
        self.email = os.getenv("NCBI_EMAIL")

    def __call__(self, pmid: str | None, doi: str | None) -> bool | None:
        try:
            if pmid:
                if self.limiter is not None:
                    self.limiter.wait()
                params = {
                    "db": "pubmed",
                    "id": pmid,
                    "retmode": "json",
                    "tool": "aspirin-research-agent",
                }
                if self.email:
                    params["email"] = self.email
                response = self._client.get(ESUMMARY_URL, params=params)
                if response.status_code == 404:
                    return False
                response.raise_for_status()
                result = response.json().get("result", {})
                return bool(result.get(pmid))
            if doi:
                if self.limiter is not None:
                    self.limiter.wait()
                response = self._client.get(CROSSREF_URL + doi, timeout=15)
                if response.status_code == 404:
                    return False
                response.raise_for_status()
                return True
        except httpx.HTTPError as exc:
            logger.warning("在线校验失败（%s / %s）: %s", pmid, doi, exc)
            return None
        return False


def _parse_json_object(raw: str) -> dict:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


class LLMJudge:
    """让模型判断引句是否真的支持主张；只输出 supported 布尔值。"""

    def __init__(
        self,
        llm,
        prompt_name: str = "verify_evidence.md",
        max_tokens: int = 300,
        source_chars: int = 6000,
    ) -> None:
        prompt_path = PROMPTS_DIR / prompt_name
        if not prompt_path.exists():
            raise FileNotFoundError(f"提示词不存在: {prompt_path}")
        self.llm = llm
        self.template = prompt_path.read_text(encoding="utf-8")
        self.max_tokens = max_tokens
        self.source_chars = source_chars

    def __call__(self, item: Evidence, article: Article) -> bool | None:
        source = f"{article.abstract}\n{article.fulltext or ''}".strip()[: self.source_chars]
        prompt = (
            self.template.replace("{{CLAIM}}", item.claim)
            .replace("{{QUOTE}}", item.source_location.quote or "")
            .replace("{{SOURCE}}", source)
        )
        raw = self.llm.complete(
            [
                {"role": "system", "content": "你是严格的引文核查员，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=self.max_tokens,
            json_mode=True,
        )
        supported = _parse_json_object(raw).get("supported")
        return supported if isinstance(supported, bool) else None


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
                try:
                    verdict = judge(item, article)
                except Exception as exc:  # noqa: BLE001 - 语义判定失败不应拖垮整批
                    logger.warning("语义判定失败 %s: %s", item.evidence_id, exc)
                    verdict = None
                if verdict is None:
                    issues.append("语义判定未能完成")
                else:
                    claim_supported = verdict
                    if not verdict:
                        issues.append("引句存在但不足以支持主张")
            else:
                claim_supported = quote_state

            if resolver is not None and identifier_check:
                online = resolver(item.pmid, item.doi)
                if online is False:
                    identifier_check = False
                    issues.append("标识符在线校验失败")
                elif online is None:
                    issues.append("在线校验不可用（网络或服务错误）")

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
