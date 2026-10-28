from __future__ import annotations

import json

import httpx

from aspirin_agent.schemas import (
    Article,
    Evidence,
    FullTextStatus,
    SourceLocation,
    StudyModel,
    VerificationStatus,
)
from aspirin_agent.tools.citation_verify import LLMJudge, PubMedResolver, verify_citations


def make_article(**overrides) -> Article:
    data = {
        "pmid": "1",
        "title": "Aspirin trial",
        "abstract": "aspirin reduced major vascular events",
        "fulltext": "In this trial aspirin reduced major vascular events.",
        "fulltext_status": FullTextStatus.FULLTEXT_AVAILABLE,
    }
    data.update(overrides)
    return Article(**data)


def make_evidence(**overrides) -> Evidence:
    data = {
        "evidence_id": "1-E01",
        "pmid": "1",
        "research_question": "q",
        "claim": "阿司匹林降低严重血管事件",
        "study_model": StudyModel.HUMAN,
        "source_title": "Aspirin trial",
        "source_location": SourceLocation(
            locator="fulltext", quote="aspirin reduced major vascular events"
        ),
        "confidence": 0.8,
    }
    data.update(overrides)
    return Evidence(**data)


def test_fulltext_quote_passes() -> None:
    article = make_article()
    item = make_evidence()

    checks = verify_citations([item], [article])

    assert len(checks) == 1
    check = checks[0]
    assert check.final_status is VerificationStatus.PASSED
    assert check.identifier_check is True
    assert check.title_check is True
    assert check.source_accessible is True
    assert check.claim_supported is True
    assert check.issues == []
    assert item.verification_status is VerificationStatus.PASSED


def test_abstract_only_is_partial_and_flagged() -> None:
    article = make_article(
        fulltext=None,
        fulltext_status=FullTextStatus.ABSTRACT_ONLY,
    )
    item = make_evidence(
        source_location=SourceLocation(locator="abstract", quote="aspirin reduced major vascular events")
    )

    checks = verify_citations([item], [article])

    assert checks[0].final_status is VerificationStatus.PARTIAL
    assert any("摘要" in issue for issue in checks[0].issues)


def test_missing_article_fails() -> None:
    item = make_evidence()

    checks = verify_citations([item], [])

    assert checks[0].final_status is VerificationStatus.FAILED
    assert checks[0].identifier_check is None
    assert any("不在本次检索" in issue for issue in checks[0].issues)


def test_quote_mismatch_fails() -> None:
    article = make_article()
    item = make_evidence(
        source_location=SourceLocation(locator="fulltext", quote="aspirin cured every disease")
    )

    checks = verify_citations([item], [article])

    assert checks[0].claim_supported is False
    assert checks[0].final_status is VerificationStatus.FAILED
    assert any("未能在原文中定位" in issue for issue in checks[0].issues)


def test_missing_quote_is_not_verifiable() -> None:
    item = make_evidence(source_location=SourceLocation())

    checks = verify_citations([item], [make_article()])

    assert checks[0].claim_supported is None
    assert checks[0].final_status is VerificationStatus.NOT_VERIFIABLE
    assert any("引句" in issue for issue in checks[0].issues)


def test_title_mismatch_fails() -> None:
    item = make_evidence(source_title="A different paper")

    checks = verify_citations([item], [make_article()])

    assert checks[0].title_check is False
    assert checks[0].final_status is VerificationStatus.FAILED


def test_resolver_failure_fails() -> None:
    checks = verify_citations(
        [make_evidence()],
        [make_article()],
        resolver=lambda pmid, doi: False,
    )

    assert checks[0].identifier_check is False
    assert checks[0].final_status is VerificationStatus.FAILED
    assert any("在线校验" in issue for issue in checks[0].issues)


def test_judge_can_reject_quote() -> None:
    checks = verify_citations(
        [make_evidence()],
        [make_article()],
        judge=lambda item, article: False,
    )

    assert checks[0].claim_supported is False
    assert checks[0].final_status is VerificationStatus.FAILED


def test_unknown_online_result_is_partial() -> None:
    checks = verify_citations(
        [make_evidence()],
        [make_article()],
        resolver=lambda pmid, doi: None,
    )

    assert checks[0].identifier_check is True
    assert checks[0].final_status is VerificationStatus.PARTIAL
    assert any("在线校验不可用" in issue for issue in checks[0].issues)


def test_judge_exception_is_not_fatal() -> None:
    def bad_judge(item, article):
        raise RuntimeError("judge boom")

    checks = verify_citations([make_evidence()], [make_article()], judge=bad_judge)

    assert checks[0].claim_supported is None
    assert checks[0].final_status is VerificationStatus.NOT_VERIFIABLE
    assert any("语义判定" in issue for issue in checks[0].issues)


class FakeJudgeLLM:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def complete(self, messages: list[dict], **kwargs) -> str:
        return json.dumps(self.payload, ensure_ascii=False)


def test_llm_judge_parses_supported() -> None:
    judge = LLMJudge(FakeJudgeLLM({"supported": False, "reason": "not enough"}))

    assert judge(make_evidence(), make_article()) is False


def test_llm_judge_invalid_output_returns_none() -> None:
    judge = LLMJudge(FakeJudgeLLM({"verdict": "yes"}))

    assert judge(make_evidence(), make_article()) is None


def test_pubmed_resolver_found_and_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "esummary" in request.url.path
        return httpx.Response(200, json={"result": {"1": {"uid": "1"}}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert PubMedResolver(client=client)("1", None) is True

    def empty_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {}})

    client = httpx.Client(transport=httpx.MockTransport(empty_handler))
    assert PubMedResolver(client=client)("999", None) is False


def test_pubmed_resolver_network_error_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert PubMedResolver(client=client)("1", None) is None


def test_pubmed_resolver_doi_via_crossref() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "crossref" in request.url.host
        return httpx.Response(200, json={"status": "ok"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert PubMedResolver(client=client)(None, "10.1/abc") is True
