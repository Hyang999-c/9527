"""CSV 导出：与 JSON 同源的扁平表，UTF-8-SIG 便于 Excel 直接打开。"""

from __future__ import annotations

import csv
from pathlib import Path

from ..licensing import classify_license
from ..schemas import Article, Evidence, Verification

ARTICLE_FIELDS = [
    "pmid",
    "doi",
    "title",
    "authors",
    "year",
    "journal",
    "publication_type",
    "publication_types",
    "fulltext_status",
    "url",
    "source",
    "retrieved_at",
    "missing_fields",
    "license",
    "license_url",
    "license_class",
    "license_commercial",
    "license_derivatives",
    "copyright",
    "abstract",
]

EVIDENCE_FIELDS = [
    "evidence_id",
    "pmid",
    "doi",
    "research_question",
    "claim",
    "evidence_type",
    "statement_type",
    "study_model",
    "methods",
    "reported_results",
    "locator",
    "section",
    "paragraph",
    "quote",
    "limitations",
    "confidence",
    "verification_status",
    "validation_notes",
]

VERIFICATION_FIELDS = [
    "evidence_id",
    "identifier_check",
    "title_check",
    "source_accessible",
    "claim_supported",
    "final_status",
    "issues",
    "checked_at",
]


def _bool(value: bool | None) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


def _join(values: list[str], sep: str = "; ") -> str:
    return sep.join(value for value in values if value)


def _write(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def article_row(article: Article) -> dict[str, object]:
    info = classify_license(article.license, article.license_url)
    return {
        "pmid": article.pmid,
        "doi": article.doi or "",
        "title": article.title,
        "authors": _join(article.authors),
        "year": article.year or "",
        "journal": article.journal or "",
        "publication_type": article.publication_type.value,
        "publication_types": _join(article.publication_types),
        "fulltext_status": article.fulltext_status.value,
        "url": article.url or "",
        "source": article.source,
        "retrieved_at": article.retrieved_at.isoformat(),
        "missing_fields": _join(article.missing_fields, ","),
        "license": article.license or "",
        "license_url": article.license_url or "",
        "license_class": info.license_class.value,
        "license_commercial": _bool(info.commercial_ok),
        "license_derivatives": _bool(info.derivatives_ok),
        "copyright": article.copyright or "",
        "abstract": article.abstract,
    }


def evidence_row(item: Evidence) -> dict[str, object]:
    location = item.source_location
    return {
        "evidence_id": item.evidence_id,
        "pmid": item.pmid,
        "doi": item.doi or "",
        "research_question": item.research_question,
        "claim": item.claim,
        "evidence_type": item.evidence_type.value,
        "statement_type": item.statement_type.value,
        "study_model": item.study_model.value,
        "methods": item.methods or "",
        "reported_results": item.reported_results or "",
        "locator": location.locator,
        "section": location.section or "",
        "paragraph": location.paragraph or "",
        "quote": location.quote or "",
        "limitations": item.limitations or "",
        "confidence": item.confidence,
        "verification_status": item.verification_status.value,
        "validation_notes": _join(item.validation_notes),
    }


def verification_row(check: Verification) -> dict[str, object]:
    return {
        "evidence_id": check.evidence_id,
        "identifier_check": _bool(check.identifier_check),
        "title_check": _bool(check.title_check),
        "source_accessible": _bool(check.source_accessible),
        "claim_supported": _bool(check.claim_supported),
        "final_status": check.final_status.value,
        "issues": _join(check.issues),
        "checked_at": check.checked_at.isoformat(),
    }


def export_csvs(
    articles: list[Article],
    evidence: list[Evidence],
    verifications: list[Verification],
    output_dir: str | Path,
    run_id: str,
) -> dict[str, Path]:
    """写出三张表，文件名带 run_id；返回路径便于报告或日志引用。"""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)

    paths = {
        "articles": directory / f"articles_{run_id}.csv",
        "evidence": directory / f"evidence_{run_id}.csv",
        "verifications": directory / f"verifications_{run_id}.csv",
    }
    _write(paths["articles"], ARTICLE_FIELDS, [article_row(a) for a in articles])
    _write(paths["evidence"], EVIDENCE_FIELDS, [evidence_row(e) for e in evidence])
    _write(
        paths["verifications"],
        VERIFICATION_FIELDS,
        [verification_row(v) for v in verifications],
    )
    return paths
