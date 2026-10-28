"""证据抽取：单篇文献 -> LLM -> 结构化 Evidence。

模型输出先过 _EvidenceDraft 校验，再按科学规则处理：
- 综述/系统综述中的 primary_result 一律降为 review_summary
- 来源位置必须与实际拿到的文本对得上，对不上就改标或置 none
- 缺失信息保持为空，由 missing_fields 暴露
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator

from ..errors import EvidenceExtractionError
from ..schemas import (
    Article,
    Evidence,
    EvidenceType,
    ExtractionBatch,
    ExtractionFailure,
    FullTextStatus,
    PublicationType,
    SourceLocation,
    StudyModel,
)
from ..utils.logging_utils import get_logger

logger = get_logger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
SYSTEM_PROMPT = "你是严谨的药学文献证据抽取助手，只输出 JSON，不编造数据。"

_LOCATORS = {"abstract", "fulltext", "none"}


def _as_text(value: object) -> object:
    """模型常把段落号、年份写成数字；统一转字符串，不因类型细节丢整条证据。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return str(value)
    return value


class _DraftLocation(BaseModel):
    locator: str = "none"
    section: str | None = None
    paragraph: str | None = None
    quote: str | None = None

    @field_validator("section", "paragraph", "quote", mode="before")
    @classmethod
    def _coerce_text(cls, value: object) -> object:
        return _as_text(value)


class _EvidenceDraft(BaseModel):
    claim: str = Field(min_length=5)
    evidence_type: str = "other"
    study_model: str = "unclear"
    methods: str | None = None
    reported_results: str | None = None
    source_location: _DraftLocation = Field(default_factory=_DraftLocation)
    limitations: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("claim", "evidence_type", "study_model", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("methods", "reported_results", "limitations", mode="before")
    @classmethod
    def _coerce_text(cls, value: object) -> object:
        return _as_text(value)

    @field_validator("source_location", mode="before")
    @classmethod
    def _location_must_be_object(cls, value: object) -> object:
        return value if isinstance(value, dict) else {}


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"提示词不存在: {path}")
    return path.read_text(encoding="utf-8")


def render_prompt(template: str, article: Article) -> str:
    mapping = {
        "TITLE": article.title,
        "ABSTRACT": article.abstract or "(无摘要)",
        "FULLTEXT": article.fulltext or "(无全文)",
        "PMID": article.pmid,
        "DOI": article.doi or "",
        "JOURNAL": article.journal or "",
        "YEAR": str(article.year or ""),
    }
    for key, value in mapping.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def _slice(text: str, opener: str, closer: str) -> str:
    start, end = text.find(opener), text.rfind(closer)
    if start == -1 or end <= start:
        return ""
    return text[start : end + 1]


def parse_json_payload(raw: str) -> list[dict]:
    """接受数组或 {"evidence": [...]}；前后夹带解释文字也能截取。"""
    text = raw.strip()
    data: object = None
    for candidate in (text, _slice(text, "{", "}"), _slice(text, "[", "]")):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue

    if data is None:
        raise EvidenceExtractionError(f"模型输出不是合法 JSON: {raw[:200]}")

    if isinstance(data, list):
        payloads = data
    elif isinstance(data, dict):
        payloads = next(
            (data[key] for key in ("evidence", "items", "data") if isinstance(data.get(key), list)),
            [data] if "claim" in data else None,
        )
    else:
        payloads = None

    if payloads is None:
        raise EvidenceExtractionError("模型输出缺少证据数组")
    # {"evidence": []} 是合法结果：这篇文献没有可抽取的证据
    return [item for item in payloads if isinstance(item, dict)]


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_enum(enum_cls, value: object, fallback):
    try:
        return enum_cls(str(value))
    except ValueError:
        return fallback


