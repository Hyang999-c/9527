"""召回评测：人工金标里的关键结论，有没有被抽出的证据覆盖。"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import yaml
from dotenv import load_dotenv

from aspirin_agent.llm_client import LLMClient

PROMPT = """判断候选证据（可以多条组合）是否覆盖了“关键结论”的核心含义。

关键结论：{{CLAIM}}

候选证据：
{{CANDIDATES}}

规则：
1. 覆盖指核心发现、数值、方向一致，不要求措辞相同。
2. 候选只覆盖结论的一部分，判 false。
3. 可以多选；若需要多条证据组合才能覆盖，也判 covered=true 并列出组合。
4. 没有可覆盖的条目时 covered=false，evidence_ids 为空。

只输出 JSON：{"covered": true 或 false, "evidence_ids": ["..."], "reason": "一句话"}
"""


def parse_object(raw: str) -> dict:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="召回评测")
    parser.add_argument("run_dir")
    parser.add_argument("--gold", default="eval/recall_gold.yaml")
    parser.add_argument("--settings", default="config/settings.yaml")
    args = parser.parse_args(argv)
    load_dotenv()

    run = Path(args.run_dir)
    rows = list(csv.DictReader((run / "items.csv").open(encoding="utf-8-sig", newline="")))
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["pmid"], []).append(row)

    gold = yaml.safe_load(Path(args.gold).read_text(encoding="utf-8")) or {}
    settings = yaml.safe_load(Path(args.settings).read_text(encoding="utf-8")) or {}
    llm = LLMClient.from_settings(settings)
    if llm is None:
        print("缺少 LLM_API_KEY")
        return 2

    results = []
    for article in gold.get("articles", []):
        pmid = str(article["pmid"])
        candidates = grouped.get(pmid, [])
        numbered = "\n".join(f"[{row['item_id']}] {row['claim']}" for row in candidates)
        claims = [
            claim
            for claim in article.get("claims", [])
            if claim.get("kind", "finding") != "method"
        ]
        for claim in claims:
            if not candidates:
                results.append(
                    {
                        "pmid": pmid,
                        "claim_id": claim["id"],
                        "claim": claim["text"],
                        "covered": False,
                        "evidence_ids": [],
                        "reason": "无候选证据",
                    }
                )
                continue

            prompt = (
                PROMPT.replace("{{CLAIM}}", claim["text"])
                .replace("{{CANDIDATES}}", numbered)
            )
            raw = llm.complete(
                [
                    {"role": "system", "content": "你是严格的证据覆盖核查员，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=400,
                json_mode=True,
            )
            data = parse_object(raw)
            covered = data.get("covered") is True
            ids = data.get("evidence_ids") if isinstance(data.get("evidence_ids"), list) else []
            results.append(
                {
                    "pmid": pmid,
                    "claim_id": claim["id"],
                    "claim": claim["text"],
                    "covered": covered,
                    "evidence_ids": [str(item) for item in ids],
                    "reason": str(data.get("reason", ""))[:200],
                }
            )
            print(f"{claim['id']} -> {'covered' if covered else 'MISS'}")

    covered_count = sum(1 for item in results if item["covered"])
    total = len(results)

    lines = [
        "# 召回评测",
        "",
        f"- 批次：{run.name}",
        f"- 关键结论覆盖：{covered_count}/{total}（{covered_count / total:.0%}）" if total else "- 无关键结论",
        "",
        "## 按文献",
        "",
        "| PMID | 覆盖 |",
        "| --- | --- |",
    ]
    by_pmid: dict[str, list[dict]] = {}
    for item in results:
        by_pmid.setdefault(item["pmid"], []).append(item)
    for pmid, group in sorted(by_pmid.items()):
        hit = sum(1 for item in group if item["covered"])
        lines.append(f"| {pmid} | {hit}/{len(group)} |")

    lines += ["", "## 未覆盖", ""]
    misses = [item for item in results if not item["covered"]]
    if not misses:
        lines.append("（无）")
    for item in misses:
        lines.append(f"- {item['claim_id']}（{item['pmid']}）：{item['claim']}")
        lines.append(f"  - 原因：{item['reason'] or '未说明'}")

    report = "\n".join(lines) + "\n"
    (run / "recall.md").write_text(report, encoding="utf-8")
    (run / "recall.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(report)
    print(f"已写入 {run / 'recall.md'}")
    llm.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
