"""PubMed E-utilities 客户端：限速、超时、有限重试、原始响应落盘。"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ..errors import PubMedError, PubMedParseError
from ..parsers.pubmed_xml import parse_articles
from ..schemas import Article
from ..utils.logging_utils import get_logger
from ..utils.rate_limit import RateLimiter

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
USER_AGENT = "aspirin-research-agent/0.1 (research use)"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _auto_rate(api_key: str | None) -> float:
    """NCBI 规定：无 key 每秒最多 3 次，有 key 最多 10 次。"""
    return 10.0 if api_key else 3.0


class PubMedSearcher:
    """一次检索 = ESearch + EFetch；client、限速器、sleep 均可注入。"""

    def __init__(
        self,
        settings: dict | None = None,
        client: httpx.Client | None = None,
        limiter: RateLimiter | None = None,
        raw_dir: str | Path | None = None,
        sleep=time.sleep,
    ) -> None:
        config = (settings or {}).get("search", {})
        self.base_url = str(config.get("base_url", DEFAULT_BASE_URL)).rstrip("/")
        self.max_results = int(config.get("max_results_per_query", 20))
        self.email = os.getenv("NCBI_EMAIL") or config.get("email")
        self.api_key = os.getenv("NCBI_API_KEY")
        self.timeout = float(config.get("timeout_seconds", 30))
        self.retries = max(1, int(config.get("retry_attempts", 3)))
        self.backoff = max(0.0, float(config.get("retry_backoff_seconds", 1.0)))
        self.batch_size = max(1, int(config.get("efetch_batch_size", 200)))
        rate = config.get("rate_limit_per_second")
        rate_value = _auto_rate(self.api_key) if rate in (None, 0) else float(rate)
        self.limiter = limiter or RateLimiter(rate_value)
        self.raw_dir = Path(raw_dir) if raw_dir else None
        self._sleep = sleep
        self._client = client or httpx.Client(
            timeout=self.timeout, headers={"User-Agent": USER_AGENT}
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PubMedSearcher:  # noqa: PYI034 - 3.10 兼容，不用 Self
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def common_params(self) -> dict[str, str]:
        params = {"tool": "aspirin-research-agent"}
        if self.email:
            params["email"] = str(self.email)
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def _save_raw(self, stem: str, text: str, suffix: str) -> None:
        if self.raw_dir is None:
            return
        try:
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            (self.raw_dir / f"{stem}_{stamp}.{suffix}").write_text(text, encoding="utf-8")
        except OSError as exc:
            logger.warning("原始响应保存失败: %s", exc)

    def _get(self, endpoint: str, params: dict[str, object]) -> httpx.Response:
        """带限速与指数退避的 GET；4xx（429 除外）不重试，直接报错。"""
        url = f"{self.base_url}/{endpoint}"
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self.limiter.wait()
            try:
                response = self._client.get(url, params=params)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status not in RETRYABLE_STATUS:
                    raise PubMedError(f"{endpoint} 返回 HTTP {status}") from exc
                last_error = exc
            except httpx.TransportError as exc:
                last_error = exc

            if attempt < self.retries:
                delay = min(self.backoff * (2 ** (attempt - 1)), 10.0)
                logger.warning(
                    "%s 第 %d 次失败，%.1fs 后重试：%s", endpoint, attempt, delay, last_error
                )
                self._sleep(delay)

        raise PubMedError(
            f"{endpoint} 请求失败（已重试 {self.retries} 次）: {last_error}"
        ) from last_error

    def esearch(self, term: str, retmax: int | None = None) -> list[str]:
        if not term.strip():
            raise ValueError("检索式不能为空")
        limit = self.max_results if retmax is None else retmax
        if not 1 <= limit <= 10000:
            raise ValueError("max_results 需在 1-10000 之间")

        params = {
            **self.common_params(),
            "db": "pubmed",
            "term": term,
            "retmode": "json",
            "retmax": limit,
            "sort": "relevance",
        }
        response = self._get("esearch.fcgi", params)
        self._save_raw("pubmed_esearch", response.text, "json")

        try:
            payload = response.json()
        except ValueError as exc:
            raise PubMedError("ESearch 返回的不是合法 JSON") from exc
        result = payload.get("esearchresult")
        if not isinstance(result, dict):
            raise PubMedError("ESearch 响应缺少 esearchresult")
        if result.get("ERROR"):
            raise PubMedError(f"ESearch 返回错误: {result['ERROR']}")
        return [str(pmid) for pmid in result.get("idlist", [])]

    def efetch(self, pmids: list[str]) -> str:
        if not pmids:
            return ""
        invalid = [pmid for pmid in pmids if not str(pmid).isdigit()]
        if invalid:
            raise ValueError(f"PMID 必须是纯数字: {invalid[:3]}")
        if len(pmids) > self.batch_size:
            raise ValueError(f"单次 EFetch 最多 {self.batch_size} 条，收到 {len(pmids)}")

        params = {
            **self.common_params(),
            "db": "pubmed",
            "id": ",".join(str(pmid) for pmid in pmids),
            "retmode": "xml",
        }
        response = self._get("efetch.fcgi", params)
        self._save_raw("pubmed_efetch", response.text, "xml")
        return response.text

    def fetch_pmc_xml(self, pmcid: str) -> str:
        """抓 PMC 全文 XML：与 PubMed 共用限速器、重试与原始响应落盘。"""
        if not pmcid.strip():
            raise ValueError("PMCID 不能为空")
        params = {
            **self.common_params(),
            "db": "pmc",
            "id": pmcid,
            "retmode": "xml",
        }
        response = self._get("efetch.fcgi", params)
        self._save_raw("pmc_efetch", response.text, "xml")
        return response.text

    def fetch_by_pmids(self, pmids: list[str]) -> list[Article]:
        """按 PMID 分批取回，去重保序；解析失败抛 PubMedError。"""
        unique = list(dict.fromkeys(str(pmid) for pmid in pmids))
        articles: list[Article] = []
        for start in range(0, len(unique), self.batch_size):
            chunk = unique[start : start + self.batch_size]
            xml = self.efetch(chunk)
            if not xml.strip():
                continue
            try:
                articles.extend(parse_articles(xml))
            except PubMedParseError as exc:
                raise PubMedError(f"EFetch XML 解析失败（{len(chunk)} 篇）: {exc}") from exc
        return articles

    def search(self, term: str, max_results: int | None = None) -> list[Article]:
        limit = self.max_results if max_results is None else max_results
        pmids = self.esearch(term, limit)
        logger.info("PubMed 检索 %r：命中 %d 篇", term, len(pmids))
        return self.fetch_by_pmids(pmids)


def search_pubmed(
    query: str,
    max_results: int = 20,
    *,
    settings: dict | None = None,
    client: httpx.Client | None = None,
) -> list[Article]:
    """工具入口：检索式 + 上限 -> Article 列表。"""
    owned = client is None
    searcher = PubMedSearcher(
        settings or {"search": {"max_results_per_query": max_results}},
        client=client,
    )
    try:
        return searcher.search(query, max_results)
    finally:
        if owned:
            searcher.close()


def fetch_articles(
    pmids: list[str],
    *,
    settings: dict | None = None,
    client: httpx.Client | None = None,
) -> list[Article]:
    """工具入口：PMID 列表 -> Article 列表。"""
    owned = client is None
    searcher = PubMedSearcher(settings, client=client)
    try:
        return searcher.fetch_by_pmids(pmids)
    finally:
        if owned:
            searcher.close()
