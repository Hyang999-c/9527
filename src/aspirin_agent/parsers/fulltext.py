"""PMC JATS XML 与 HTML 全文的章节提取。"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import ClassVar


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_pmc_xml(xml_text: str) -> dict[str, str]:
    """返回 {章节标题: 正文}；缺少 body 时返回空字典。"""
    if not xml_text.strip():
        return {}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}

    sections: dict[str, str] = {}
    for sec in root.findall(".//body//sec"):
        title_node = sec.find("title")
        title = _clean("".join(title_node.itertext())) if title_node is not None else "正文"
        paragraphs = [_clean("".join(p.itertext())) for p in sec.findall("p")]
        body = " ".join(p for p in paragraphs if p)
        if body:
            sections[title or "正文"] = body

    abstract = root.find(".//abstract")
    if abstract is not None:
        parts = [_clean("".join(p.itertext())) for p in abstract.findall(".//p")]
        text = " ".join(p for p in parts if p)
        if text:
            sections.setdefault("摘要", text)
    return sections


class _TextExtractor(HTMLParser):
    _BLOCK_TAGS: ClassVar[set[str]] = {
        "p",
        "div",
        "br",
        "li",
        "h1",
        "h2",
        "h3",
        "section",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(data)

    def get_text(self) -> str:
        return _clean(" ".join(self._parts))


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.get_text()
