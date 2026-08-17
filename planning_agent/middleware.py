from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque

from fastapi import Request
from redis import Redis
from starlette.responses import JSONResponse

from .observability import request_id_context


class RequestControlsMiddleware:
    def __init__(self, app, max_request_bytes: int, rate_limit_per_minute: int, redis_url: str):
        self.app = app
        self.max_request_bytes = max_request_bytes
        self.limit = rate_limit_per_minute
        self.redis = Redis.from_url(redis_url, socket_connect_timeout=0.2, socket_timeout=0.2)
        self.local: dict[str, deque[float]] = defaultdict(deque)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))[:100]
        token = request_id_context.set(request_id)
        try:
            length = int(request.headers.get("content-length", "0") or 0)
            if length > self.max_request_bytes:
                await JSONResponse({"detail": "Request body is too large"}, 413)(scope, receive, send)
                return
            if request.url.path.startswith("/api/") and not request.url.path.endswith("/status"):
                key = request.client.host if request.client else "unknown"
                if not self._allow(key):
                    await JSONResponse({"detail": "Rate limit exceeded"}, 429, headers={"Retry-After": "60"})(scope, receive, send)
                    return

            async def send_with_id(message):
                if message["type"] == "http.response.start":
                    message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
                await send(message)
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_context.reset(token)

    def _allow(self, key: str) -> bool:
        bucket = int(time.time() // 60)
        try:
            redis_key = f"rate:{key}:{bucket}"
            count = self.redis.incr(redis_key)
            if count == 1:
                self.redis.expire(redis_key, 61)
            return count <= self.limit
        except Exception:
            now = time.monotonic()
            entries = self.local[key]
            while entries and entries[0] < now - 60:
                entries.popleft()
            if len(entries) >= self.limit:
                return False
            entries.append(now)
            return True
