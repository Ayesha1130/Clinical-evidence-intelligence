"""
In-process rate limiting, keyed per authenticated user.

Same design rationale as app/core/event_bus.py: this targets a
single-instance deployment (Render/Railway), so an in-memory sliding
window is the correct amount of infrastructure — no Redis needed. Applied
to the genuinely expensive endpoints (starting a research pipeline,
Ask This Paper, manual reindexing) that each trigger multiple real LLM/
embedding/external-API calls.
"""
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, status

from app.core.security import CurrentUser, get_current_user


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str, max_requests: int, window_seconds: float) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= max_requests:
            retry_after = max(0.0, window_seconds - (now - hits[0]))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Try again in {retry_after:.0f} seconds.",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
        hits.append(now)

    def reset(self) -> None:
        """Test-only helper — production code never needs to clear this."""
        self._hits.clear()


rate_limiter = RateLimiter()


def rate_limit(scope: str, max_requests: int, window_seconds: float):
    """Returns a FastAPI dependency that rate-limits by (scope, user_id).
    `scope` distinguishes independent limits for different endpoints (e.g.
    'start' vs 'ask') so hitting one doesn't consume the other's budget.
    Runs after auth (depends on get_current_user), so an unauthenticated
    request is rejected by auth before it ever reaches the limiter."""

    def dependency(user: CurrentUser = Depends(get_current_user)) -> None:
        rate_limiter.check(f"{scope}:{user.id}", max_requests, window_seconds)

    return dependency
