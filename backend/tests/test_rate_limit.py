"""
Pure unit tests for the sliding-window rate limiter.
"""
import time

import pytest
from fastapi import HTTPException

from app.core.rate_limit import RateLimiter


def test_allows_requests_under_the_limit():
    limiter = RateLimiter()
    for _ in range(5):
        limiter.check("user-1", max_requests=5, window_seconds=60.0)


def test_blocks_requests_over_the_limit():
    limiter = RateLimiter()
    for _ in range(5):
        limiter.check("user-1", max_requests=5, window_seconds=60.0)
    with pytest.raises(HTTPException) as exc_info:
        limiter.check("user-1", max_requests=5, window_seconds=60.0)
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


def test_different_keys_have_independent_limits():
    limiter = RateLimiter()
    for _ in range(5):
        limiter.check("user-1", max_requests=5, window_seconds=60.0)
    limiter.check("user-2", max_requests=5, window_seconds=60.0)


def test_different_scopes_for_same_user_are_independent():
    limiter = RateLimiter()
    for _ in range(5):
        limiter.check("start:user-1", max_requests=5, window_seconds=60.0)
    limiter.check("ask:user-1", max_requests=5, window_seconds=60.0)


def test_old_hits_expire_out_of_the_window():
    limiter = RateLimiter()
    limiter.check("user-1", max_requests=1, window_seconds=0.05)
    time.sleep(0.1)
    limiter.check("user-1", max_requests=1, window_seconds=0.05)


def test_reset_clears_all_state():
    limiter = RateLimiter()
    limiter.check("user-1", max_requests=1, window_seconds=60.0)
    limiter.reset()
    limiter.check("user-1", max_requests=1, window_seconds=60.0)
