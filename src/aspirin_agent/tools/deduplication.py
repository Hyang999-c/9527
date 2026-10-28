"""去重：先按 PMID/DOI 精确去重，再按标题相似度兜底。"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..schemas import Article

DEFAULT_THRESHOLD = 0.92


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_title(left), normalize_title(right)).ratio()


def deduplicate_records(
    records: list[Article],
    threshold: float = DEFAULT_THRESHOLD,
) -> list[Article]:
    """保留首次出现的记录；同一 PMID、同一 DOI、近似标题都视为重复。"""
    kept: list[Article] = []
    seen_pmids: set[str] = set()
    seen_dois: set[str] = set()
    kept_titles: list[str] = []

    for article in records:
        if article.pmid in seen_pmids:
            continue
        doi = (article.doi or "").lower()
        if doi and doi in seen_dois:
            continue
        normalized = normalize_title(article.title)
        if any(
            SequenceMatcher(None, normalized, other).ratio() >= threshold
            for other in kept_titles
        ):
            continue

        kept.append(article)
        seen_pmids.add(article.pmid)
        if doi:
            seen_dois.add(doi)
        kept_titles.append(normalized)
    return kept
