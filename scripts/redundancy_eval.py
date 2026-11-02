"""冗余评测：同一文献内，claim 近似重复的比例。"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path


def normalize(text: str) -> str:
    return re.sub(r"[\s，。；、,.!?！？：:（）()\[\]]+", "", text.lower())


def numbers(text: str) -> list[str]:
    return sorted(re.findall(r"\d+(?:[.,]\d+)?", text))


def masked(text: str) -> str:
    return normalize(re.sub(r"\d+(?:[.,]\d+)?", "#", text))


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, masked(left), masked(right)).ratio()


def is_duplicate(left: str, right: str, threshold: float) -> bool:
    # 数字不同 = 不同结果（如 81mg 97% vs 325mg 96%），不算重复
    if numbers(left) != numbers(right):
        return False
    return similarity(left, right) >= threshold


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, index: int) -> int:
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def union(self, left: int, right: int) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="claim 冗余评测")
    parser.add_argument("run_dir")
    parser.add_argument("--threshold", type=float, default=0.85)
    args = parser.parse_args(argv)

    run = Path(args.run_dir)
    rows = list(csv.DictReader((run / "items.csv").open(encoding="utf-8-sig", newline="")))
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["pmid"]].append(row)

    total = 0
    redundant = 0
    per_article = []
    examples = []

    for pmid, items in grouped.items():
        total += len(items)
        union = UnionFind(len(items))
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                score = similarity(items[i]["claim"], items[j]["claim"])
                if is_duplicate(items[i]["claim"], items[j]["claim"], args.threshold):
                    union.union(i, j)
                    if len(examples) < 15:
                        examples.append(
                            {
                                "pmid": pmid,
                                "a": items[i]["claim"],
                                "b": items[j]["claim"],
                                "similarity": round(score, 3),
                            }
                        )
        clusters = {union.find(i) for i in range(len(items))}
        duplicates = len(items) - len(clusters)
        redundant += duplicates
        per_article.append(
            {
                "pmid": pmid,
                "items": len(items),
                "clusters": len(clusters),
                "redundant": duplicates,
            }
        )

    rate = redundant / total if total else 0.0
    lines = [
        "# 冗余评测",
        "",
        f"- 批次：{run.name}",
        f"- 阈值：{args.threshold}",
        f"- 证据数：{total}",
        f"- 近似重复：{redundant}（{rate:.0%}）",
        "",
        "## 按文献",
        "",
        "| PMID | 条目 | 聚类 | 冗余 |",
        "| --- | --- | --- | --- |",
    ]
    for row in sorted(per_article, key=lambda item: -item["redundant"]):
        lines.append(
            f"| {row['pmid']} | {row['items']} | {row['clusters']} | {row['redundant']} |"
        )

    lines += ["", "## 近似重复示例", ""]
    if not examples:
        lines.append("（无）")
    for example in examples:
        lines.append(f"- {example['pmid']}（{example['similarity']}）")
        lines.append(f"  - A：{example['a']}")
        lines.append(f"  - B：{example['b']}")

    report = "\n".join(lines) + "\n"
    (run / "redundancy.md").write_text(report, encoding="utf-8")
    (run / "redundancy.json").write_text(
        json.dumps({"threshold": args.threshold, "total": total, "redundant": redundant,
                    "per_article": per_article, "examples": examples},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
