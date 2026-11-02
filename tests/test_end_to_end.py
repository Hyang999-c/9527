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
                        "statement_type": "fact",
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

    csv_files = sorted((tmp_path / "data" / "exports").glob("*.csv"))
    assert len(csv_files) == 3
    evidence_csv = next(path for path in csv_files if path.name.startswith("evidence_"))
    assert evidence_csv.read_text(encoding="utf-8-sig").splitlines()[0].startswith("evidence_id")


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


def test_related_expansion_adds_articles(tmp_path) -> None:
    class ExpandingSearcher(FakeSearcher):
        def expand_related(self, pmids: list[str], max_results: int = 10) -> list[Article]:
            assert pmids == ["1"]
            return [Article(pmid="99", title="Related aspirin study", abstract="related")]

    orchestrator = Orchestrator(
        {
            "search": {
                "max_results_per_query": 3,
                "expand": {"enabled": True, "seeds": 1, "max_related": 5},
            }
        },
        llm=FakeLLM(),
        searcher=ExpandingSearcher(build_articles()[:1]),
        workdir=tmp_path,
    )

    result = orchestrator.run("扩展测试")

    assert [article.pmid for article in result.articles] == ["1", "99"]
    assert result.stats["related_fetched"] == 1
    assert result.stats["duplicates_removed"] == 0


def test_citation_chasing_adds_articles(tmp_path) -> None:
    class CitationSearcher(FakeSearcher):
        def expand_citations(
            self, pmids: list[str], max_refs: int = 5, max_cited: int = 5
        ) -> list[Article]:
            assert pmids == ["1"]
            return [Article(pmid="88", title="Cited aspirin study", abstract="cited")]

    orchestrator = Orchestrator(
        {
            "search": {
                "max_results_per_query": 3,
                "expand": {"enabled": False, "citations": True, "seeds": 1},
            }
        },
        llm=FakeLLM(),
        searcher=CitationSearcher(build_articles()[:1]),
        workdir=tmp_path,
    )

    result = orchestrator.run("引文追溯测试")

    assert [article.pmid for article in result.articles] == ["1", "88"]
    assert result.stats["citation_fetched"] == 1


def test_recursive_expansion_runs_multiple_rounds(tmp_path) -> None:
    class GrowingSearcher(FakeSearcher):
        def __init__(self, articles: list[Article]) -> None:
            super().__init__(articles)
            self.expand_calls = 0

        def expand_related(self, pmids: list[str], max_results: int = 10) -> list[Article]:
            self.expand_calls += 1
            return [
                Article(
                    pmid=str(9000 + self.expand_calls),
                    title=(
                        "Platelet aggregation after aspirin"
                        if self.expand_calls == 1
                        else "Pharmacokinetics of enteric aspirin"
                    ),
                    abstract="related",
                )
            ]

    orchestrator = Orchestrator(
        {
            "search": {
                "max_results_per_query": 3,
                "expand": {
                    "enabled": True,
                    "rounds": 2,
                    "seeds": 1,
                    "max_total": 10,
                },
            }
        },
        llm=FakeLLM(),
        searcher=GrowingSearcher(build_articles()[:1]),
        workdir=tmp_path,
    )

    result = orchestrator.run("递归扩展测试")

    assert [article.pmid for article in result.articles] == ["1", "9001", "9002"]
    assert result.stats["related_fetched"] == 2
    assert result.stats["expansion_rounds"] == 2


def test_extraction_failure_is_reported(tmp_path) -> None:
    class FailingLLM:
        def complete(self, messages: list[dict], **kwargs) -> str:
            raise RuntimeError("model down")

    orchestrator = Orchestrator(
        {"search": {"max_results_per_query": 3}},
        llm=FailingLLM(),
        searcher=FakeSearcher(build_articles()[:1]),
        workdir=tmp_path,
    )

    result = orchestrator.run("失败测试")

    assert result.stats["extraction_failures"] == 1
    assert result.report is not None
    assert "抽取失败" in result.report.markdown
    assert "model down" in result.report.markdown


def test_low_confidence_is_filtered(tmp_path) -> None:
    class LowConfidenceLLM(FakeLLM):
        def complete(self, messages: list[dict], **kwargs) -> str:
            return json.dumps(
                {"evidence": [{"claim": "阿司匹林可能降低风险", "confidence": 0.2}]},
                ensure_ascii=False,
            )

    orchestrator = Orchestrator(
        {
            "search": {"max_results_per_query": 3},
            "extraction": {"min_confidence": 0.5},
        },
        llm=LowConfidenceLLM(),
        searcher=FakeSearcher(build_articles()[:1]),
        workdir=tmp_path,
    )

    result = orchestrator.run("低置信度测试")

    assert result.evidence == []
    assert result.stats["low_confidence_filtered"] == 1
    assert result.filtered_low_confidence
    assert result.report is not None
    assert "低置信度未纳入 1 条" in result.report.markdown


def test_custom_extraction_prompt_is_used(tmp_path) -> None:
    prompt_file = tmp_path / "custom_prompt.md"
    prompt_file.write_text("CUSTOM {{TITLE}}", encoding="utf-8")
    seen: dict = {}

    class CaptureLLM(FakeLLM):
        def complete(self, messages: list[dict], **kwargs) -> str:
            seen["messages"] = messages
            return super().complete(messages, **kwargs)

    orchestrator = Orchestrator(
        {
            "search": {"max_results_per_query": 3},
            "extraction": {"prompt": str(prompt_file)},
        },
        llm=CaptureLLM(),
        searcher=FakeSearcher(build_articles()[:1]),
        workdir=tmp_path,
    )

    orchestrator.run("prompt test", ["q"])

    assert "CUSTOM" in seen["messages"][1]["content"]


def test_online_resolver_failure_marks_evidence_failed(tmp_path) -> None:
    orchestrator = Orchestrator(
        {"search": {"max_results_per_query": 3}},
        llm=FakeLLM(),
        searcher=FakeSearcher(build_articles()[:1]),
        workdir=tmp_path,
        resolver=lambda pmid, doi: False,
    )

    result = orchestrator.run("在线核查")

    assert result.verifications
    assert all(check.final_status is VerificationStatus.FAILED for check in result.verifications)
    assert any("在线校验失败" in issue for check in result.verifications for issue in check.issues)


def test_judge_rejection_marks_evidence_failed(tmp_path) -> None:
    orchestrator = Orchestrator(
        {"search": {"max_results_per_query": 3}},
        llm=FakeLLM(),
        searcher=FakeSearcher(build_articles()[:1]),
        workdir=tmp_path,
        judge=lambda item, article: False,
    )

    result = orchestrator.run("语义核查")

    assert result.verifications
    assert all(check.final_status is VerificationStatus.FAILED for check in result.verifications)
    assert any("不足以支持" in issue for check in result.verifications for issue in check.issues)
