"""流水线编排：检索 -> 去重 -> 全文 -> 抽取 -> 核查 -> 成稿。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .schemas import ExtractionBatch, PipelineResult
from .tools.article_fetch import enrich_articles
from .tools.citation_verify import LLMJudge, PubMedResolver, verify_citations
from .tools.csv_export import export_csvs
from .tools.deduplication import deduplicate_records
from .tools.evidence_extract import extract_batch
from .tools.pubmed_search import PubMedSearcher
from .tools.report_builder import build_report
from .utils.logging_utils import get_logger

logger = get_logger(__name__)

DEFAULT_TITLE = "阿司匹林研究证据简报"


class Orchestrator:
    """依赖可注入：searcher 与 llm 都能换成假实现，端到端测试不联网。"""

    def __init__(
        self,
        settings: dict | None = None,
        llm=None,
        searcher=None,
        workdir: str | Path | None = None,
        resolver=None,
        judge=None,
    ) -> None:
        self.settings = settings or {}
        paths = self.settings.get("paths", {})
        self.root = Path(workdir or paths.get("base_dir", ".")).resolve()
        self.paths = {
            "raw": self.root / paths.get("raw", "data/raw"),
            "processed": self.root / paths.get("processed", "data/processed"),
            "exports": self.root / paths.get("exports", "data/exports"),
            "reports": self.root / paths.get("reports", "reports"),
        }
        self.max_results = int(self.settings.get("search", {}).get("max_results_per_query", 20))
        self.llm = llm
        self.searcher = searcher or PubMedSearcher(self.settings, raw_dir=self.paths["raw"])
        self.resolver = resolver
        self.judge = judge

    def _fetch_enabled(self) -> bool:
        return bool(self.settings.get("fetch", {}).get("fulltext", False))

    def run(self, question: str, queries: list[str] | None = None) -> PipelineResult:
        terms = queries or [question]
        found = []
        for term in terms:
            try:
                found.extend(self.searcher.search(term, self.max_results))
            except Exception as exc:  # noqa: BLE001 - 单条检索式失败不中断全流程
                logger.error("检索失败 %r: %s", term, exc)

        unique = deduplicate_records(found)
        logger.info("检索 %d 篇，去重后 %d 篇", len(found), len(unique))

        if self._fetch_enabled():
            limit = self.settings.get("fetch", {}).get("max_articles")
            unique = enrich_articles(unique, limit=limit, searcher=self.searcher)

        extraction = self.settings.get("extraction", {})
        prompt_template = None
        prompt_path = extraction.get("prompt")
        if prompt_path:
            path = Path(prompt_path)
            if not path.is_absolute():
                path = self.root / path
            if path.exists():
                prompt_template = path.read_text(encoding="utf-8")
            else:
                logger.warning("抽取提示词不存在，回退默认: %s", path)

        batch = (
            extract_batch(
                unique,
                question,
                self.llm,
                batch_size=int(extraction.get("batch_size", 5)),
                temperature=float(extraction.get("temperature", 0.1)),
                max_tokens=int(extraction.get("max_tokens", 4000)),
                prompt_template=prompt_template,
            )
            if self.llm
            else ExtractionBatch()
        )
        evidence = batch.evidence

        verification_config = self.settings.get("verification", {})
        resolver = self.resolver
        if resolver is None and verification_config.get("online_check"):
            resolver = PubMedResolver(limiter=getattr(self.searcher, "limiter", None))
        judge = self.judge
        if judge is None and verification_config.get("semantic_judge") and self.llm is not None:
            judge = LLMJudge(self.llm)

        verifications = verify_citations(
            evidence, unique, resolver=resolver, judge=judge
        )
        title = self.settings.get("report", {}).get("title", DEFAULT_TITLE)
        report = build_report(unique, evidence, verifications, question=question, title=title)

        result = PipelineResult(
            question=question,
            queries=terms,
            articles=unique,
            evidence=evidence,
            verifications=verifications,
            extraction_failures=batch.failures,
            report=report,
            stats={
                "articles_found": len(found),
                "articles_unique": len(unique),
                "duplicates_removed": len(found) - len(unique),
                "evidence_items": len(evidence),
                "extraction_failures": len(batch.failures),
                "verified_passed": sum(
                    1 for check in verifications if check.final_status.value == "passed"
                ),
                "verification_issues": sum(1 for check in verifications if check.issues),
            },
        )
        self._persist(result)
        return result

    def _persist(self, result: PipelineResult) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for directory in self.paths.values():
            directory.mkdir(parents=True, exist_ok=True)

        articles_path = self.paths["raw"] / f"articles_{timestamp}.json"
        articles_path.write_text(
            json.dumps(
                [article.model_dump(mode="json") for article in result.articles],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        evidence_path = self.paths["processed"] / f"evidence_{timestamp}.json"
        evidence_path.write_text(
            json.dumps(
                {
                    "evidence": [item.model_dump(mode="json") for item in result.evidence],
                    "verifications": [
                        check.model_dump(mode="json") for check in result.verifications
                    ],
                    "extraction_failures": [
                        failure.model_dump(mode="json")
                        for failure in result.extraction_failures
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        if result.report is not None:
            (self.paths["reports"] / f"report_{timestamp}.md").write_text(
                result.report.markdown, encoding="utf-8"
            )

        csv_paths = export_csvs(
            result.articles,
            result.evidence,
            result.verifications,
            self.paths["exports"],
            timestamp,
        )
        logger.info("CSV 已导出：%s", "、".join(path.name for path in csv_paths.values()))
        logger.info("产物已写入 %s", self.root)
