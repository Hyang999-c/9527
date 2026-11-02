"""命令行入口：aspirin-agent --question "..."。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from .llm_client import LLMClient
from .orchestrator import Orchestrator
from .utils.logging_utils import setup_logging


def load_settings(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_queries(path: str | Path) -> list[str]:
    path = Path(path)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    queries: list[str] = []
    for group in data.get("groups", []):
        queries.extend(group.get("queries", []))
    return queries


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aspirin-agent",
        description="阿司匹林文献检索、证据抽取与引用核查",
    )
    parser.add_argument("--question", required=True, help="研究问题，写入报告标题")
    parser.add_argument("--query", action="append", default=[], help="自定义检索式，可重复")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--queries-file", default="config/search_queries.yaml")
    parser.add_argument("--max-queries", type=int, default=6)
    parser.add_argument("--no-llm", action="store_true", help="只检索，不调用大模型")
    parser.add_argument("--no-expand", action="store_true", help="关闭相关文献扩展")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):  # 某些重定向环境不支持
                pass

    args = build_parser().parse_args(argv)
    setup_logging(args.log_level)

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # pragma: no cover - python-dotenv 是硬依赖，仅容错
        pass

    settings = load_settings(args.config)
    if args.no_expand:
        settings.setdefault("search", {}).setdefault("expand", {})["enabled"] = False
    queries = args.query or load_queries(args.queries_file)[: args.max_queries] or [args.question]
    llm = None if args.no_llm else LLMClient.from_settings(settings)

    result = Orchestrator(settings, llm=llm).run(args.question, queries)
    if result.report is not None:
        print(result.report.markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
