"""网络重试：只包裹幂等的 GET/POST 调用。"""

from __future__ import annotations

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

RETRYABLE = (httpx.TimeoutException, httpx.TransportError)


def http_retry(attempts: int = 3, min_wait: float = 1.0, max_wait: float = 10.0):
    """指数退避重试装饰器；HTTP 4xx/5xx 不重试，交给调用方判断。"""
    return retry(
        reraise=True,
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=min_wait, min=min_wait, max=max_wait),
        retry=retry_if_exception_type(RETRYABLE),
    )
