"""简单限速器：保证相邻请求间隔不小于 1/速率 秒。

时钟与 sleep 可注入，测试不需要真的等待。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        max_per_second: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_per_second <= 0:
            raise ValueError("max_per_second 必须大于 0")
        self.max_per_second = max_per_second
        self.min_interval = 1.0 / max_per_second
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> float:
        """阻塞到允许下一次请求，返回实际睡眠秒数（测试用）。"""
        with self._lock:
            slept = 0.0
            now = self._clock()
            if self._last is not None:
                delay = self._last + self.min_interval - now
                if delay > 0:
                    self._sleep(delay)
                    slept = delay
                    now = self._clock()
            self._last = now
            return slept
