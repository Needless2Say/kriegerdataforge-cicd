"""Unit tests for the shared retry/backoff HTTP session (common/http.py).

Regression guard: distribute_kit.py and rotate_secret.py both fan out GitHub/Vercel
API calls; a single transient 502/503/429 or DNS blip must be retried, not abort a
whole target (the 2026-07 distribute check errored on two 502s + one DNS failure).
"""

from __future__ import annotations

import requests

from common import http


def test_build_session_returns_session_with_retry_adapter():
    session = http.build_session()
    assert isinstance(session, requests.Session)
    for scheme in ("https://", "http://"):
        retry = session.get_adapter(scheme).max_retries
        assert retry.total and retry.total >= 3
        assert retry.connect and retry.connect >= 1  # DNS / connection blips
        assert retry.backoff_factor > 0  # exponential backoff, not a hot loop
        for code in (429, 500, 502, 503, 504):
            assert code in retry.status_forcelist
        # 404 (missing) / 422 (conflict/exists) are meaningful, never transient.
        assert 404 not in retry.status_forcelist
        assert 422 not in retry.status_forcelist


def test_build_session_retries_idempotent_methods_only():
    # GET/PUT are safe to replay; POST/DELETE/PATCH must NOT be status-retried
    # (no duplicate PRs / tokens, no double-delete after a 502-that-succeeded).
    retry = http.build_session().get_adapter("https://api.github.com").max_retries
    assert "GET" in retry.allowed_methods
    assert "PUT" in retry.allowed_methods
    for method in ("POST", "DELETE", "PATCH"):
        assert method not in retry.allowed_methods


def test_build_session_returns_independent_instances():
    # Each engine builds its own session — no shared mutable state across scripts.
    assert http.build_session() is not http.build_session()
