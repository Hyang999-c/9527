from __future__ import annotations

import csv

from aspirin_agent.schemas import (
    Article,
    Evidence,
    EvidenceType,
    FullTextStatus,
    PublicationType,
    SourceLocation,
    StatementType,
    StudyModel,
    Verification,
    VerificationStatus,
)
from aspirin_agent.tools.csv_export import (
    ARTICLE_FIELDS,
    EVIDENCE_FIELDS,
    VERIFICATION_FIELDS,
    export_csvs,
)


def make_data():
    article = Article(
        pmid="1",
        title="Aspirin trial",
        authors=["Li Wei", "Zhou Yang"],
        year=2020,
        journal="Lancet",
        publication_type=PublicationType.RCT,
        abstract="aspirin reduced events",
        fulltext_status=FullTextStatus.ABSTRACT_ONLY,
        license="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        copyright="© 2020 Authors",
    )
    item = Evidence(
        evidence_id="1-E01",
        pmid="1",
        research_question="阿司匹林是否降低事件",
        claim="阿司匹林降低严重血管事件",
        evidence_type=EvidenceType.PRIMARY_RESULT,
        statement_type=StatementType.FACT,
        study_model=StudyModel.HUMAN,
        source_location=SourceLocation(locator="abstract", quote="aspirin reduced events"),
        confidence=0.8,
        validation_notes=["测试提示"],
    )
    check = Verification(
        evidence_id="1-E01",
        identifier_check=True,
        title_check=False,
        source_accessible=True,
        claim_supported=None,
        issues=["标题不一致"],
        final_status=VerificationStatus.PARTIAL,
    )
    return article, item, check


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_export_writes_three_tables(tmp_path) -> None:
    article, item, check = make_data()
    paths = export_csvs([article], [item], [check], tmp_path, "RUN1")

    assert paths["articles"].name == "articles_RUN1.csv"
    assert paths["evidence"].name == "evidence_RUN1.csv"
    assert paths["verifications"].name == "verifications_RUN1.csv"
    assert all(path.exists() for path in paths.values())


def test_csv_is_utf8_sig_and_has_headers(tmp_path) -> None:
    article, item, check = make_data()
    paths = export_csvs([article], [item], [check], tmp_path, "RUN1")

    for path in paths.values():
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")

    assert list(read_rows(paths["articles"])[0].keys()) == ARTICLE_FIELDS
    assert list(read_rows(paths["evidence"])[0].keys()) == EVIDENCE_FIELDS
    assert list(read_rows(paths["verifications"])[0].keys()) == VERIFICATION_FIELDS


def test_row_values_are_flat(tmp_path) -> None:
    article, item, check = make_data()
    paths = export_csvs([article], [item], [check], tmp_path, "RUN1")

    article_row = read_rows(paths["articles"])[0]
    assert article_row["authors"] == "Li Wei; Zhou Yang"
    assert article_row["missing_fields"] == "doi"
    assert article_row["publication_type"] == "rct"
    assert article_row["license"] == "CC BY 4.0"
    assert article_row["license_url"].endswith("by/4.0/")
    assert article_row["license_class"] == "cc_by"
    assert article_row["license_commercial"] == "true"

    evidence_row = read_rows(paths["evidence"])[0]
    assert evidence_row["statement_type"] == "fact"
    assert evidence_row["quote"] == "aspirin reduced events"
    assert evidence_row["validation_notes"] == "测试提示"
    assert evidence_row["verification_status"] == "pending"

    verification_row = read_rows(paths["verifications"])[0]
    assert verification_row["identifier_check"] == "true"
    assert verification_row["title_check"] == "false"
    assert verification_row["claim_supported"] == ""
    assert verification_row["issues"] == "标题不一致"
    assert verification_row["final_status"] == "partial"


def test_empty_inputs_still_write_headers(tmp_path) -> None:
    paths = export_csvs([], [], [], tmp_path, "EMPTY")

    assert read_rows(paths["articles"]) == []
    assert paths["evidence"].read_text(encoding="utf-8-sig").strip().startswith("evidence_id")
