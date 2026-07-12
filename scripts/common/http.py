"""Shared HTTP session with retry/backoff for the CI-plane ops engines.

The kit-distribute (`distribute_kit.py`) and secret-rotation (`rotate_secret.py`)
engines fan GitHub — and, for rotation, Vercel — API calls across many repos /
projects in one run. A single transient failure on any one call (a `502`/`503`
Bad Gateway, a `429` rate-limit, or a momentary DNS / connection blip) would
otherwise abort a whole target mid-run: a `check` reports ERROR, a `distribute`
leaves a repo un-synced, a rotation strands a secret half-written. This builds a
`requests.Session` that retries those transient failures with exponential backoff.

Retries are limited to **idempotent** methods (`GET`/`PUT`):
  - GET  — drift/public-key/list reads; always safe to replay.
  - PUT  — the Contents-API file write and the Actions/Environment secret write
           are upserts (they carry the target sha / encrypted value), so replaying
           is safe, not duplicative.
`POST`/`DELETE`/`PATCH` (create-branch, create-PR, create-/delete-token, delete-secret,
patch-env-var) are deliberately EXCLUDED from status/read retries, so a `502` that
GitHub/Vercel *already processed* can't create a duplicate ref/PR/token. A pure
connection error (DNS, connection refused) is still retried for every method, since
that request never reached the server. `404` (missing) and `422` (already exists /
conflict) are NOT in the force-list — callers treat them as meaningful, not transient.
"""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# urllib3 sleeps 0 before the 1st retry, then backoff_factor * 2**(n-1): with 0.75
# that's 0, 1.5, 3, 6, 12, 24s between the 6 retries (capped by urllib3 at 120s).
_RETRY = Retry(
    total=6,
    connect=6,            # DNS / connection-refused blips (request never sent -> safe)
    read=3,
    status=5,
    backoff_factor=0.75,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET", "PUT", "HEAD"}),
    respect_retry_after_header=True,
    raise_on_status=False,  # let resp.raise_for_status() surface the final status code
)


def build_session() -> requests.Session:
    """A ``requests.Session`` that retries transient GitHub/Vercel failures (see module docstring)."""
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=_RETRY)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
