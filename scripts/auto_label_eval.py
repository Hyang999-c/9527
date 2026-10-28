"""用同一套严格判据自动预标：claim 的每个事实要素是否都在 quote 里。

注意：这是模型判定，不是人工金标准；只用于同一批次间的相对比较。
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from dotenv import load_dotenv

from aspirin_agent.llm_client import LLMClient

PROMPT = """判断 claim 是否被 quote 支持。

规则：
1. quote 必须支持 claim 的核心结果，以及 claim 中出现的剂量、时长、数值、机制、因果方向。
2. claim 用文献总体人群/背景作主语（例如“无糖尿病成人”）是允许的，前提是 quote 的结果与这个人群一致。
3. 如果 claim 的数值、剂量、机制或因果在 quote 中找不到，或者 quote 只覆盖了 claim 的一部分数值，判“不支持”。
4. 代词（该药、上述结果等）可以接受。
5. 不判断医学结论是否正确，只判断引文是否覆盖 claim。

claim: {claim}
quote: {quote}

只输出 JSON：{{"supported": true 或 false, "reason": "一句话"}}
"""


def parse_bool(raw: str) -> bool | None:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    value = data.get("supported")
    return value if isinstance(value, bool) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="自动预标评测批次")
    parser.add_argument("run_dir")
    args = parser.parse_args(argv)
    load_dotenv()

    run = Path(args.run_dir)
    path = run / "items.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
    fields = list(rows[0].keys())

    settings = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    llm = LLMClient.from_settings(
        {
            "llm": {
                "base_url": "https://api.deepseek.com/v1",
                "model": settings.get("model", "deepseek-chat"),
            }
        }
    )
    if llm is None:
        print("缺少 LLM_API_KEY")
        return 2

    labeled = 0
    for index, row in enumerate(rows, 1):
        if not row["quote"]:
            row["supported"] = "0"
            row["reviewer_note"] = "无可定位引句"
            continue
        raw = llm.complete(
            [
                {"role": "system", "content": "你是严格的引文核查员，只输出 JSON。"},
                {
                    "role": "user",
                    "content": PROMPT.format(claim=row["claim"], quote=row["quote"]),
                },
            ],
            temperature=0.0,
            max_tokens=200,
            json_mode=True,
        )
        verdict = parse_bool(raw)
        if verdict is None:
            row["supported"] = ""
            row["reviewer_note"] = "自动预标失败"
        else:
            row["supported"] = "1" if verdict else "0"
            row["reviewer_note"] = "auto-strict"
            labeled += 1
        row["quote_verbatim"] = "1" if row["locator"] != "none" else "0"
        print(f"{index}/{len(rows)} {row['item_id']} -> {row['supported'] or '?'}")

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    meta["labeler"] = "auto-strict（模型判定，非人工金标准）"
    meta["auto_labeled"] = labeled
    (run / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"labeled {labeled}/{len(rows)}")
    llm.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
