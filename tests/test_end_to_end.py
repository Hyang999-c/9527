from __future__ import annotations

import json

from aspirin_agent.orchestrator import Orchestrator
from aspirin_agent.schemas import Article, FullTextStatus, VerificationStatus


class FakeSearcher:
    def __init__(self, articles: list[Article]) -> None:
        self.articles = articles
        self.calls: list[str] = []

    def search(self, term: str, max_results: int | None = None) -> list[Article]:
        self.calls.append(term)
        return list(self.articles)


class FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages: list[dict], **kwargs) -> str:
        self.calls += 1
        return json.dumps(
            {
                "evidence": [
                    {
                        "claim": "阿司匹林降低二级预防中的严重血管事件",
                        "evidence_type": "primary_result",
                        "study_model": "human",
                        "methods": "随机对照试验",
                        "reported_results": "RR 0.81",
                        "source_location": {
                            "locator": "fulltext",
                            "section": "Results",
                            "quote": "aspirin reduced major vascular events",
                        },
                        "limitations": "出血风险增加",
                        "confidence": 0.8,
                    }
                ]
            },
            ensure_ascii=False,
        )


def build_articles() -> list[Article]:
    first = Article(
        pmid="1",
        title="Aspirin trial",
        abstract="aspirin reduced major vascular events",
        fulltext="In this trial aspirin reduced major vascular events in adults.",
        fulltext_status=FullTextStatus.FULLTEXT_AVAILABLE,
        doi="10.1/a",
    )
    second = Article(
        pmid="2",
        title="Bleeding risk study",
        abstract="aspirin increased bleeding",
        fulltext_status=FullTextStatus.ABSTRACT_ONLY,
    )
    return [first, second, first.model_copy()]


def test_pipeline_runs_offline(tmp_path) -> None:
    searcher = FakeSearcher(build_articles())
    llm = FakeLLM()
    orchestrator = Orchestrator(
        {"search": {"max_results_per_query": 10}},
        llm=llm,
        searcher=searcher,
        workdir=tmp_path,
    )

    result = orchestrator.run("阿司匹林二级预防的获益与风险", ["aspirin secondary prevention"])

    assert searcher.calls == ["aspirin secondary prevention"]
    assert len(result.articles) == 2
    assert result.stats["duplicates_removed"] == 1
    assert result.stats["extraction_failures"] == 0
    assert len(result.evidence) == 2
    assert llm.calls == 2
    assert len(result.verifications) == 2

    statuses = {check.evidence_id: check.final_status for check in result.verifications}
    assert statuses["1-E01"] is VerificationStatus.PASSED
    assert statuses["2-E01"] is VerificationStatus.FAILED

    assert result.report is not None
    assert "阿司匹林研究证据简报" in result.report.markdown
    assert "阿司匹林降低二级预防中的严重血管事件" in result.report.markdown

    raw_files = list((tmp_path / "data" / "raw").glob("articles_*.json"))
    assert raw_files
    saved = json.loads(raw_files[0].read_text(encoding="utf-8"))
    assert len(saved) == 2

    processed_files = list((tmp_path / "data" / "processed").glob("evidence_*.json"))
    assert processed_files
    processed = json.loads(processed_files[0].read_text(encoding="utf-8"))
    assert len(processed["evidence"]) == 2
    assert len(processed["verifications"]) == 2

    assert list((tmp_path / "reports").glob("report_*.md"))


def test_pipeline_without_llm_still_reports(tmp_path) -> None:
    orchestrator = Orchestrator(
        {"search": {"max_results_per_query": 3}},
        llm=None,
        searcher=FakeSearcher(build_articles()[:1]),
        workdir=tmp_path,
    )

    result = orchestrator.run("只检索")

    assert result.evidence == []
    assert result.verifications == []
    assert result.report is not None
    assert "本轮未抽取到证据" in result.report.markdown
