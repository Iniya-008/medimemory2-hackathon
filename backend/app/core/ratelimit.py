"""Small in-memory per-user rate limiter (single instance; enough for a demo deployment)."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Depends, HTTPException

from app.core.deps import get_current_user
from app.models import User

_hits: dict[tuple[str, int], deque] = defaultdict(deque)
_lock = Lock()
ENABLED = True


def reset() -> None:
    with _lock:
        _hits.clear()


def limit(bucket: str, per_minute: int):
    def dep(user: User = Depends(get_current_user)) -> User:
        if not ENABLED:
            return user
        now = time.monotonic()
        with _lock:
            q = _hits[(bucket, user.id)]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= per_minute:
                raise HTTPException(429, "Too many requests. Please wait a moment and try again.")
            q.append(now)
        return user
    return dep
