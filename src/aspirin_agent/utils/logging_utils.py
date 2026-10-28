"""统一日志配置：有 rich 用 rich，没有就退回标准输出。"""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def get_logger(name: str = "aspirin_agent") -> logging.Logger:
    return logging.getLogger(name)


def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    handlers: list[logging.Handler] = []
    try:
        from rich.logging import RichHandler

        handlers.append(RichHandler(show_path=False, rich_tracebacks=True))
    except ImportError:  # pragma: no cover - rich 是可选依赖
        handlers.append(logging.StreamHandler(sys.stderr))
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=_FORMAT,
        handlers=handlers,
        force=True,
    )
