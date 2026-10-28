"""读取人工标注，计算抽取 precision 与 quote 逐字率。"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

LABELS = {"1": True, "0": False, "true": True, "false": False, "yes": True, "no": False}


def parse_label(value: str) -> bool | None:
    text = (value or "").strip().lower()
    return LABELS.get(text)


def read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def ratio(hit: int, total: int) -> str:
    return f"{hit}/{total}（{hit / total:.0%}）" if total else "0/0（—）"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="计算评测指标")
    parser.add_argument("run_dir")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir)
    rows = read_rows(run_dir / "items.csv")
    labeled = [row for row in rows if parse_label(row["supported"]) is not None]

    if not labeled:
        print(f"共 {len(rows)} 条，尚未标注。请填写 items.csv 的 supported 列（1/0）。")
        return 1

    supported = sum(1 for row in labeled if parse_label(row["supported"]))
    verbatim_rows = [row for row in rows if parse_label(row["quote_verbatim"]) is not None]
    verbatim = sum(1 for row in verbatim_rows if parse_label(row["quote_verbatim"]))

    lines = [
        "# 评测结果",
        "",
        f"- 批次：{run_dir.name}",
        f"- 已标注：{len(labeled)} / {len(rows)} 条",
        f"- 支持率（precision 近似）：{ratio(supported, len(labeled))}",
        f"- quote 逐字率：{ratio(verbatim, len(verbatim_rows)) if verbatim_rows else '未标注'}",
        "",
        "## 按研究类型",
        "",
        "| stratum | 支持 / 已标注 |",
        "| --- | --- |",
    ]
    by_stratum: dict[str, list[dict]] = defaultdict(list)
    for row in labeled:
        by_stratum[row["stratum"]].append(row)
    for stratum, group in sorted(by_stratum.items()):
        hit = sum(1 for row in group if parse_label(row["supported"]))
        lines.append(f"| {stratum} | {ratio(hit, len(group))} |")

    lines += ["", "## 按陈述类型", "", "| statement_type | 支持 / 已标注 |", "| --- | --- |"]
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in labeled:
        by_type[row["statement_type"]].append(row)
    for statement_type, group in sorted(by_type.items()):
        hit = sum(1 for row in group if parse_label(row["supported"]))
        lines.append(f"| {statement_type} | {ratio(hit, len(group))} |")

    lines += ["", "## 未通过样本", ""]
    rejected = [row for row in labeled if not parse_label(row["supported"])]
    if not rejected:
        lines.append("（无）")
    for row in rejected:
        lines.append(
            f"- {row['item_id']}（{row['stratum']}）：{row['claim']}"
            f"\n  - quote：{row['quote']}"
            f"\n  - 备注：{row['reviewer_note'] or '无'}"
        )

    report = "\n".join(lines) + "\n"
    output = Path(args.out) if args.out else run_dir / "score.md"
    output.write_text(report, encoding="utf-8")
    print(report)
    print(f"已写入 {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
