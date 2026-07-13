"""
GitHub App credential distribution engine (`ops:distribute-app-secrets`).

Copies the cicd-held KDF GitHub App credentials — the repository secrets KDF_APP_ID and
KDF_APP_PRIVATE_KEY — to every consumer repo listed in scripts/secret_registry.json
(the entries carrying `distribute_source_env`). Consumer repos need their own copies
because personal-account repos cannot share secrets (no org secrets until the org move):
the copies power the E2E gate's App-token mint (run-e2e composite action) and the
ci-python-* (and, from epic Wave 3, ci-nextjs-*) private-package install tokens.

This generalizes the fixed-allow-list copy step in ops-setup-e2e.yml (which still owns the
E2E-specific RUN_E2E_GATE / USE_GITHUB_APP variables): here the target list lives in the
registry, so onboarding a consumer repo is a registry edit, not a workflow edit
(AGENTS.md rule 12). Reports-ecosystem epic Wave 2.5, ADR D-010.

PRE-ORG-MOVE STOPGAP: after an org move KDF_APP_* become org secrets (visible to every
repo with no copy) and both this flow and the per-repo copies are obsolete — the
registry's target list is then the cleanup checklist for deleting the copies.

Modes
  check     Read-only audit: list each target repo's Actions-secret NAMES (+ updated
            timestamps — the API cannot return values) and report which targets lack a
            copy. Exit 0 when the audit completed (missing copies are the report, not a
            failure); exit 1 only when a repo could not be audited.
  execute   Encrypt each source value against every target repo's public key and PUT it.
            PUT is create-or-update, so re-runs are idempotent; per-target failures are
            aggregated and reported, never abort the fan-out.
  targets   Print the comma-separated short names of every target repo (the union over
            all distributable entries). Feeds the ops workflow's App-token
            `repositories:` scope.

Environment variables
  GH_TOKEN               token with secrets:read (check) / secrets:write (execute) on
                         every target — the App installation token, or CICD_PAT fallback
  KDF_APP_ID             source value [execute] — from this repo's same-named secret
  KDF_APP_PRIVATE_KEY    source value [execute] — from this repo's same-named secret

SECURITY: source values arrive only via env, flow only into the libsodium sealed box
(rotate_secret.update_github_repo_secret), and are never printed — output is secret
NAMES, repos, and timestamps. The value sanity checks name the expected SHAPE on
failure, never the value.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from common.http import build_session

# The sealed-box PUT (libsodium encrypt against the target repo's public key) is
# single-sourced in the rotation engine — a second implementation here could drift on
# the crypto. Its module-level session also carries the shared retry/backoff config.
from rotate_secret import GITHUB_API, _github_headers, update_github_repo_secret

REGISTRY_FILE = Path(__file__).parent / "secret_registry.json"

_SESSION = build_session()

_FORMAT_HUMAN = {
    "numeric": "an all-digits GitHub App id",
    "pem": "a PEM private key (-----BEGIN ... PRIVATE KEY-----)",
}


def _looks_valid(value: str, fmt: str) -> bool:
    """Best-effort shape check so swapped env wiring fails BEFORE any write.

    Callers report the expected shape (`_FORMAT_HUMAN`) on failure — never the value.
    An unknown/absent `value_format` label means no check (the write itself is the
    operation; this guard only catches obviously mis-wired sources).
    """
    if fmt == "numeric":
        return value.isdigit()
    if fmt == "pem":
        return "-----BEGIN" in value and "PRIVATE KEY-----" in value
    return True


# ============================================================
# Registry + selection
# ============================================================


def _load_registry() -> dict:
    if not REGISTRY_FILE.is_file():
        sys.exit(f"Error: registry file not found: {REGISTRY_FILE}")
    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))


def _distributable(registry: dict) -> list[dict]:
    """Entries opted into distribution (they carry `distribute_source_env`)."""
    return [e for e in registry.get("secrets", []) if e.get("distribute_source_env")]


def _select_entries(registry: dict, raw: str) -> list[dict]:
    """Distributable entries matching the CSV filter (empty / 'all' = every one).

    Refuses unknown names AND known-but-non-distributable names (e.g.
    VERCEL_DEPLOYMENT_TOKEN): this engine must never become a second write path for
    secrets the rotation engine owns.
    """
    entries = _distributable(registry)
    if not entries:
        sys.exit("Error: no distributable entries (distribute_source_env) in the registry.")
    stripped = (raw or "").strip().lower()
    if stripped in ("", "all"):
        return entries
    by_name = {e["name"].lower(): e for e in entries}
    wanted = {p.strip() for p in stripped.split(",") if p.strip()}
    unknown = sorted(w for w in wanted if w not in by_name)
    if unknown:
        sys.exit(
            f"Error: not distributable: {', '.join(unknown)}. "
            f"Distributable secrets: {', '.join(sorted(by_name))}."
        )
    return [e for e in entries if e["name"].lower() in wanted]


def _target_repos(entries: list[dict]) -> list[str]:
    """Sorted union of `owner/repo` targets across the entries."""
    return sorted({t["repo"] for e in entries for t in e.get("github_repo_secrets", [])})


# ============================================================
# GitHub read helper (check mode)
# ============================================================


def list_repo_secret_meta(gh_token: str, owner_repo: str) -> dict[str, str]:
    """Map of secret NAME -> updated_at for a repo's Actions secrets.

    The list endpoint returns metadata only (GitHub cannot return secret values).
    GitHub caps a repo at 100 Actions secrets, so one `per_page=100` call is complete.
    """
    owner, repo = owner_repo.split("/", 1)
    resp = _SESSION.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/actions/secrets",
        headers=_github_headers(gh_token),
        params={"per_page": 100},
        timeout=30,
    )
    resp.raise_for_status()
    return {s["name"]: s.get("updated_at", "?") for s in resp.json().get("secrets", [])}


# ============================================================
# Mode: check
# ============================================================


def cmd_check(entries: list[dict], gh_token: str) -> int:
    """Audit which targets hold / lack each distributable secret. Read-only.

    Prints a machine-greppable `MISSING: <n>` line for the ops workflow's summary.
    """
    if not gh_token:
        sys.exit("Error: GH_TOKEN not set.")
    repos = _target_repos(entries)
    names = [e["name"] for e in entries]
    print(
        f"Auditing {len(repos)} target repo(s) for {len(names)} distributable "
        f"secret(s): {', '.join(names)}\n"
    )
    errors: list[str] = []
    missing = 0
    for owner_repo in repos:
        try:
            have = list_repo_secret_meta(gh_token, owner_repo)
        except Exception as exc:  # noqa: BLE001
            print(f"{owner_repo}: ERROR listing secrets - {exc}")
            errors.append(f"{owner_repo}: {exc}")
            continue
        print(f"{owner_repo}:")
        for entry in entries:
            name = entry["name"]
            if not any(t["repo"] == owner_repo for t in entry.get("github_repo_secrets", [])):
                continue
            if name in have:
                print(f"  {name}: present (updated {have[name]})")
            else:
                print(f"  {name}: MISSING")
                missing += 1
    print()
    print(f"MISSING: {missing}")
    if errors:
        print(f"{len(errors)} repo(s) could not be audited:")
        for e in errors:
            print(f"  - {e}")
        return 1
    if missing:
        print("Audit complete. Run mode=execute to write the missing copies.")
    else:
        print("Audit complete. Every target holds every copy.")
    return 0


# ============================================================
# Mode: execute
# ============================================================


def cmd_execute(entries: list[dict], gh_token: str) -> int:
    if not gh_token:
        sys.exit("Error: GH_TOKEN not set.")
    # Resolve + sanity-check EVERY source value before the first write, so a missing or
    # mis-wired env var can never half-distribute the pair.
    values: dict[str, str] = {}
    for entry in entries:
        env_name = entry["distribute_source_env"]
        value = os.environ.get(env_name, "")
        if not value:
            sys.exit(
                f"Error: {env_name} is not set — the ops workflow passes it from this "
                "repo's same-named secret (execute mode only). Nothing was written."
            )
        fmt = entry.get("value_format", "")
        if fmt and not _looks_valid(value, fmt):
            sys.exit(
                f"Error: {env_name} does not look like {_FORMAT_HUMAN.get(fmt, fmt)} — "
                "refusing to distribute a mis-wired value. Nothing was written."
            )
        values[entry["name"]] = value

    errors: list[str] = []
    for entry in entries:
        targets = entry.get("github_repo_secrets", [])
        print(f"Distributing {entry['name']} to {len(targets)} repo(s):")
        for t in targets:
            label = f"{t['repo']} [repo] {t['secret_name']}"
            print(f"  {label}", end=" ... ", flush=True)
            try:
                update_github_repo_secret(
                    gh_token, t["repo"], t["secret_name"], values[entry["name"]]
                )
                print("OK")
            except Exception as exc:  # noqa: BLE001
                print(f"FAILED - {exc}")
                errors.append(f"{label}: {exc}")
    print()
    if errors:
        print(f"{len(errors)} target(s) failed (PUT is idempotent — fix and re-run to converge):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("All targets updated successfully.")
    return 0


# ============================================================
# Mode: targets
# ============================================================


def cmd_targets(registry: dict) -> int:
    """Print the comma-separated SHORT names of every distribution target.

    Always the union over ALL distributable entries (ignores --secrets): the ops
    workflow scopes its App token once, before knowing which secrets a run touches.
    `actions/create-github-app-token`'s `repositories:` input takes bare repo names —
    every target shares the one account owner.
    """
    repos = _target_repos(_distributable(registry))
    print(",".join(r.split("/", 1)[1] for r in repos))
    return 0


# ============================================================
# CLI
# ============================================================


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Distribute the cicd-held GitHub App credentials to every consumer repo "
            "in secret_registry.json (entries carrying distribute_source_env)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("mode", choices=["check", "execute", "targets"])
    parser.add_argument(
        "--secrets",
        default="all",
        help='Comma-separated distributable secret names, or "all" (targets mode ignores this).',
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_cli_args(argv)
    registry = _load_registry()
    if args.mode == "targets":
        sys.exit(cmd_targets(registry))
    entries = _select_entries(registry, args.secrets)
    gh_token = os.environ.get("GH_TOKEN", "").strip()
    if args.mode == "check":
        sys.exit(cmd_check(entries, gh_token))
    sys.exit(cmd_execute(entries, gh_token))


if __name__ == "__main__":
    main()
