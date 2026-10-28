"""项目内可预期的错误类型；工具失败时抛这些，不返回伪造数据。"""

from __future__ import annotations


class AspirinAgentError(Exception):
    """项目内错误的基类。"""


class PubMedError(AspirinAgentError):
    """检索、取回或响应解析失败。"""


class PubMedParseError(PubMedError):
    """PubMed XML 无法解析。"""


class LLMError(AspirinAgentError):
    """模型调用失败或返回结构异常。"""


class EvidenceExtractionError(AspirinAgentError):
    """模型输出无法解析为结构化证据。"""
