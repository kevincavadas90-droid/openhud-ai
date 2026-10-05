"""Shared test fixtures.

The login rate limiter is an in-memory singleton: across many API tests it
would eventually return 429 for the shared "testclient" key. Reset it between
tests so each test starts from a clean slate (this does not affect production,
where the window is real time).
"""
from __future__ import annotations

import os

import pytest

# The suite must be hermetic: a DATABASE_URL exported in the developer's shell
# (e.g. to point at a production Postgres) would otherwise make SQLite-specific
# tests run against Postgres. Drop it before any test module imports the app.
for _var in ("DATABASE_URL", "OPENHUD_DATABASE_URL"):
    os.environ.pop(_var, None)


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