def _normalized(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _contains(quote: str, source: str | None) -> bool:
    return bool(source) and _normalized(quote) in _normalized(source)


def _normalize_location(
    draft: _DraftLocation, article: Article
) -> tuple[SourceLocation, list[str]]:
    notes: list[str] = []
    locator = draft.locator if draft.locator in _LOCATORS else "none"
    if draft.locator not in _LOCATORS:
        notes.append(f"未知来源类型 {draft.locator!r}，按未定位处理")

    quote = _clean(draft.quote)
    if not quote:
        if locator != "none":
            notes.append("标注了来源位置但没给引句")
        return (
            SourceLocation(locator=locator, section=_clean(draft.section), paragraph=_clean(draft.paragraph)),
            notes,
        )

    if locator == "fulltext" and article.fulltext_status is not FullTextStatus.FULLTEXT_AVAILABLE:
        if _contains(quote, article.abstract):
            notes.append("标注全文位置但仅取到摘要；引句在摘要中定位，改标 abstract")
            locator = "abstract"
        else:
            notes.append("标注全文位置但该文献未取到全文，引句无法在摘要中定位")
            locator = "none"

    elif locator == "abstract" and not article.abstract:
        if _contains(quote, article.fulltext):
            notes.append("标注摘要位置但该文献无摘要；引句在全文定位，改标 fulltext")
            locator = "fulltext"
        else:
            notes.append("标注摘要位置但该文献无摘要，引句无法定位")
            locator = "none"

    if locator == "none":
        notes.append("没有可定位的原文位置")

    return (
        SourceLocation(
            locator=locator,
            section=_clean(draft.section),
            paragraph=_clean(draft.paragraph),
            quote=quote,
        ),
        notes,
    )


def _evidence_type(article: Article, raw: object, notes: list[str]) -> EvidenceType:
    evidence_type = _coerce_enum(EvidenceType, raw, EvidenceType.OTHER)
    if (
        article.publication_type in {PublicationType.REVIEW, PublicationType.SYSTEMATIC_REVIEW}
        and evidence_type is EvidenceType.PRIMARY_RESULT
    ):
        notes.append("综述类文献中的主张不得标为原始结果，已改为综述转述")
        return EvidenceType.REVIEW_SUMMARY
    return evidence_type


def _to_evidence(
    draft: _EvidenceDraft,
    *,
    article: Article,
    research_question: str,
    index: int,
) -> Evidence:
    notes: list[str] = []
    location, location_notes = _normalize_location(draft.source_location, article)
    notes.extend(location_notes)
    evidence_type = _evidence_type(article, draft.evidence_type, notes)

    return Evidence(
        evidence_id=f"{article.pmid}-E{index:02d}",
        pmid=article.pmid,
        doi=article.doi,
        research_question=research_question,
        claim=draft.claim,
        evidence_type=evidence_type,
        study_model=_coerce_enum(StudyModel, draft.study_model, StudyModel.UNCLEAR),
        methods=_clean(draft.methods),
        reported_results=_clean(draft.reported_results),
        source_location=location,
        limitations=_clean(draft.limitations),
        confidence=draft.confidence,
        source_title=article.title,
        validation_notes=notes,
    )


def extract_evidence(
    article: Article,
    research_question: str,
    llm,
    prompt_template: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 2000,
) -> list[Evidence]:
    """从单篇文献抽取证据；输出无法解析时抛 EvidenceExtractionError。"""
    template = prompt_template or load_prompt("extract_evidence.md")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": render_prompt(template, article)},
    ]
    raw = llm.complete(messages, temperature=temperature, max_tokens=max_tokens, json_mode=True)
    payloads = parse_json_payload(raw)

    items: list[Evidence] = []
    for payload in payloads:
        try:
            draft = _EvidenceDraft.model_validate(payload)
        except ValidationError as exc:
            logger.warning("丢弃不合规证据条目 PMID %s: %s", article.pmid, exc.errors()[:2])
            continue
        items.append(
            _to_evidence(
                draft,
                article=article,
                research_question=research_question,
                index=len(items) + 1,
            )
        )
    return items


def extract_batch(
    articles: list[Article],
    research_question: str,
    llm,
    batch_size: int = 5,
    temperature: float = 0.1,
    max_tokens: int = 2000,
) -> ExtractionBatch:
    """逐篇抽取；单篇失败进 failures，不污染证据列表，也不假装成功。"""
    batch = ExtractionBatch()
    for start in range(0, len(articles), max(1, batch_size)):
        chunk = articles[start : start + batch_size]
        logger.info("抽取证据 %d-%d / %d", start + 1, start + len(chunk), len(articles))
        for article in chunk:
            try:
                batch.evidence.extend(
                    extract_evidence(
                        article,
                        research_question,
                        llm,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - 单篇失败不拖垮整批
                logger.warning("证据抽取失败 PMID %s: %s", article.pmid, exc)
                batch.failures.append(
                    ExtractionFailure(
                        pmid=article.pmid,
                        error=f"{type(exc).__name__}: {exc}"[:300],
                    )
                )
    return batch
