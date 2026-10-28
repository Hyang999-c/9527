"""OpenAI 兼容接口的最小客户端（DeepSeek / OpenAI 均可）。

- 供应商细节锁在本模块，业务层只依赖 complete()
- 超时、有限重试、限速由配置控制；429/5xx 指数退避
- 部分供应商不支持 response_format，遇到 400 自动退回普通 JSON 提示
"""

from __future__ import annotations

import os
import time

import httpx

from .errors import LLMError
from .utils.logging_utils import get_logger

logger = get_logger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class _JSONModeUnsupported(Exception):
    """供应商拒绝 response_format 时内部使用。"""


class LLMClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
        timeout: float = 90.0,
        retries: int = 3,
        backoff: float = 1.0,
        client: httpx.Client | None = None,
        sleep=time.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("api_key 不能为空")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.retries = max(1, retries)
        self.backoff = max(0.0, backoff)
        self._sleep = sleep
        self._client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    @classmethod
    def from_settings(
        cls,
        settings: dict | None = None,
        api_key: str | None = None,
    ) -> LLMClient | None:
        """没有密钥时返回 None，让流水线降级为纯检索模式。"""
        config = (settings or {}).get("llm", {})
        key = api_key or os.getenv("LLM_API_KEY")
        if not key:
            logger.warning("未配置 LLM_API_KEY，跳过证据抽取")
            return None
        return cls(
            api_key=key,
            base_url=os.getenv("LLM_BASE_URL") or config.get("base_url", "https://api.deepseek.com/v1"),
            model=os.getenv("LLM_MODEL") or config.get("model", "deepseek-chat"),
            timeout=float(config.get("timeout_seconds", 90)),
            retries=int(config.get("max_retries", 3)),
            backoff=float(config.get("retry_backoff_seconds", 1.0)),
        )

    def _payload(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _post(self, payload: dict) -> dict:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        last_error: Exception | None = None

        for attempt in range(1, self.retries + 1):
            try:
                response = self._client.post(url, json=payload, headers=headers, timeout=self.timeout)
                if response.status_code == 400 and "response_format" in payload:
                    raise _JSONModeUnsupported(response.text)
                response.raise_for_status()
                return response.json()
            except _JSONModeUnsupported:
                raise
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status not in RETRYABLE_STATUS:
                    raise LLMError(f"模型接口返回 HTTP {status}: {exc.response.text[:200]}") from exc
                last_error = exc
            except httpx.HTTPError as exc:
                last_error = exc

            if attempt < self.retries:
                delay = min(self.backoff * (2 ** (attempt - 1)), 10.0)
                logger.warning("模型调用第 %d 次失败，%.1fs 后重试：%s", attempt, delay, last_error)
                self._sleep(delay)

        raise LLMError(f"模型调用失败（已重试 {self.retries} 次）: {last_error}") from last_error

    def complete(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 2000,
        json_mode: bool = True,
    ) -> str:
        payload = self._payload(messages, temperature, max_tokens, json_mode)
        try:
            data = self._post(payload)
        except _JSONModeUnsupported:
            logger.warning("当前模型不支持 response_format，退回普通 JSON 提示")
            payload.pop("response_format", None)
            data = self._post(payload)

        usage = data.get("usage") or {}
        if usage:
            logger.info(
                "模型用量：prompt=%s completion=%s",
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
            )

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"模型返回格式异常: {str(data)[:200]}") from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMError("模型返回了空内容")
        return content
