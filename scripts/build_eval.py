"""构建评测批次：抓文献 -> 抽证据 -> 生成人工标注表。"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from aspirin_agent.llm_client import LLMClient
from aspirin_agent.tools.article_fetch import enrich_articles
from aspirin_agent.tools.citation_verify import verify_citations
from aspirin_agent.tools.evidence_extract import extract_batch
from aspirin_agent.tools.pubmed_search import PubMedSearcher

ITEM_FIELDS = [
    "item_id",
    "stratum",
    "pmid",
    "claim",
    "statement_type",
    "evidence_type",
    "study_model",
    "locator",
    "quote",
    "confidence",
    "auto_status",
    "auto_issues",
    "supported",
    "quote_verbatim",
    "reviewer_note",
]

ARTICLE_FIELDS = [
    "pmid",
    "stratum",
    "title",
    "year",
    "journal",
    "publication_type",
    "fulltext_status",
    "doi",
]


def load_gold(path: Path) -> tuple[str, list[dict]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    question = data.get("question") or "阿司匹林的作用机制与药理学证据是什么？"
    articles = data.get("articles") or []
    if not articles:
        raise ValueError("gold_set.yaml 里没有 articles")
    return question, articles


def write_review(
    path: Path,
    question: str,
    article_rows: list[dict],
    item_rows: list[dict],
) -> None:
    grouped: dict[str, list[dict]] = {}
    for item in item_rows:
        grouped.setdefault(item["pmid"], []).append(item)

    lines = [
        "# 人工标注表",
        "",
        f"> {question}",
        "",
        "规则：quote 必须支持 claim 的核心结果，以及其中出现的剂量、数值、机制、因果；文献总体人群可作背景。",
        "先在 items.csv 填 supported / quote_verbatim（1/0），再跑 score_eval.py。",
        "",
    ]
    for article in article_rows:
        lines += [
            f"## PMID {article['pmid']} — {article['stratum']}",
            f"{article['title']}（{article['year']} · {article['journal']}）",
            "",
        ]
        for item in grouped.get(article["pmid"], []):
            lines += [
                f"### {item['item_id']}",
                f"- claim：{item['claim']}",
                f"- quote：{item['quote'] or '（未提供）'}",
                f"- 自动状态：{item['auto_status']}",
                "- [ ] 支持　[ ] 不支持",
                "",
            ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建评测批次")
    parser.add_argument("--gold", default="eval/gold_set.yaml")
    parser.add_argument("--settings", default="config/settings.yaml")
    parser.add_argument("--out", default="eval/runs")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-fulltext", action="store_true")
    parser.add_argument("--prompt", default=None, help="自定义抽取提示词路径")
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    args = parser.parse_args(argv)
    load_dotenv()

    question, gold_articles = load_gold(Path(args.gold))
    if args.limit:
        gold_articles = gold_articles[: args.limit]
    strata = {str(item["pmid"]): item.get("stratum", "unknown") for item in gold_articles}
    pmids = list(strata)

    settings = yaml.safe_load(Path(args.settings).read_text(encoding="utf-8")) or {}
    llm = LLMClient.from_settings(settings)
    if llm is None:
        print("缺少 LLM_API_KEY，无法构建评测批次")
        return 2

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.out) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    searcher = PubMedSearcher(settings, raw_dir=run_dir / "raw")
    articles = searcher.fetch_by_pmids(pmids)
    if not args.no_fulltext:
        max_articles = int(settings.get("fetch", {}).get("max_articles", 40))
        articles = enrich_articles(articles, searcher=searcher, limit=max_articles)

    prompt_template = (
        Path(args.prompt).read_text(encoding="utf-8") if args.prompt else None
    )
    extraction = settings.get("extraction", {})
    temperature = (
        args.temperature
        if args.temperature is not None
        else float(extraction.get("temperature", 0.1))
    )
    max_tokens = (
        args.max_tokens
        if args.max_tokens is not None
        else int(extraction.get("max_tokens", 4000))
    )
    batch = extract_batch(
        articles,
        question,
        llm,
        batch_size=int(extraction.get("batch_size", 5)),
        temperature=temperature,
        max_tokens=max_tokens,
        prompt_template=prompt_template,
    )
    checks = verify_citations(batch.evidence, articles)
    check_by_id = {check.evidence_id: check for check in checks}

    item_rows = []
    for item in batch.evidence:
        check = check_by_id.get(item.evidence_id)
        item_rows.append(
            {
                "item_id": item.evidence_id,
                "stratum": strata.get(item.pmid, "unknown"),
                "pmid": item.pmid,
                "claim": item.claim,
                "statement_type": item.statement_type.value,
                "evidence_type": item.evidence_type.value,
                "study_model": item.study_model.value,
                "locator": item.source_location.locator,
                "quote": item.source_location.quote or "",
                "confidence": item.confidence,
                "auto_status": check.final_status.value if check else "pending",
                "auto_issues": "；".join(check.issues) if check else "",
                "supported": "",
                "quote_verbatim": "",
                "reviewer_note": "",
            }
        )

    article_rows = [
        {
            "pmid": article.pmid,
            "stratum": strata.get(article.pmid, "unknown"),
            "title": article.title,
            "year": article.year or "",
            "journal": article.journal or "",
            "publication_type": article.publication_type.value,
            "fulltext_status": article.fulltext_status.value,
            "doi": article.doi or "",
        }
        for article in articles
    ]

    write_csv(run_dir / "items.csv", ITEM_FIELDS, item_rows)
    write_csv(run_dir / "articles.csv", ARTICLE_FIELDS, article_rows)
    write_review(run_dir / "review.md", question, article_rows, item_rows)

    meta = {
        "run_id": run_id,
        "question": question,
        "model": llm.model,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "requested_pmids": pmids,
        "articles": len(articles),
        "evidence": len(item_rows),
        "extraction_failures": [failure.model_dump() for failure in batch.failures],
        "fulltext": not args.no_fulltext,
        "prompt": args.prompt or "prompts/extract_evidence.md",
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"run: {run_dir}")
    print(f"articles: {len(articles)} | evidence: {len(item_rows)} | failures: {len(batch.failures)}")
    print("标注表: items.csv（supported / quote_verbatim 列留空待填）")
    llm.close()
    searcher.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
