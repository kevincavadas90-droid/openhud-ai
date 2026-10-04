"""Shared test fixtures.

The login rate limiter is an in-memory singleton: across many API tests it
would eventually return 429 for the shared "testclient" key. Reset it between
tests so each test starts from a clean slate (this does not affect production,
where the window is real time).
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    from openhud.web import ratelimit

    for limiter in (
        ratelimit.login_limiter,
        ratelimit.chat_limiter,
        ratelimit.register_limiter,
        ratelimit.reset_limiter,
        ratelimit.account_limiter,
    ):
        limiter._hits.clear()
    yield
    for limiter in (
        ratelimit.login_limiter,
        ratelimit.chat_limiter,
        ratelimit.register_limiter,
        ratelimit.reset_limiter,
        ratelimit.account_limiter,
    ):
        limiter._hits.clear()
