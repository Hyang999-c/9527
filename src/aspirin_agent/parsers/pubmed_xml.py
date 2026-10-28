"""PubMed EFetch XML 解析为 Article；解析失败抛 PubMedParseError。"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from ..errors import PubMedParseError
from ..schemas import Article, FullTextStatus, PublicationType
from ..utils.logging_utils import get_logger

logger = get_logger(__name__)

# 顺序有意义：先具体后宽泛
_PUBLICATION_TYPE_RULES: tuple[tuple[str, PublicationType], ...] = (
    ("meta-analysis", PublicationType.META_ANALYSIS),
    ("systematic review", PublicationType.SYSTEMATIC_REVIEW),
    ("randomized controlled trial", PublicationType.RCT),
    ("clinical trial", PublicationType.RCT),
    ("observational study", PublicationType.COHORT),
    ("case reports", PublicationType.CASE_REPORT),
    ("review", PublicationType.REVIEW),
)


def _text(node: ET.Element, path: str, default: str | None = None) -> str | None:
    found = node.find(path)
    if found is None:
        return default
    value = "".join(found.itertext()).strip()
    return value or default


def _abstract(article: ET.Element) -> str:
    parts: list[str] = []
    for node in article.findall(".//Abstract/AbstractText"):
        text = "".join(node.itertext()).strip()
        if not text:
            continue
        label = node.get("Label")
        parts.append(f"{label}: {text}" if label else text)
    return "\n".join(parts)


def _authors(article: ET.Element) -> list[str]:
    names: list[str] = []
    for author in article.findall(".//AuthorList/Author"):
        last = _text(author, "LastName")
        fore = _text(author, "ForeName")
        if last:
            names.append(f"{last} {fore}".strip() if fore else last)
            continue
        collective = _text(author, "CollectiveName")
        if collective:
            names.append(collective)
    return names


def _year(article: ET.Element) -> int | None:
    for path in (".//JournalIssue/PubDate/Year", ".//ArticleDate/Year"):
        value = _text(article, path)
        if value and value.isdigit():
            return int(value)
    medline = _text(article, ".//JournalIssue/PubDate/MedlineDate") or ""
    match = re.search(r"(?:19|20)\d{2}", medline)
    return int(match.group(0)) if match else None


def _publication_types(article: ET.Element) -> list[str]:
    raw = [
        (node.text or "").strip()
        for node in article.findall(".//PublicationTypeList/PublicationType")
    ]
    return [item for item in raw if item]


def _publication_type(publication_types: list[str]) -> PublicationType:
    lowered = [item.lower() for item in publication_types]
    for label, publication_type in _PUBLICATION_TYPE_RULES:
        if any(label in item for item in lowered):
            return publication_type
    return PublicationType.OTHER


def parse_articles(xml_text: str, source: str = "pubmed") -> list[Article]:
    """解析 PubmedArticleSet；缺 PMID 的条目跳过，XML 损坏则抛错。"""
    if not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise PubMedParseError(f"XML 解析失败: {exc}") from exc

    book_entries = len(root.findall(".//PubmedBookArticle"))
    if book_entries:
        logger.info("跳过 %d 条 PubMed Book 条目（第一版不处理）", book_entries)

    records: list[Article] = []
    for article in root.findall(".//PubmedArticle"):
        pmid = _text(article, ".//MedlineCitation/PMID")
        if not pmid:
            continue
        # 只取本篇 PubmedData 下的 ID；".//" 会把参考文献里的 ArticleId 也扫进来
        ids = {
            (node.get("IdType") or ""): (node.text or "").strip()
            for node in article.findall("PubmedData/ArticleIdList/ArticleId")
        }
        doi = ids.get("doi") or _text(article, ".//ELocationID[@EIdType='doi']")
        pmcid = ids.get("pmc")
        journal = _text(article, ".//Journal/ISOAbbreviation") or _text(article, ".//Journal/Title")
        publication_types = _publication_types(article)
        abstract = _abstract(article)
        records.append(
            Article(
                pmid=pmid,
                doi=doi or None,
                pmcid=pmcid or None,
                title=_text(article, ".//ArticleTitle", "Untitled") or "Untitled",
                abstract=abstract,
                authors=_authors(article),
                journal=journal,
                year=_year(article),
                publication_types=publication_types,
                publication_type=_publication_type(publication_types),
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                source=source,
                fulltext_status=(
                    FullTextStatus.ABSTRACT_ONLY if abstract else FullTextStatus.NOT_FETCHED
                ),
            )
        )
    return records
