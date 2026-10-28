from __future__ import annotations

import json

import pytest

from aspirin_agent.errors import EvidenceExtractionError
from aspirin_agent.schemas import (
    Article,
    EvidenceType,
    FullTextStatus,
    PublicationType,
    StudyModel,
    VerificationStatus,
)
from aspirin_agent.tools.evidence_extract import extract_batch, extract_evidence, parse_json_payload

FULL_PAYLOAD = {
    "claim": "阿司匹林降低二级预防中的严重血管事件",
    "evidence_type": "primary_result",
    "study_model": "human",
    "methods": "随机双盲对照试验",
    "reported_results": "RR 0.81 (95% CI 0.75-0.87)",
    "source_location": {
        "locator": "abstract",
        "section": "RESULTS",
        "paragraph": None,
        "quote": "aspirin reduced major vascular events",
    },
    "limitations": "出血风险增加",
    "confidence": 0.8,
}


class FakeLLM:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls = 0

    def complete(self, messages: list[dict], **kwargs) -> str:
        self.calls += 1
        return json.dumps(self.payload, ensure_ascii=False)


def make_article(**overrides) -> Article:
    data = {
        "pmid": "1",
        "title": "Aspirin for secondary prevention",
        "abstract": "aspirin reduced major vascular events",
    }
    data.update(overrides)
    return Article(**data)


def test_extract_maps_all_fields() -> None:
    article = make_article()
    items = extract_evidence(
        article, "阿司匹林是否降低血管事件", FakeLLM({"evidence": [FULL_PAYLOAD]})
    )

    assert len(items) == 1
    item = items[0]
    assert item.evidence_id == "1-E01"
    assert item.pmid == "1"
    assert item.research_question == "阿司匹林是否降低血管事件"
    assert item.evidence_type is EvidenceType.PRIMARY_RESULT
    assert item.study_model is StudyModel.HUMAN
    assert item.reported_results == "RR 0.81 (95% CI 0.75-0.87)"
    assert item.source_location.locator == "abstract"
    assert item.source_title == article.title
    assert item.verification_status is VerificationStatus.PENDING


def test_accepts_bare_array_and_single_object() -> None:
    assert len(parse_json_payload(json.dumps([FULL_PAYLOAD]))) == 1
    assert len(parse_json_payload(json.dumps(FULL_PAYLOAD))) == 1


def test_review_primary_result_downgraded() -> None:
    article = make_article(
        publication_type=PublicationType.REVIEW,
        title="Review of aspirin",
        abstract="aspirin reduced major vascular events",
    )
    item = extract_evidence(article, "q", FakeLLM({"evidence": [FULL_PAYLOAD]}))[0]

    assert item.evidence_type is EvidenceType.REVIEW_SUMMARY
    assert any("综述" in note for note in item.validation_notes)


def test_fulltext_locator_without_fulltext_is_relabelled() -> None:
    article = make_article(fulltext_status=FullTextStatus.ABSTRACT_ONLY)
    payload = {
        **FULL_PAYLOAD,
        "source_location": {
            "locator": "fulltext",
            "section": "Results",
            "quote": "aspirin reduced major vascular events",
        },
    }
    item = extract_evidence(article, "q", FakeLLM({"evidence": [payload]}))[0]

    assert item.source_location.locator == "abstract"
    assert any("仅取到摘要" in note for note in item.validation_notes)


def test_unlocatable_quote_marked_none() -> None:
    article = make_article(fulltext_status=FullTextStatus.ABSTRACT_ONLY)
    payload = {
        **FULL_PAYLOAD,
        "source_location": {
            "locator": "fulltext",
            "quote": "aspirin cured every disease",
        },
    }
    item = extract_evidence(article, "q", FakeLLM({"evidence": [payload]}))[0]

    assert item.source_location.locator == "none"
    assert item.source_location.is_locatable is False
    assert any("无法在摘要中定位" in note for note in item.validation_notes)


def test_missing_fields_stay_empty() -> None:
    payload = [{"claim": "阿司匹林可能抑制血小板聚集", "confidence": 0.4}]
    items = extract_evidence(make_article(), "q", FakeLLM(payload))

    item = items[0]
    assert item.methods is None
    assert item.reported_results is None
    assert item.source_location.locator == "none"
    assert set(item.missing_fields) >= {"methods", "study_model", "source_location"}
    assert item.evidence_type is EvidenceType.OTHER


def test_unknown_enum_values_fall_back() -> None:
    payload = [
        {
            "claim": "阿司匹林抑制环氧合酶",
            "evidence_type": "not-a-type",
            "study_model": "not-a-model",
        }
    ]
    item = extract_evidence(make_article(), "q", FakeLLM(payload))[0]

    assert item.evidence_type is EvidenceType.OTHER
    assert item.study_model is StudyModel.UNCLEAR


def test_numeric_fields_are_coerced() -> None:
    payload = {
        "claim": "阿司匹林降低血小板聚集",
        "methods": 2019,
        "reported_results": 0.81,
        "source_location": {"locator": "abstract", "paragraph": 1, "quote": "aspirin reduced aggregation"},
    }
    item = extract_evidence(make_article(), "q", FakeLLM({"evidence": [payload]}))[0]

    assert item.methods == "2019"
    assert item.reported_results == "0.81"
    assert item.source_location.paragraph == "1"


def test_empty_evidence_list_is_valid() -> None:
    assert extract_evidence(make_article(), "q", FakeLLM({"evidence": []})) == []


def test_invalid_json_raises() -> None:
    class BadLLM:
        def complete(self, messages: list[dict], **kwargs) -> str:
            return "抱歉，我无法回答"

    with pytest.raises(EvidenceExtractionError):
        extract_evidence(make_article(), "q", BadLLM())


def test_invalid_items_are_dropped() -> None:
    payload = [
        {"claim": "有效"},  # claim 太短
        {"claim": "阿司匹林抑制血小板", "confidence": 1.5},  # 置信度越界
        FULL_PAYLOAD,
    ]
    items = extract_evidence(make_article(), "q", FakeLLM(payload))

    assert len(items) == 1
    assert items[0].evidence_id == "1-E01"


def test_batch_collects_failures() -> None:
    class FlakyLLM:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, messages: list[dict], **kwargs) -> str:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("模型超时")
            return json.dumps({"evidence": [FULL_PAYLOAD]}, ensure_ascii=False)

    articles = [make_article(pmid="1"), make_article(pmid="2")]
    batch = extract_batch(articles, "q", FlakyLLM(), batch_size=5)

    assert [item.pmid for item in batch.evidence] == ["2"]
    assert len(batch.failures) == 1
    assert batch.failures[0].pmid == "1"
    assert "模型超时" in batch.failures[0].error
