"""进程内滑动窗口限流（演示用，纯内存，不依赖 Redis）。

配额与计数范围
- 默认共享配额 30 次 / 60 秒滑动窗口，按客户端 IP 分桶。
- 只计数 /api/ 前缀下的 POST/PUT/PATCH/DELETE；GET/HEAD/OPTIONS 与 /health 永不计数。
- 被拒（429）的请求不计入窗口，否则客户端重试会把窗口无限续期。
- 最多跟踪 MAX_TRACKED_KEYS=10000 个桶，超出时先清空桶、再淘汰最久未写入的桶。

环境变量
- RATE_LIMIT_PER_MIN    默认 30；0 表示关闭限流。
- RATE_LIMIT_WINDOW_SEC 默认 60；<=0 或非法值回退 60。
- TRUST_PROXY           默认 "0"；开启后按 X-Forwarded-For 最左一跳（其次 X-Real-IP）分桶。

配置解析时机
- RateLimiter(limit=..., window_sec=...) 显式传值 → pin，之后不再看 env（单测注入固定
  limit / 假时钟的场景不受环境变量干扰）。
- 未传值，或 configure(limit=None, window_sec=None) → env-driven：limit / window_sec
  属性与每次 check() 都重新解析 env。所以用例里 monkeypatch.setenv("RATE_LIMIT_PER_MIN",
  "3") 立即生效，不需要再调 reset()。
- reset() 只负责「回到 env-driven + 清空窗口」，不读死配置；每请求路径上只解析、不清窗口。
"""
from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from typing import NamedTuple

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

MAX_TRACKED_KEYS = 10000
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
TRUTHY = frozenset({"1", "true", "yes", "on"})


def _env_number(name: str, default: float) -> float:
    """读非负有限数；缺失/非法/负数/inf/nan 一律回退默认值。"""
    raw = os.environ.get(name)
    if raw is None:
        return float(default)
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(value) or value < 0:
        return float(default)
    return value


def env_limit() -> int:
    return int(_env_number("RATE_LIMIT_PER_MIN", 30))


def env_window() -> float:
    window = _env_number("RATE_LIMIT_WINDOW_SEC", 60.0)
    return window if window > 0 else 60.0


def trust_proxy() -> bool:
    return os.environ.get("TRUST_PROXY", "").strip().lower() in TRUTHY


def client_ip(request: Request) -> str:
    if trust_proxy():
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
        real = request.headers.get("x-real-ip", "").strip()
        if real:
            return real
    return request.client.host if request.client else "unknown"


def is_counted(method: str, path: str) -> bool:
    return method.upper() in WRITE_METHODS and path.startswith("/api/")


def _fmt_number(value: float) -> str:
    value = float(value)
    return str(int(value)) if value.is_integer() else str(value)


class Decision(NamedTuple):
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class RateLimiter:
    """线程安全的滑动窗口计数器。limit<=0 时永远放行。"""

    def __init__(self, limit=None, window_sec=None, *, clock=time.monotonic):
        self._clock = clock
        self._pinned_limit = None if limit is None else int(limit)
        self._pinned_window = None if window_sec is None else float(window_sec)
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    # ---- 配置解析（调用方需持锁）----
    def _resolve_limit(self) -> int:
        return self._pinned_limit if self._pinned_limit is not None else env_limit()

    def _resolve_window(self) -> float:
        return self._pinned_window if self._pinned_window is not None else env_window()

    @property
    def limit(self) -> int:
        with self._lock:
            return self._resolve_limit()

    @property
    def window_sec(self) -> float:
        with self._lock:
            return self._resolve_window()

    def configure(self, limit=None, window_sec=None) -> None:
        """传值 = pin；传 None = 该维度交回 env。不清空窗口。"""
        with self._lock:
            self._pinned_limit = None if limit is None else int(limit)
            self._pinned_window = None if window_sec is None else float(window_sec)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()

    # ---- 桶淘汰（调用方需持锁）----
    def _evict_if_needed(self) -> None:
        if len(self._hits) < MAX_TRACKED_KEYS:
            return
        for key in [k for k, hits in self._hits.items() if not hits]:
            del self._hits[key]
        if len(self._hits) < MAX_TRACKED_KEYS:
            return
        oldest = min(
            self._hits,
            key=lambda k: self._hits[k][-1] if self._hits[k] else float("-inf"),
        )
        self._hits.pop(oldest, None)

    def check(self, key: str) -> Decision:
        now = self._clock()
        with self._lock:
            limit = self._resolve_limit()
            window = self._resolve_window()
            if limit <= 0:
                return Decision(True, 0, 0, 0)

            hits = self._hits.get(key)
            if hits is None:
                self._evict_if_needed()
                hits = deque()
                self._hits[key] = hits

            cutoff = now - window
            while hits and hits[0] <= cutoff:
                hits.popleft()

            if len(hits) >= limit:
                # 被拒请求不入窗口；retry 至少 1 秒，避免 Retry-After: 0 打脸。
                retry = max(1, math.ceil(window - (now - hits[0])))
                return Decision(False, limit, 0, retry)

            hits.append(now)
            return Decision(True, limit, max(0, limit - len(hits)), 0)


_limiter = RateLimiter()


def get_limiter() -> RateLimiter:
    return _limiter


def reset() -> None:
    """回到 env-driven 并清空窗口。用例 autouse fixture 用。"""
    _limiter.configure()
    _limiter.clear()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter=None):
        super().__init__(app)
        self.limiter = limiter if limiter is not None else get_limiter()

    async def dispatch(self, request: Request, call_next):
        limiter = self.limiter
        limit = limiter.limit
        if limit <= 0 or not is_counted(request.method, request.url.path):
            return await call_next(request)

        decision = limiter.check(client_ip(request))
        window = limiter.window_sec
        headers = {
            "X-RateLimit-Limit": str(decision.limit),
            "X-RateLimit-Remaining": str(decision.remaining),
            "X-RateLimit-Window": _fmt_number(window),
        }

        if not decision.allowed:
            headers["Retry-After"] = str(decision.retry_after)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"写操作过于频繁：{_fmt_number(window)} 秒内最多 "
                        f"{decision.limit} 次，请在 {decision.retry_after} 秒后重试。"
                    ),
                    "retry_after": decision.retry_after,
                    "limit": decision.limit,
                    "window_sec": window,
                },
                headers=headers,
            )

        response = await call_next(request)
        for name, value in headers.items():
            response.headers[name] = value
        return response
