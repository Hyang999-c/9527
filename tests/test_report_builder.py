from __future__ import annotations

from aspirin_agent.schemas import (
    Article,
    Evidence,
    FullTextStatus,
    PublicationType,
    SourceLocation,
    StatementType,
    StudyModel,
    Verification,
    VerificationStatus,
)
from aspirin_agent.tools.report_builder import build_report


def test_report_contains_traceable_sections() -> None:
    article = Article(
        pmid="1",
        title="Aspirin trial",
        journal="Lancet",
        year=2020,
        publication_type=PublicationType.RCT,
        abstract="aspirin reduced events",
        fulltext_status=FullTextStatus.ABSTRACT_ONLY,
    )
    item = Evidence(
        evidence_id="1-E01",
        pmid="1",
        research_question="q",
        claim="阿司匹林降低严重血管事件",
        statement_type=StatementType.AUTHOR_INTERPRETATION,
        study_model=StudyModel.HUMAN,
        source_location=SourceLocation(locator="abstract", quote="aspirin reduced events"),
        confidence=0.7,
        validation_notes=["测试提示：来源仅摘要"],
    )
    check = Verification(
        evidence_id="1-E01",
        identifier_check=True,
        title_check=True,
        source_accessible=True,
        claim_supported=True,
        issues=["证据仅来自摘要或全文缺失，未完成全文核查"],
        final_status=VerificationStatus.PARTIAL,
    )

    report = build_report([article], [item], [check], question="阿司匹林是否有效？")
    markdown = report.markdown

    assert "阿司匹林研究证据简报" in markdown
    assert "阿司匹林是否有效？" in markdown
    assert "1-E01" in markdown
    assert "阿司匹林降低严重血管事件" in markdown
    assert "https://pubmed.ncbi.nlm.nih.gov/1/" in markdown
    assert "陈述类型：作者解释" in markdown
    assert "部分通过" in markdown
    assert "仅摘要" in markdown
    assert "未报告" in markdown
    assert "校验提示：测试提示：来源仅摘要" in markdown
    assert "不构成医学建议" in markdown
    assert "1 条" in report.summary


def test_report_handles_empty_inputs() -> None:
    report = build_report([], [], [], question="空")

    assert "本轮未抽取到证据" in report.markdown
    assert "无证据条目" in report.markdown
