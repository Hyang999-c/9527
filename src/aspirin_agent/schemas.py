"""核心数据模型：Article / Evidence / Verification。

三条硬规则：
1. 缺失信息不推测，字段留空，由 missing_fields 显式列出；
2. 没有可定位原文位置时，Evidence 不得标记为 passed；
3. Verification 只有在标识符、标题、可访问性与主张支持四项全部为 True、
   且没有遗留问题的情况下，才允许最终状态为 passed。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PublicationType(str, Enum):
    SYSTEMATIC_REVIEW = "systematic_review"
    META_ANALYSIS = "meta_analysis"
    REVIEW = "review"
    RCT = "rct"
    COHORT = "cohort"
    CASE_CONTROL = "case_control"
    CASE_REPORT = "case_report"
    PRECLINICAL = "preclinical"
    OTHER = "other"


class StudyModel(str, Enum):
    HUMAN = "human"
    ANIMAL = "animal"
    CELL = "cell"
    BIOCHEMICAL = "biochemical"
    COMPUTATIONAL = "computational"
    MIXED = "mixed"
    UNCLEAR = "unclear"


class EvidenceType(str, Enum):
    PRIMARY_RESULT = "primary_result"
    SECONDARY_RESULT = "secondary_result"
    REVIEW_SUMMARY = "review_summary"
    MECHANISM = "mechanism"
    OTHER = "other"


class FullTextStatus(str, Enum):
    NOT_FETCHED = "not_fetched"
    ABSTRACT_ONLY = "abstract_only"
    FULLTEXT_AVAILABLE = "fulltext_available"
    FULLTEXT_UNAVAILABLE = "fulltext_unavailable"


class VerificationStatus(str, Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    PASSED = "passed"
    FAILED = "failed"
    NOT_VERIFIABLE = "not_verifiable"


class SourceLocation(BaseModel):
    """证据在原文中的位置；locator=none 表示没有可定位来源。"""

    locator: Literal["abstract", "fulltext", "none"] = "none"
    section: str | None = None
    paragraph: str | None = None
    quote: str | None = None

    @property
    def is_locatable(self) -> bool:
        return self.locator != "none" and bool(self.quote and self.quote.strip())


class Article(BaseModel):
    """一篇文献的规范化记录；publication_types 保留 MEDLINE 原始类型。"""

    pmid: str
    doi: str | None = None
    pmcid: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    journal: str | None = None
    publication_types: list[str] = Field(default_factory=list)
    publication_type: PublicationType = PublicationType.OTHER
    abstract: str = ""
    source: str = "pubmed"
    url: str | None = None
    retrieved_at: datetime = Field(default_factory=_now)
    fulltext_status: FullTextStatus = FullTextStatus.NOT_FETCHED
    fulltext: str | None = None

    @field_validator("pmid")
    @classmethod
    def _pmid_is_digits(cls, value: str) -> str:
        value = value.strip()
        if not value.isdigit():
            raise ValueError("PMID 必须是纯数字")
        return value

    @field_validator("year")
    @classmethod
    def _year_is_plausible(cls, value: int | None) -> int | None:
        if value is not None and not (1800 <= value <= 2100):
            raise ValueError("年份超出合理范围")
        return value

    @property
    def is_review(self) -> bool:
        return self.publication_type in {
            PublicationType.REVIEW,
            PublicationType.SYSTEMATIC_REVIEW,
            PublicationType.META_ANALYSIS,
        }

    @property
    def missing_fields(self) -> list[str]:
        """显式列出缺失字段，供报告与核查使用。"""
        missing: list[str] = []
        for name in ("doi", "year", "journal"):
            if not getattr(self, name):
                missing.append(name)
        if not self.authors:
            missing.append("authors")
        if not self.abstract:
            missing.append("abstract")
        return missing


class Evidence(BaseModel):
    """一条可追溯的证据；来源位置与核查状态必须能对上。"""

    evidence_id: str
    pmid: str
    doi: str | None = None
    research_question: str
    claim: str = Field(min_length=5)
    evidence_type: EvidenceType = EvidenceType.OTHER
    study_model: StudyModel = StudyModel.UNCLEAR
    methods: str | None = None
    reported_results: str | None = None
    source_location: SourceLocation = Field(default_factory=SourceLocation)
    limitations: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    verification_status: VerificationStatus = VerificationStatus.PENDING
    source_title: str | None = Field(
        default=None, description="抽取时记录的文献标题，用于后续标题核对"
    )
    validation_notes: list[str] = Field(
        default_factory=list, description="结构化校验提示；只记录处理，不改写原文结论"
    )

    @field_validator("evidence_id", "pmid")
    @classmethod
    def _identifier_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("标识符不能为空")
        return value

    @model_validator(mode="after")
    def _passed_requires_location(self) -> Evidence:
        if (
            self.verification_status is VerificationStatus.PASSED
            and not self.source_location.is_locatable
        ):
            raise ValueError("没有可定位的原文位置，不得标记为核查通过")
        return self

    @property
    def missing_fields(self) -> list[str]:
        missing = [name for name in ("methods", "reported_results", "limitations") if not getattr(self, name)]
        if self.study_model is StudyModel.UNCLEAR:
            missing.append("study_model")
        if not self.source_location.is_locatable:
            missing.append("source_location")
        return missing


class Verification(BaseModel):
    """一条证据的核查结果；passed 是严格状态，不是默认值。"""

    evidence_id: str
    identifier_check: bool | None = None
    title_check: bool | None = None
    source_accessible: bool | None = None
    claim_supported: bool | None = None
    issues: list[str] = Field(default_factory=list)
    final_status: VerificationStatus = VerificationStatus.PENDING
    checked_at: datetime = Field(default_factory=_now)

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("evidence_id 不能为空")
        return value

    @model_validator(mode="after")
    def _passed_requires_all_checks(self) -> Verification:
        if self.final_status is VerificationStatus.PASSED:
            checks = (
                self.identifier_check,
                self.title_check,
                self.source_accessible,
                self.claim_supported,
            )
            if not all(check is True for check in checks):
                raise ValueError("四项核查未全部通过，不得标记为 passed")
            if self.issues:
                raise ValueError("仍存在未解决问题，不得标记为 passed")
        return self


class ExtractionFailure(BaseModel):
    """一篇文献抽取失败的原因；不混入证据列表。"""

    pmid: str
    error: str


class ExtractionBatch(BaseModel):
    evidence: list[Evidence] = Field(default_factory=list)
    failures: list[ExtractionFailure] = Field(default_factory=list)


class Report(BaseModel):
    title: str
    question: str = ""
    generated_at: datetime = Field(default_factory=_now)
    summary: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    verifications: list[Verification] = Field(default_factory=list)
    markdown: str = ""


class PipelineResult(BaseModel):
    question: str
    queries: list[str] = Field(default_factory=list)
    articles: list[Article] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    verifications: list[Verification] = Field(default_factory=list)
    extraction_failures: list[ExtractionFailure] = Field(default_factory=list)
    report: Report | None = None
    stats: dict[str, int] = Field(default_factory=dict)
