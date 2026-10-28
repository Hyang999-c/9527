from __future__ import annotations

import pytest
from pydantic import ValidationError

from aspirin_agent.schemas import (
    Article,
    Evidence,
    FullTextStatus,
    PublicationType,
    SourceLocation,
    StudyModel,
    Verification,
    VerificationStatus,
)


def test_article_missing_fields_are_explicit() -> None:
    article = Article(pmid="1", title="t")

    assert article.missing_fields == ["doi", "year", "journal", "authors", "abstract"]
    assert article.fulltext_status is FullTextStatus.NOT_FETCHED
    assert article.publication_type is PublicationType.OTHER


def test_pmid_must_be_digits() -> None:
    with pytest.raises(ValidationError):
        Article(pmid="PMC123", title="not a pmid")


def test_year_range_is_checked() -> None:
    with pytest.raises(ValidationError):
        Article(pmid="1", title="t", year=1500)


def test_review_detection() -> None:
    review = Article(pmid="1", title="t", publication_type=PublicationType.REVIEW)
    rct = Article(pmid="2", title="t", publication_type=PublicationType.RCT)

    assert review.is_review is True
    assert rct.is_review is False


def test_evidence_passed_requires_location() -> None:
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="1-E01",
            pmid="1",
            research_question="q",
            claim="阿司匹林抑制血小板聚集",
            verification_status=VerificationStatus.PASSED,
        )


def test_evidence_missing_fields_lists_gaps() -> None:
    item = Evidence(evidence_id="1-E01", pmid="1", research_question="q", claim="阿司匹林抑制血小板聚集")

    assert item.study_model is StudyModel.UNCLEAR
    assert set(item.missing_fields) == {"methods", "reported_results", "limitations", "study_model", "source_location"}


def test_evidence_with_location_is_not_flagged_for_source() -> None:
    item = Evidence(
        evidence_id="1-E01",
        pmid="1",
        research_question="q",
        claim="阿司匹林抑制血小板聚集",
        study_model=StudyModel.HUMAN,
        methods="随机双盲试验",
        reported_results="血小板聚集率下降",
        limitations="样本量小",
        source_location=SourceLocation(locator="abstract", quote="aspirin reduced aggregation"),
    )

    assert "source_location" not in item.missing_fields
    assert item.source_location.is_locatable is True


def test_verification_passed_requires_all_checks() -> None:
    with pytest.raises(ValidationError):
        Verification(
            evidence_id="1-E01",
            identifier_check=True,
            title_check=True,
            source_accessible=True,
            claim_supported=None,
            final_status=VerificationStatus.PASSED,
        )


def test_verification_passed_requires_no_issues() -> None:
    with pytest.raises(ValidationError):
        Verification(
            evidence_id="1-E01",
            identifier_check=True,
            title_check=True,
            source_accessible=True,
            claim_supported=True,
            issues=["标题不一致"],
            final_status=VerificationStatus.PASSED,
        )


def test_verification_passed_with_all_checks_ok() -> None:
    check = Verification(
        evidence_id="1-E01",
        identifier_check=True,
        title_check=True,
        source_accessible=True,
        claim_supported=True,
        final_status=VerificationStatus.PASSED,
    )

    assert check.final_status is VerificationStatus.PASSED
    assert check.issues == []
