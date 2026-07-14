"""
Reports-triage trigger engine (`trigger-reports-triage.yml` / `ops:triage-reports`).

POSTs each selected app's ``{base_url}/reports/triage/cron`` endpoint with the
``X-Cron-Secret`` header so the app runs one AI triage batch in-process (the kdf_reports
package: PII-redact -> cluster -> GitHub issues + board items). The trigger lives in
GitHub Actions — not Vercel cron / a cloud scheduler — by owner decision (cloud-agnostic
orchestration); this engine is the workflow's whole brain, driven by
scripts/reports_registry.json. Reports-ecosystem epic Wave 4, ADR D-010.

Selection
  --apps enabled       Entries with ``enabled: true`` for the environment (the SCHEDULED
                       selection; all entries ship ``enabled: false``, so the weekly cron
                       is a no-op until the owner flips an entry). Empty selection = OK.
  --apps all           Every registry entry for the environment. TODO_-placeholder
                       base_urls are skipped with a warning, never fired.
  --apps slug[,slug]   Explicit app slugs. Unknown slugs and TODO_ base_urls are hard
                       errors — an explicit request must never silently no-op.
  --dry-run            Validate selection + secret PRESENCE and print the firing plan
                       (app, environment, URL, secret NAME) without POSTing anything.

Failure semantics (deliberate — see docs/guides/REPORTS_TRIAGE_OPS.md)
  * POSTs are NEVER status-retried: ``common.http.build_session`` retries only
    GET/PUT/HEAD statuses, so a 502-that-actually-triaged cannot double-fire a batch.
    (The app's PL-134 concurrency guard makes even a true double-fire safe; re-runs are
    manual, via re-dispatch.) Pure connection errors do retry — those never reached the
    server.
  * Every cron secret is resolved from the environment BEFORE the first POST, so a
    mis-wired workflow can never half-fire a multi-app run.
  * Per-app failures are aggregated and reported; one app's failure never aborts the
    fan-out to the others.
  * A quiet week is green: the app answers 202 with total_reports=0 when there is
    nothing to triage.

Environment variables
  REPORTS_CRON_SECRET_FITNESS_APP / REPORTS_CRON_SECRET_TIFFANYS_SPACE
      cicd-side copies of each app's X-Cron-Secret value (registry `cron_secret_env`).
      Authoritative value is the Terraform app-side one — SECRET_ROTATION.md §8.13a.

SECURITY: output is METADATA-ONLY. Secret values are read from env, sent only as the
X-Cron-Secret header, and never printed. Success output whitelists scalar batch counters
(``_METADATA_FIELDS``); cluster payloads, error_message, and raw response bodies are
never echoed (report content must not leak into public Actions logs / issue comments) —
non-2xx statuses map to fixed local interpretations instead. Unit-tested invariants.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from common.http import build_session

REGISTRY_FILE = Path(__file__).parent / "reports_registry.json"

TRIAGE_CRON_PATH = "/reports/triage/cron"
CRON_SECRET_HEADER = "X-Cron-Secret"  # noqa: S105 — header NAME, not a credential

# (connect, read): AI clustering runs synchronously in the app; Vercel functions allow
# up to 300s, so the read timeout matches rather than guessing lower.
REQUEST_TIMEOUT = (10, 300)

ENVIRONMENTS = ("dev", "prod")

# The ONLY response fields success output may echo — scalar batch counters/identifiers.
# Cluster payloads and error_message stay in the app; they can carry report content.
_METADATA_FIELDS = (
    "id",
    "status",
    "total_reports",
    "clusters_created",
    "issues_opened",
    "model_name",
    "prompt_version",
)

# Fixed interpretations keyed by HTTP status — printed INSTEAD of the response body.
_STATUS_HINTS = {
    207: (
        "triage ran but some GitHub writes failed (partial_link) — check the app logs; "
        "a re-run links the remainder"
    ),
    400: "the app rejected the request (bad request)",
    401: (
        f"{CRON_SECRET_HEADER} mismatch — the cicd-side secret copy is stale against the "
        "app's REPORTS_CRON_SECRET (rotate: SECRET_ROTATION.md §8.13a)"
    ),
    409: (
        "a triage batch is already running for this app (PL-134 concurrency guard) — "
        "not double-fired; re-dispatch later"
    ),
    429: "the app's AI provider rate-limited the run — re-dispatch later",
    503: (
        "endpoint is fail-closed: REPORTS_CRON_SECRET is unset on the app — provision it "
        "via the terraform env block first"
    ),
    504: "AI triage timed out inside the app",
}

_SESSION = build_session()


# ============================================================
# Registry + selection
# ============================================================


def _load_registry() -> dict:
    if not REGISTRY_FILE.is_file():
        sys.exit(f"Error: registry file not found: {REGISTRY_FILE}")
    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))


def _is_todo(entry: dict) -> bool:
    return str(entry.get("base_url", "")).startswith("TODO_")


def select_entries(registry: dict, raw_apps: str, environment: str) -> list[dict]:
    """Registry entries to fire for this run (see module docstring for the modes).

    Explicit slugs are validated hard (unknown slug / TODO_ base_url = abort before any
    POST); bulk modes (``enabled`` / ``all``) skip TODO_ entries with a warning so one
    unconfigured app can't block the others.
    """
    env_entries = [e for e in registry.get("apps", []) if e.get("environment") == environment]
    if not env_entries:
        sys.exit(f"Error: no registry entries for environment '{environment}'.")
    known = sorted({e["app_slug"] for e in env_entries})

    stripped = (raw_apps or "").strip().lower()
    if stripped in ("", "enabled"):
        selected = [e for e in env_entries if e.get("enabled") is True]
    elif stripped == "all":
        selected = list(env_entries)
    else:
        wanted = {p.strip() for p in stripped.split(",") if p.strip()}
        unknown = sorted(w for w in wanted if w not in known)
        if unknown:
            sys.exit(
                f"Error: unknown app slug(s) for environment '{environment}': "
                f"{', '.join(unknown)}. Known: {', '.join(known)}."
            )
        selected = [e for e in env_entries if e["app_slug"] in wanted]
        todo = sorted(e["app_slug"] for e in selected if _is_todo(e))
        if todo:
            sys.exit(
                f"Error: base_url for {', '.join(todo)} ({environment}) is still a TODO_ "
                "placeholder — fill scripts/reports_registry.json (owner: Vercel dashboard "
                "-> project -> Domains) before requesting it explicitly. Nothing was fired."
            )
        return selected

    fireable = [e for e in selected if not _is_todo(e)]
    for e in selected:
        if _is_todo(e):
            print(
                f"SKIP {e['app_slug']} ({environment}): base_url is a TODO_ placeholder "
                "in scripts/reports_registry.json — not fired."
            )
    return fireable


def resolve_secrets(entries: list[dict]) -> dict[str, str]:
    """Map ``cron_secret_env`` name -> value for every selected entry.

    All-or-nothing, BEFORE the first POST: a missing env var aborts the whole run so a
    mis-wired workflow can never half-fire a multi-app selection. Values are returned
    for header use only — callers never print them.
    """
    secrets: dict[str, str] = {}
    for entry in entries:
        env_name = entry["cron_secret_env"]
        if env_name in secrets:
            continue
        value = os.environ.get(env_name, "").strip()
        if not value:
            sys.exit(
                f"Error: {env_name} is not set — set the cicd repo secret (the caller-side "
                "copy of the app's REPORTS_CRON_SECRET, SECRET_ROTATION.md §8.13a). "
                "Nothing was fired."
            )
        secrets[env_name] = value
    return secrets


# ============================================================
# Firing
# ============================================================


def _cron_url(entry: dict) -> str:
    return str(entry["base_url"]).rstrip("/") + TRIAGE_CRON_PATH


def _print_accepted_metadata(resp) -> None:
    """Echo ONLY the whitelisted scalar batch counters from a 202 body."""
    try:
        body = resp.json()
    except ValueError:
        print("    accepted (202); response body not parseable — batch metadata unavailable")
        return
    if not isinstance(body, dict):
        print("    accepted (202); unexpected response shape — batch metadata unavailable")
        return
    parts = [f"{k}={body[k]}" for k in _METADATA_FIELDS if k in body]
    print(f"    accepted (202): {', '.join(parts) if parts else 'no batch metadata returned'}")


def fire_one(entry: dict, secret_value: str) -> bool:
    """POST one app's cron endpoint. Returns success; never raises, never retries a status."""
    label = f"{entry['app_slug']} ({entry['environment']})"
    url = _cron_url(entry)
    print(f"POST {label}: {url}")
    try:
        resp = _SESSION.post(
            url,
            headers={CRON_SECRET_HEADER: secret_value},
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 — network errors are per-app results, not crashes
        print(f"    FAILED - could not reach the app: {type(exc).__name__}")
        return False
    if resp.status_code == 202:
        _print_accepted_metadata(resp)
        return True
    hint = _STATUS_HINTS.get(resp.status_code, "unexpected status")
    # Deliberately NOT the response body: bodies can carry report content.
    print(f"    FAILED - HTTP {resp.status_code}: {hint}")
    return False


def run(entries: list[dict], environment: str, dry_run: bool) -> int:
    if not entries:
        print(
            f"Nothing to fire for environment '{environment}': no enabled/selected apps. "
            "(All registry entries ship enabled:false — flip an entry to arm the schedule.)"
        )
        print("RESULT: ok=0 failed=0")
        return 0

    secrets = resolve_secrets(entries)

    if dry_run:
        print(f"DRY RUN — would fire {len(entries)} app(s) against '{environment}':")
        for e in entries:
            print(f"  {e['app_slug']}: {_cron_url(e)}  [secret: {e['cron_secret_env']} present]")
        print("RESULT: ok=0 failed=0")
        return 0

    ok = failed = 0
    for e in entries:
        if fire_one(e, secrets[e["cron_secret_env"]]):
            ok += 1
        else:
            failed += 1
    print()
    print(f"RESULT: ok={ok} failed={failed}")
    if failed:
        print(
            f"{failed} app(s) failed. POSTs are never status-retried (a batch may already "
            "have started); PL-134 makes a manual re-dispatch safe."
        )
        return 1
    return 0


# ============================================================
# CLI
# ============================================================


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fire the reports-triage cron endpoint of each selected app "
            "(scripts/reports_registry.json)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apps",
        default="enabled",
        help='App slugs (CSV), "enabled" (default; the scheduled selection), or "all".',
    )
    parser.add_argument("--environment", required=True, choices=ENVIRONMENTS)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate selection + secret presence and print the plan without POSTing.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_cli_args(argv)
    registry = _load_registry()
    entries = select_entries(registry, args.apps, args.environment)
    sys.exit(run(entries, args.environment, args.dry_run))


if __name__ == "__main__":
    main()
