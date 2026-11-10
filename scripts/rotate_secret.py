"""
Unified CI-plane secret rotation engine.

One registry (scripts/secret_registry.json) maps each rotatable secret to every place
its value lives — GitHub Actions ENVIRONMENT secrets (github_env_secrets), GitHub Actions
REPOSITORY secrets (github_repo_secrets — what CI reads when a job declares no environment),
and/or non-Terraform Vercel project env vars. This script is the single front-end behind both
the scheduled rotation workflows and the owner-only `ops:rotate-secrets` issue form.

SCOPE — CI-plane credentials only. App secrets owned by Terraform (SECRETS_INVENTORY:
DB URLs, the RS256 keypair, KDF_SERVICE_KEY, STRIPE_*, OIDC client secrets, CRON_SECRET …)
must be rotated through the terraform SECRETS_ROTATION runbook, NOT here — a direct API
write would drift on the next `terraform apply`. Any registry entry flagged
`"terraform_managed": true` is refused by this engine (fail closed).

Modes
  generate   Mint fresh value(s) and write them to the registry targets.
               generator "vercel_token"   -> one unique Vercel API token per target (create,
                                             write to the GitHub env secret, delete the old token)
               generator "random_urlsafe" -> a high-entropy random value (per-environment when
                                             per_env, else one shared value)
  paste      Write an owner-supplied value (from the STAGED_SECRET_VALUE env, never an issue body) to one `paste`
             entry's registry targets. Single secret only.
  paste-staged
             The staging slots' run (D-099). Each slot a registry `paste` entry names in `staging`, one per
             environment for an entry held in two, is read from the env var of its own name. Every selected slot is
             checked before anything is written, set, recent and with every target resolved, then each is pasted to
             its entry's targets and deleted from cicd's ops once they are written, a failed one kept for a retry.
  check      Report time-to-expiry for secrets that carry a "check" block (advisory rotation).

Environment variables
  GH_TOKEN              Writes the targets' secrets, and reads and deletes cicd's ops slots.   [generate/paste/staged]
  FACTS_GH_TOKEN        Writes cicd's variables, the expiry facts.                             [paste-staged]
  VERCEL_MASTER_TOKEN   Vercel API token that can create/delete tokens + set project env.   [vercel_token generate / paste-to-vercel]
  STAGED_SECRET_VALUE   The value to distribute.                                            [paste]
  <SLOT>                Each selected staging slot's value, under the slot's own name.     [paste-staged]

Usage
  python rotate_secret.py --mode check    --secrets all
  python rotate_secret.py --mode check    --secrets all --live   # each check.live token's real expiry (D-049)
  python rotate_secret.py --mode generate --secrets VERCEL_DEPLOYMENT_TOKEN
  python rotate_secret.py --mode paste    --secrets GH_PACKAGES_PAT          # value from STAGED_SECRET_VALUE
  python rotate_secret.py --mode paste-staged --slots GH_PACKAGES_PAT_NEW,GH_NPM_TOKEN_NEW
  python rotate_secret.py --mode record-expiry --secrets VERCEL_DEPLOYMENT_TOKEN
"""

from __future__ import annotations

# standard imports
import argparse
import base64
import json
import os
import secrets as _secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# third party imports
import requests
from common.http import build_session
from nacl import encoding, public

# ======================================================================================================================
# Configuration
# ======================================================================================================================

REGISTRY_FILE = Path(__file__).parent / "secret_registry.json"
VERCEL_API    = "https://api.vercel.com"
GITHUB_API    = "https://api.github.com"

# New Vercel tokens expire after 33 days, the owner's rule of 2026-11-10 for every token. The cron rotates on the 1st
# of each month and the old token is deleted then, so a month's token outlives its month by a few days of grace.
TOKEN_EXPIRY_DAYS = 33

# a staging slot set longer ago than this is refused, so a value left behind from an earlier rotation is never
# pasted again (D-099)
STAGED_MAX_AGE_DAYS = 7

# the cicd environment that holds every staging slot
OPS_ENVIRONMENT = "ops"

# a registry entry's `check.live` names where its real expiry is read, with the secret itself (D-049)
LIVE_SOURCES = {"github": "GitHub", "vercel-current": "Vercel", "vercel-named": "Vercel"}

# a token marked `check.recorded` lives in ops, so the ops run keeps its expiry as the cicd repository variable
# EXPIRY_<NAME> and the weekly monitor reads that fact (the secrets fence)
RECORDED_PREFIX = "EXPIRY_"
FACT_STATUSES   = ("ok", "rejected", "no-expiry", "no-token", "error")

# the throwaway token the prove-master mode mints with the master token and deletes at once
PROVE_MASTER_TOKEN_NAME = "kdf-prove-master-throwaway"

# Shared HTTP session with retry/backoff so a transient GitHub/Vercel 5xx / 429 / DNS blip doesn't
# strand a secret half-written across the fan-out. Config + rationale live in common/http.py (the
# same session hardens distribute_kit.py). Idempotent GET/PUT retry; POST/DELETE/PATCH (create/delete
# token, delete secret) are not status-retried, so a 502-after-success can't duplicate/revoke twice.
_SESSION = build_session()

# ======================================================================================================================
# GitHub helpers
# ======================================================================================================================

def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_env_public_key(gh_token: str, owner: str, repo: str, environment: str) -> tuple[str, str]:
    """
    Return (key_id, base64_public_key) for a repo environment's secret box.
    """
    resp = _SESSION.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/environments/{environment}/secrets/public-key",
        headers = _github_headers(gh_token),
        timeout = 30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["key_id"], data["key"]


def _encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    """
    Seal `secret_value` to the repo's libsodium public key (base64 out).
    """
    pub_key   = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder)
    sealed    = public.SealedBox(pub_key)
    encrypted = sealed.encrypt(secret_value.encode())
    return base64.b64encode(encrypted).decode()


def update_github_env_secret(
    gh_token: str,
    owner_repo: str,
    environment: str,
    secret_name: str,
    secret_value: str,
) -> None:
    """
    Encrypt + PUT a value into repo `owner_repo`'s environment secret.
    """
    owner, repo = owner_repo.split("/", 1)
    key_id, pub_key_b64 = _get_env_public_key(gh_token, owner, repo, environment)
    encrypted = _encrypt_secret(pub_key_b64, secret_value)
    resp      = _SESSION.put(
        f"{GITHUB_API}/repos/{owner}/{repo}/environments/{environment}/secrets/{secret_name}",
        headers = _github_headers(gh_token),
        json = {"encrypted_value": encrypted, "key_id": key_id},
        timeout = 30,
    )
    resp.raise_for_status()


def _get_repo_public_key(gh_token: str, owner: str, repo: str) -> tuple[str, str]:
    """
    Return (key_id, base64_public_key) for a repo's REPOSITORY (Actions) secret box.
    """
    resp = _SESSION.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/actions/secrets/public-key",
        headers = _github_headers(gh_token),
        timeout = 30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["key_id"], data["key"]


def update_github_repo_secret(
    gh_token: str,
    owner_repo: str,
    secret_name: str,
    secret_value: str,
) -> None:
    """
    Encrypt + PUT a value into repo `owner_repo`'s REPOSITORY (Actions) secret.

    Repository secrets are a DIFFERENT store from environment secrets. A CI job that
    does NOT declare `environment:` (e.g. the reusable ci-python-*.yml SDK-install step,
    triggered on pull_request) can only read repository/organization secrets — never
    environment secrets. A value pasted solely into an environment is therefore invisible
    to CI, which is why a GH_PACKAGES_PAT rotation used to leave CI on a dead token even
    after every environment secret was refreshed. Targets are declared per registry entry
    under `github_repo_secrets`.
    """
    owner, repo = owner_repo.split("/", 1)
    key_id, pub_key_b64 = _get_repo_public_key(gh_token, owner, repo)
    encrypted = _encrypt_secret(pub_key_b64, secret_value)
    resp      = _SESSION.put(
        f"{GITHUB_API}/repos/{owner}/{repo}/actions/secrets/{secret_name}",
        headers = _github_headers(gh_token),
        json = {"encrypted_value": encrypted, "key_id": key_id},
        timeout = 30,
    )
    resp.raise_for_status()


def delete_github_env_secret(
    gh_token: str,
    owner_repo: str,
    environment: str,
    secret_name: str,
) -> None:
    """
    DELETE a repo ENVIRONMENT secret.

    Used to reap the environment-level copy of a secret that has migrated to repository-level
    (see `retired_github_env_secrets`). A leftover env copy shadows the repo value — an env
    secret takes precedence over a same-named repo secret — so the migration is not complete
    until the env copy is gone. Idempotent: a 404 (already absent) is treated as success so a
    re-run is a clean no-op.
    """
    owner, repo = owner_repo.split("/", 1)
    resp = _SESSION.delete(
        f"{GITHUB_API}/repos/{owner}/{repo}/environments/{environment}/secrets/{secret_name}",
        headers = _github_headers(gh_token),
        timeout = 30,
    )
    if resp.status_code == 404:
        return
    resp.raise_for_status()


def github_env_secret_updated_at(gh_token: str, owner_repo: str, environment: str, secret_name: str) -> str | None:
    """
    When an environment secret was last set, from GitHub's metadata, never its value.

    Args:
        gh_token: A token that reads the repo's environment secrets
        owner_repo: The repo, owner/name
        environment: The environment holding it
        secret_name: The secret's name

    Returns:
        The `updated_at` time GitHub reports, or None when the secret is not set

    Raises:
        requests.HTTPError: When GitHub refuses the read
    """
    owner, repo = owner_repo.split("/", 1)
    resp = _SESSION.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/environments/{environment}/secrets/{secret_name}",
        headers = _github_headers(gh_token),
        timeout = 30,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json().get("updated_at")

# ======================================================================================================================
# Vercel helpers
# ======================================================================================================================

def _vercel_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


class VercelMasterScopeError(RuntimeError):
    """
    Raised when the Vercel token API returns 403 — VERCEL_MASTER_TOKEN lacks Full Account scope.
    """


def _raise_for_token_api(resp: requests.Response) -> None:
    """
    ``raise_for_status`` for the ``/v3/user/tokens`` calls, with a clear hint on 403.

    The token-management API is personal-account-only: a team / "all projects" scoped
    VERCEL_MASTER_TOKEN is rejected there with 403. Surface that as an actionable message instead of a
    bare HTTP error (this is the #1 misconfiguration for the rotation engine).
    """
    if resp.status_code == 403:
        raise VercelMasterScopeError(
            "Vercel returned 403 from /v3/user/tokens — VERCEL_MASTER_TOKEN must be a FULL ACCOUNT "
            "scoped token to mint/list/delete tokens. A team / 'all projects' token (the kind used for "
            "deploys) is rejected here. Create a Full Account token in Vercel and update the "
            "VERCEL_MASTER_TOKEN repo secret."
        )
    resp.raise_for_status()


def create_vercel_token(master_token: str, name: str, team_id: str = "") -> tuple[str, str]:
    """
    Create a new Vercel API token (TOKEN_EXPIRY_DAYS expiry). Returns (token_id, token_value).

    When ``team_id`` is set, the token is scoped to that Vercel team (the ``teamId`` query param) so it
    can deploy/manage the team's projects. A token minted WITHOUT a team is personal-account-scoped, and
    Vercel rejects it ("The specified token is not valid") the moment the CLI targets a team project.
    """
    expires_at_ms = int((datetime.now(timezone.utc) + timedelta(days = TOKEN_EXPIRY_DAYS)).timestamp() * 1000)
    resp          = _SESSION.post(
        f"{VERCEL_API}/v3/user/tokens",
        headers = _vercel_headers(master_token),
        params = {"teamId": team_id} if team_id else None,
        json = {"name": name, "expiresAt": expires_at_ms},
        timeout = 30,
    )
    _raise_for_token_api(resp)
    data = resp.json()
    return data["token"]["id"], data["bearerToken"]


def list_vercel_tokens(master_token: str) -> list[dict]:
    resp = _SESSION.get(
        f"{VERCEL_API}/v3/user/tokens",
        headers = _vercel_headers(master_token),
        timeout = 30,
    )
    _raise_for_token_api(resp)
    return resp.json().get("tokens", [])


def delete_vercel_token(master_token: str, token_id: str) -> None:
    resp = _SESSION.delete(
        f"{VERCEL_API}/v3/user/tokens/{token_id}",
        headers = _vercel_headers(master_token),
        timeout = 30,
    )
    _raise_for_token_api(resp)


def _list_vercel_env_vars(master_token: str, project_id: str) -> list[dict]:
    resp = _SESSION.get(
        f"{VERCEL_API}/v10/projects/{project_id}/env",
        headers = _vercel_headers(master_token),
        timeout = 30,
    )
    resp.raise_for_status()
    return resp.json().get("envs", [])


def upsert_vercel_env_var(master_token: str, project_id: str, key: str, value: str) -> None:
    """
    Patch every existing entry for `key` in place, or create one covering all 3 targets.
    """
    existing = [e for e in _list_vercel_env_vars(master_token, project_id) if e["key"] == key]
    if existing:
        for entry in existing:
            resp = _SESSION.patch(
                f"{VERCEL_API}/v10/projects/{project_id}/env/{entry['id']}",
                headers = _vercel_headers(master_token),
                json = {"value": value, "type": "encrypted", "target": entry["target"]},
                timeout = 30,
            )
            resp.raise_for_status()
    else:
        resp = _SESSION.post(
            f"{VERCEL_API}/v10/projects/{project_id}/env",
            headers = _vercel_headers(master_token),
            json = {
                "key": key,
                "value": value,
                "type": "encrypted",
                "target": ["production", "preview", "development"],
            },
            timeout = 30,
        )
        resp.raise_for_status()

# ======================================================================================================================
# Registry + filters
# ======================================================================================================================

def _load_registry() -> dict:
    if not REGISTRY_FILE.is_file():
        sys.exit(f"Error: registry file not found: {REGISTRY_FILE}")
    return json.loads(REGISTRY_FILE.read_text(encoding = "utf-8"))


def _parse_filter(raw: str) -> frozenset[str]:
    """
    Empty / 'all' -> empty frozenset (match all); else a set of lowercased names.
    """
    stripped = (raw or "").strip().lower()
    if stripped in ("", "all"):
        return frozenset()
    return frozenset(part.strip() for part in stripped.split(",") if part.strip())


def _select_secrets(registry: dict, names: frozenset[str]) -> list[dict]:
    """
    Registry entries matching `names` (empty = all). Exits if a named secret is unknown.
    """
    entries = registry.get("secrets", [])
    by_name = {e["name"].lower(): e for e in entries}
    if not names:
        return list(entries)
    unknown = sorted(n for n in names if n not in by_name)
    if unknown:
        known = ", ".join(sorted(by_name))
        sys.exit(f"Error: unknown secret(s): {', '.join(unknown)}. Known: {known}.")
    return [by_name[n] for n in sorted(names)]


def staging_slots(registry: dict) -> dict[str, tuple[dict, str]]:
    """
    Every staging slot the registry names, each with its entry and the one environment it feeds (D-099).

    A `paste` entry lists its slots in `staging`, one for an entry held in repository secrets alone and one per
    environment for an entry held in environments, so a slot's name alone decides where its value goes.

    Args:
        registry: The parsed registry

    Returns:
        The slot's name mapped to its entry and its environment, empty for a repository held entry
    """
    slots: dict[str, tuple[dict, str]] = {}
    for entry in registry.get("secrets", []):
        for slot in entry.get("staging", []):
            slots[slot["slot"]] = (entry, str(slot.get("environment", "")).lower())
    return slots


def _refuse_unless_paste(entry: dict) -> None:
    """
    Refuse a paste of any entry whose kind is not `paste`.

    A generated token, a credential made straight into ops or an App key distributed with its pair never takes a
    pasted value, which would write it outside its own flow, its generation or its key check (D-099).

    Args:
        entry: The registry entry being pasted
    """
    if entry.get("kind") != "paste":
        sys.exit(
            f"Error: {entry['name']} is of kind '{entry.get('kind')}', and only a 'paste' entry takes a pasted value.",
        )


def _refuse_if_terraform_managed(entry: dict) -> None:
    if entry.get("terraform_managed"):
        sys.exit(
            f"Error: '{entry['name']}' is Terraform-managed — refusing to write it directly "
            "(it would drift on the next `terraform apply`). Rotate it via the terraform "
            "SECRETS_ROTATION runbook (update *.secrets.auto.tfvars + apply, with -replace for "
            "coupled groups)."
        )


def _gh_targets(entry: dict, apps: frozenset[str], envs: frozenset[str]) -> list[dict]:
    out = []
    for t in entry.get("github_env_secrets", []):
        if apps and t.get("app", "").lower() not in apps:
            continue
        if envs and t.get("environment", "").lower() not in envs:
            continue
        out.append(t)
    return out


def _gh_repo_targets(entry: dict) -> list[dict]:
    """
    Repository-level (Actions) secret targets.

    Unlike environment secrets these are NOT env-scoped — a repository secret is a single
    global value read by CI jobs that declare no `environment:` — so the app/env filters
    do not apply and every listed target is always written on a distribution.
    """
    return list(entry.get("github_repo_secrets", []))


def _delete_retired_env_secrets(entry: dict, gh_token: str, errors: list[str]) -> int:
    """
    Reap the environment-level copies a secret has migrated away from (repository-level now).

    A secret that moved from `github_env_secrets` to `github_repo_secrets` (e.g. the single shared
    VERCEL_DEPLOYMENT_TOKEN / GH_PACKAGES_PAT) leaves stale env copies that SHADOW the repo value —
    an environment secret wins over a same-named repository secret — so CD would keep reading the old
    value. Deleting them makes the repo-level value authoritative. Returns the number of delete
    failures (0 = fully clean); appends any to `errors`. Callers gate token revocation on a clean (0)
    result so a repo whose shadow could not be removed keeps a valid token.
    """
    retired = entry.get("retired_github_env_secrets", [])
    if not retired:
        return 0
    failures = 0
    print(f"\nReaping {len(retired)} retired environment-level copy(ies) of {entry['name']} "
          "(migrated to repository-level; a leftover env copy would shadow it):")
    for t in retired:
        label = f"{t['repo']} [{t['environment']}] {t['secret_name']}"
        print(f"  delete {label}", end = " ... ", flush = True)
        try:
            delete_github_env_secret(gh_token, t["repo"], t["environment"], t["secret_name"])
            print("OK")
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED - {exc}")
            errors.append(f"delete env {label}: {exc}")
            failures += 1
    return failures


def _vercel_targets(entry: dict, envs: frozenset[str]) -> list[dict]:
    out = []
    for t in entry.get("vercel_env_vars", []):
        if envs and t.get("environment", "").lower() not in envs:
            continue
        out.append(t)
    return out

# ======================================================================================================================
# Live expiry (ADR D-049)
# ======================================================================================================================

def parse_github_expiry(raw: str) -> str | None:
    """
    The UTC date of GitHub's `github-authentication-token-expiration` header.

    Args:
        raw: the header's value, `2026-11-02 12:00:00 UTC` or `2026-11-02 12:00:00 -0500`

    Returns:
        str | None: the date as YYYY-MM-DD in UTC, or None when the value reads neither way
    """
    text = raw.strip()
    if text.endswith(" UTC"):
        text = text[: -len(" UTC")] + " +0000"
    try:
        when = datetime.strptime(text, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        return None
    return when.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _ms_date(millis: object) -> str | None:
    """
    The UTC date of a millisecond timestamp, as Vercel reports a token's `expiresAt`.

    Args:
        millis: milliseconds since the epoch

    Returns:
        str | None: the date as YYYY-MM-DD in UTC, or None when it is not a timestamp
    """
    try:
        return datetime.fromtimestamp(int(millis) / 1000, tz = timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def live_expiry(entry: dict, environ: dict[str, str] | None = None) -> tuple[str | None, str]:
    """
    The expiry its provider reports for a secret whose `check.live` names one, read with the secret from this run's
    environment, whose value is never printed.

    Args:
        entry: the secret's registry entry
        environ: where the secret's value is read, this process's environment when None

    Returns:
        tuple[str | None, str]: the date and a status, `ok`, `no expiry`, `rejected`, `not checked live`, `no token
        in this run`, or `error, <what>`
    """
    env    = os.environ if environ is None else environ
    source = (entry.get("check") or {}).get("live")
    if not source:
        return None, "not checked live"
    if source not in LIVE_SOURCES:
        return None, f"error, unknown live source {source}"
    token = env.get("VERCEL_MASTER_TOKEN" if source == "vercel-named" else entry["name"], "").strip()
    if not token:
        return None, "no token in this run"
    try:
        if source == "github":
            resp = _SESSION.get(
                f"{GITHUB_API}/rate_limit",
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout = 30,
            )
            if resp.status_code == 401:
                return None, "rejected"
            if not resp.ok:
                return None, f"error, HTTP {resp.status_code}"
            raw = resp.headers.get("github-authentication-token-expiration", "")
            if not raw:
                return None, "no expiry"
            date = parse_github_expiry(raw)
            return (date, "ok") if date else (None, "error, an expiry header it cannot read")
        if source == "vercel-current":
            resp = _SESSION.get(f"{VERCEL_API}/v5/user/tokens/current", headers = _vercel_headers(token), timeout = 30)
            if resp.status_code in (401, 403):
                return None, "rejected"
            if not resp.ok:
                return None, f"error, HTTP {resp.status_code}"
            expires = (resp.json().get("token") or {}).get("expiresAt")
            if expires is None:
                return None, "no expiry"
            date = _ms_date(expires)
            return (date, "ok") if date else (None, "error, an expiresAt it cannot read")
        # vercel-named, the named token's expiry from the master token's list of tokens
        name = entry.get("vercel_token_name") or entry["name"]
        resp = _SESSION.get(f"{VERCEL_API}/v3/user/tokens", headers = _vercel_headers(token), timeout = 30)
        if resp.status_code in (401, 403):
            return None, "error, Vercel refused VERCEL_MASTER_TOKEN, so the named token was not read"
        if not resp.ok:
            return None, f"error, HTTP {resp.status_code}"
        named = [meta for meta in resp.json().get("tokens", []) if meta.get("name") == name]
        if not named:
            return None, f"error, no Vercel token named {name}"
        dates = [
            day for day in (_ms_date(meta.get("expiresAt")) for meta in named if meta.get("expiresAt") is not None)
            if day
        ]
        if not dates:
            return None, "no expiry"
        # after a rotation that kept the old token, a repo may still hold the one that expires first
        if len(named) > 1:
            return min(dates), f"ok, {len(named)} Vercel tokens are named {name}, the earliest expiry is used"
        return dates[0], "ok"
    except Exception as exc:  # noqa: BLE001, any failure is reported, never raised, and never with its text
        # the type alone, an exception's text could carry a request's details
        return None, f"error, {type(exc).__name__}"

# ======================================================================================================================
# Mode: check
# ======================================================================================================================

def _check_one(entry: dict, live: bool = False) -> tuple[int, str | None]:
    """
    Advisory expiry check for one secret.

    Args:
        entry: the secret's registry entry
        live: read the expiry from its provider where `check.live` says how

    Returns:
        tuple[int, str | None]: 0 = ok, 1 = warn/expired/rejected/misconfigured/no-check, and with `live` the date its
        provider reports when the registry's differs
    """
    name = entry["name"]
    chk  = entry.get("check")
    if not chk:
        print(f"  {name}: no expiry tracked (nothing to check).")
        return 0, None
    if chk.get("recorded"):
        return _check_recorded(entry), None
    expiry_raw = chk.get("expiry", "")
    warn_days  = chk.get("warn_days_before_expiry", 14)
    drift      = None
    if live and chk.get("live"):
        provider = LIVE_SOURCES.get(chk["live"], str(chk["live"]))
        date, status = live_expiry(entry)
        if status == "rejected":
            print(f"  {name}: REJECTED by {provider}, it is expired or revoked. Rotate now.")
            return 1, None
        if date:
            if status.startswith("ok, "):
                print(f"  {name}: NOTE — {status[len('ok, '):]}.")
            if date != expiry_raw:
                print(f"  {name}: DRIFT — the registry says {expiry_raw or 'nothing'}, {provider} says {date}. "
                      "Update check.expiry.")
                drift = date
            expiry_raw = date
        elif status == "no expiry":
            print(f"  {name}: OK — {provider} reports no expiry on it.")
            return 0, None
        else:
            print(f"  {name}: live check {status}, so the registry's date is used.")
    if not expiry_raw or str(expiry_raw).startswith("TODO"):
        print(f"  {name}: WARNING — expiry not set in the registry.")
        return 1, drift
    try:
        expiry = datetime.strptime(expiry_raw, "%Y-%m-%d").replace(tzinfo = timezone.utc)
    except ValueError:
        print(f"  {name}: ERROR — expiry '{expiry_raw}' is not YYYY-MM-DD.")
        return 1, drift
    days = (expiry - datetime.now(timezone.utc)).days
    if days < 0:
        print(f"  {name}: EXPIRED {(-days)} day(s) ago ({expiry_raw}). Rotate now.")
        return 1, drift
    if days <= warn_days:
        print(f"  {name}: WARNING — expires in {days} day(s) ({expiry_raw}, threshold {warn_days}).")
        return 1, drift
    print(f"  {name}: OK — valid for {days} more day(s) (expires {expiry_raw}).")
    return 0, drift


def cmd_check(entries: list[dict], live: bool = False) -> int:
    print(f"Checking expiry for {len(entries)} secret(s)" + (", live where the registry says how:" if live else ":"))
    needs: list[str] = []
    drift: list[str] = []
    for entry in entries:
        outcome, live_date = _check_one(entry, live)
        if outcome != 0:
            needs.append(entry["name"])
        if live_date:
            drift.append(f"{entry['name']}={live_date}")
    print()
    # Machine-readable lines the scheduled monitor greps to build/close its issue.
    print("NEEDS_ROTATION: " + ",".join(needs))
    print("REGISTRY_DRIFT: " + ",".join(drift))
    return 1 if needs or drift else 0

# ======================================================================================================================
# Mode: record-expiry
# ======================================================================================================================

def set_repo_variable(gh_token: str, owner_repo: str, name: str, value: str) -> None:
    """
    Update a repository Actions variable, or create it when it does not exist yet.

    Args:
        gh_token: A token that writes the repo's variables
        owner_repo: The repo, owner/name
        name: The variable's name
        value: Its value, never a secret

    Raises:
        RuntimeError: When GitHub refuses the write
    """
    base = f"{GITHUB_API}/repos/{owner_repo}/actions/variables"
    body = {"name": name, "value": value}
    resp = _SESSION.patch(f"{base}/{name}", headers = _github_headers(gh_token), json = body, timeout = 30)
    if resp.status_code == 404:
        resp = _SESSION.post(base, headers = _github_headers(gh_token), json = body, timeout = 30)
    if not resp.ok:
        raise RuntimeError(f"GitHub answered HTTP {resp.status_code} to the write of {name}")


def _status_word(status: str) -> str:
    """
    The one word a recorded fact keeps of a live read's status, `ok`, `rejected`, `no-expiry`, `no-token` or `error`.

    Args:
        status: The status `live_expiry` returned
    """
    for prefix, word in (("ok", "ok"), ("rejected", "rejected"), ("no expiry", "no-expiry"), ("no token", "no-token")):
        if status.startswith(prefix):
            return word
    return "error"


def cmd_record_expiry(
    entries: list[dict],
    gh_token: str,
    repo: str,
    environ: dict[str, str] | None = None,
    now: datetime | None = None,
) -> int:
    """
    Read each recorded token's expiry live and keep it as a cicd repository variable, nothing secret.

    The ops run holds CICD_PAT, the master token and the master's view of the deployment token, which the weekly
    monitor outside ops does not, so it records each one's expiry as `EXPIRY_<NAME>`, `expires=<date or none>
    status=<word> recorded=<UTC time>`, for the monitor to read (the secrets fence, design 5.5 item 9).

    Args:
        entries: The selected registry entries, those marked `check.recorded` recorded and the rest skipped
        gh_token: A token that writes cicd's variables
        repo: The repo holding the variables, owner/name
        environ: Where each token is read, this process's environment when None
        now: The time recorded, the clock's when None

    Returns:
        0 when every fact was written, else 1
    """
    if not gh_token or not repo:
        sys.exit("Error: GH_TOKEN and GITHUB_REPOSITORY are needed to record the expiry facts.")
    stamp    = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recorded = [entry for entry in entries if (entry.get("check") or {}).get("recorded")]
    print(f"Recording the expiry of {len(recorded)} token(s): {', '.join(entry['name'] for entry in recorded)}")
    failed = 0
    for entry in recorded:
        date, status = live_expiry(entry, environ)
        value = f"expires={date or 'none'} status={_status_word(status)} recorded={stamp}"
        try:
            set_repo_variable(gh_token, repo, f"{RECORDED_PREFIX}{entry['name']}", value)
            print(f"  {RECORDED_PREFIX}{entry['name']}: {value}")
        except Exception as exc:  # noqa: BLE001, the type alone, an exception's text could carry a request's details
            print(f"  {RECORDED_PREFIX}{entry['name']}: FAILED, {type(exc).__name__}")
            failed += 1
    return 1 if failed else 0


def _read_fact(raw: str) -> dict[str, str] | None:
    """
    A recorded expiry fact read whole, or None when any part of it is not as `cmd_record_expiry` writes it.

    Exactly `expires`, `status` and `recorded`, each once, a known status, the recording time a UTC time, and a date
    when the status is `ok` or `none` otherwise, so no malformed, repeated or inconsistent fact reads as healthy.

    Args:
        raw: The variable's value

    Returns:
        The three fields, or None
    """
    fact: dict[str, str] = {}
    for part in raw.split():
        key, sep, value = part.partition("=")
        if not sep or not value or key in fact or key not in ("expires", "status", "recorded"):
            return None
        fact[key] = value
    if len(fact) != 3 or fact["status"] not in FACT_STATUSES:
        return None
    try:
        datetime.strptime(fact["recorded"], "%Y-%m-%dT%H:%M:%SZ")
        if fact["status"] == "ok":
            datetime.strptime(fact["expires"], "%Y-%m-%d")
        elif fact["expires"] != "none":
            return None
    except ValueError:
        return None
    return fact


def _check_recorded(entry: dict, environ: dict[str, str] | None = None) -> int:
    """
    The weekly check of a token whose expiry the ops run records, read from that fact and never the registry's date.

    Args:
        entry: The secret's registry entry, marked `check.recorded`
        environ: Where the fact is read, this process's environment when None

    Returns:
        0 when the fact is healthy, 1 when it is missing, unreadable, rejected or near its expiry
    """
    env  = os.environ if environ is None else environ
    name = entry["name"]
    raw  = env.get(f"{RECORDED_PREFIX}{name}", "").strip()
    if not raw:
        print(
            f"  {name}: no recorded expiry yet. A distribution from its staging slot records it, or Rotate Vercel "
            "Deployment Token's record-expiry for a token that run reads."
        )
        return 1
    fact = _read_fact(raw)
    if fact is None:
        print(f"  {name}: ERROR — the recorded fact {RECORDED_PREFIX}{name} is one the check cannot read.")
        return 1
    when = f"recorded {fact['recorded']}"
    if fact["status"] == "rejected":
        print(f"  {name}: REJECTED by its provider when {when}, it is expired or revoked. Rotate now.")
        return 1
    if fact["status"] == "no-expiry":
        print(f"  {name}: OK — its provider reported no expiry ({when}).")
        return 0
    if fact["status"] != "ok":
        print(f"  {name}: ERROR — no date was read when {when}, the read said {fact['status']}.")
        return 1
    expiry    = datetime.strptime(fact["expires"], "%Y-%m-%d").replace(tzinfo = timezone.utc)
    warn_days = (entry.get("check") or {}).get("warn_days_before_expiry", 14)
    days      = (expiry - datetime.now(timezone.utc)).days
    if days < 0:
        print(f"  {name}: EXPIRED {(-days)} day(s) ago ({fact['expires']}, {when}). Rotate now.")
        return 1
    if days <= warn_days:
        print(f"  {name}: WARNING — expires in {days} day(s) ({fact['expires']}, {when}, threshold {warn_days}).")
        return 1
    print(f"  {name}: OK — valid for {days} more day(s) (expires {fact['expires']}, {when}).")
    return 0

# ======================================================================================================================
# Mode: generate
# ======================================================================================================================

def _gen_value() -> str:
    return _secrets.token_urlsafe(32)


def _reap_old_vercel_tokens(
    master_token: str,
    all_tokens: list[dict],
    token_name: str,
    new_id: str,
    errors: list[str],
    label: str,
) -> None:
    """
    Delete EVERY existing Vercel token named ``token_name`` except ``new_id``.

    Vercel allows several tokens to share a display name, so a name->id map would silently miss
    duplicates (left over from a prior partial-failure run that kept the old token, an operator-seeded
    token, or a re-run). A delete failure is a **soft error** — the new token is already live, so a
    failed cleanup must never crash the run or abort the rest of the rotation.
    """
    for t in all_tokens:
        if t.get("name") == token_name and t.get("id") != new_id:
            try:
                delete_vercel_token(master_token, t["id"])
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{label}: delete old '{token_name}' (id={t['id']}): {exc}")


def _generate_vercel_token_secret(
    entry: dict,
    apps: frozenset[str],
    envs: frozenset[str],
    master_token: str,
    gh_token: str,
    team_id: str = "",
) -> list[str]:
    """
    Mint Vercel token(s) and write them to the GitHub env secret targets.

    A ``"shared": true`` entry mints ONE token (entry-level ``vercel_token_name``) and writes the
    same value to every target — easier to manage than one token per repo. Otherwise the default
    is one unique token per target (keyed by each target's ``vercel_token_name``). ``team_id`` scopes
    the minted token to a Vercel team (required for team projects).
    """
    if entry.get("shared"):
        return _generate_shared_vercel_token(entry, apps, envs, master_token, gh_token, team_id)

    errors: list[str] = []
    targets = _gh_targets(entry, apps, envs)
    if not targets:
        print(f"  {entry['name']}: no targets matched the app/env filter — skipped.")
        return errors
    all_tokens = list_vercel_tokens(master_token)
    for t in targets:
        token_name = t["vercel_token_name"]
        label      = f"{token_name} -> {t['repo']} [{t['environment']}] {t['secret_name']}"
        print(f"  {label}", end = " ... ", flush = True)
        try:
            new_id, new_value = create_vercel_token(master_token, token_name, team_id)
            update_github_env_secret(gh_token, t["repo"], t["environment"], t["secret_name"], new_value)
            print("OK")
        except VercelMasterScopeError:
            raise  # surfaced cleanly by cmd_generate — a config error, not a per-target failure
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED - {exc}")
            errors.append(f"{label}: {exc}")
            continue
        # New token is live; clean up old same-named tokens best-effort (never crashes the run).
        _reap_old_vercel_tokens(master_token, all_tokens, token_name, new_id, errors, label)
    return errors


def _generate_shared_vercel_token(
    entry: dict,
    apps: frozenset[str],
    envs: frozenset[str],
    master_token: str,
    gh_token: str,
    team_id: str = "",
) -> list[str]:
    """
    Mint ONE Vercel token and fan the same value out to every target.

    A shared token is a single value everywhere, so app/env filters are ignored (a partial write
    would leave repos out of sync). The previous token(s) of the same name are deleted only if EVERY
    write succeeded — on any failure both the old and new tokens stay valid, so no repo is left
    holding a revoked token. Cleanup is best-effort (a delete failure is a soft error, never a crash).
    ``team_id`` scopes the minted token to a Vercel team (required for team projects).
    """
    errors: list[str] = []
    env_targets  = entry.get("github_env_secrets", [])
    repo_targets = _gh_repo_targets(entry)
    total        = len(env_targets) + len(repo_targets)
    if total == 0:
        print(f"  {entry['name']}: no targets — skipped.")
        return errors
    if apps or envs:
        print(f"  {entry['name']}: shared token — ignoring app/env filter; writing all {total} target(s).")
    token_name = entry.get("vercel_token_name")
    if not token_name:
        return [f"{entry['name']}: shared entry is missing the entry-level 'vercel_token_name'."]
    all_tokens = list_vercel_tokens(master_token)
    print(f"  {entry['name']}: minting one shared token '{token_name}' for {total} target(s)")
    try:
        new_id, new_value = create_vercel_token(master_token, token_name, team_id)
    except VercelMasterScopeError:
        raise  # surfaced cleanly by cmd_generate — a config error, not a per-target failure
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED to mint '{token_name}': {exc}")
        return [f"{entry['name']} mint '{token_name}': {exc}"]
    wrote_all = True
    for t in env_targets:
        label = f"{t['repo']} [{t['environment']}] {t['secret_name']}"
        print(f"    {label}", end = " ... ", flush = True)
        try:
            update_github_env_secret(gh_token, t["repo"], t["environment"], t["secret_name"], new_value)
            print("OK")
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED - {exc}")
            errors.append(f"{label}: {exc}")
            wrote_all = False
    for t in repo_targets:
        label = f"{t['repo']} [repo] {t['secret_name']}"
        print(f"    {label}", end = " ... ", flush = True)
        try:
            update_github_repo_secret(gh_token, t["repo"], t["secret_name"], new_value)
            print("OK")
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED - {exc}")
            errors.append(f"{label}: {exc}")
            wrote_all = False
    # Revoke the old token ONLY once the new value is live at every target AND every retired env
    # shadow is gone — otherwise a repo still reading a stale env copy would be left holding a
    # just-revoked token. A failed shadow-delete therefore keeps the previous token valid.
    if wrote_all:
        shadow_failures = _delete_retired_env_secrets(entry, gh_token, errors)
        if shadow_failures == 0:
            _reap_old_vercel_tokens(master_token, all_tokens, token_name, new_id, errors, entry["name"])
        else:
            print(f"  keeping previous '{token_name}' token(s) — a retired env copy still shadows repo-level.")
    else:
        print(f"  keeping previous '{token_name}' token(s) — a write failed, so they stay valid.")
    return errors


def _generate_random_secret(entry: dict, envs: frozenset[str], gh_token: str, master_token: str) -> list[str]:
    """
    A random value (per-environment when per_env) written to all matching targets.
    """
    errors: list[str] = []
    gh = _gh_targets(entry, frozenset(), envs)
    vc = _vercel_targets(entry, envs)
    if not gh and not vc:
        print(f"  {entry['name']}: no targets matched the env filter — skipped.")
        return errors
    per_env = entry.get("per_env", False)
    # one value per environment (per_env) or a single shared value
    value_for: dict[str, str] = {}


    def value(env: str) -> str:
        key = env if per_env else "*"
        if key not in value_for:
            value_for[key] = _gen_value()
        return value_for[key]


    for t in gh:
        label = f"{entry['name']} -> {t['repo']} [{t['environment']}] {t['secret_name']}"
        print(f"  {label}", end = " ... ", flush = True)
        try:
            update_github_env_secret(gh_token, t["repo"], t["environment"], t["secret_name"], value(t["environment"]))
            print("OK")
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED - {exc}")
            errors.append(f"{label}: {exc}")
    if vc:
        if not master_token:
            print(f"  {entry['name']}: VERCEL_MASTER_TOKEN unset — skipping {len(vc)} Vercel target(s).")
        else:
            for t in _actionable_vercel(vc):
                label = f"{entry['name']} -> Vercel {t['project_name']} [{t['environment']}] {t['env_key']}"
                print(f"  {label}", end = " ... ", flush = True)
                try:
                    upsert_vercel_env_var(master_token, t["project_id"], t["env_key"], value(t["environment"]))
                    print("OK")
                except Exception as exc:  # noqa: BLE001
                    print(f"FAILED - {exc}")
                    errors.append(f"{label}: {exc}")
    return errors


def cmd_generate(
    entries: list[dict],
    apps: frozenset[str],
    envs: frozenset[str],
    gh_token: str,
    master_token: str,
    team_id: str = "",
) -> int:
    if not gh_token:
        sys.exit("Error: GH_TOKEN not set.")
    errors: list[str] = []
    for entry in entries:
        _refuse_if_terraform_managed(entry)
        generator = entry.get("generator")
        print(f"Generating {entry['name']} (generator={generator}):")
        if generator == "vercel_token":
            if not master_token:
                sys.exit("Error: VERCEL_MASTER_TOKEN not set (required for vercel_token generation).")
            try:
                errors += _generate_vercel_token_secret(entry, apps, envs, master_token, gh_token, team_id)
            except VercelMasterScopeError as exc:
                sys.exit(f"Error: {exc}")
        elif generator == "random_urlsafe":
            errors += _generate_random_secret(entry, envs, gh_token, master_token)
        else:
            sys.exit(f"Error: '{entry['name']}' has no/unknown generator '{generator}' — cannot generate.")
    return _summary(errors)

# ======================================================================================================================
# Mode: paste
# ======================================================================================================================

def _actionable_vercel(targets: list[dict]) -> list[dict]:
    """
    Vercel targets whose project_id is real and that the registry does not mark inactive, each other one named.
    """
    actionable, skipped = [], []
    for t in targets:
        (skipped if t.get("inactive") or str(t["project_id"]).startswith("TODO") else actionable).append(t)
    for t in skipped:
        print(f"  Skipping Vercel {t['project_name']} — inactive, or no project_id in secret_registry.json")
    return actionable


def _is_project_id(value: object) -> bool:
    """
    Whether a registry value is a real Vercel project id, a string, not blank and no `TODO` placeholder.

    Args:
        value: The target's `project_id`

    Returns:
        True for a real id
    """
    return isinstance(value, str) and bool(value.strip()) and not value.startswith("TODO")


def _resolve_vercel(entry: dict, envs: frozenset[str], master_token: str) -> tuple[list[dict], list[dict]]:
    """
    The Vercel targets a paste writes and those the registry marks inactive, refusing before any write a target it
    cannot resolve.

    A target with no project id, or a Vercel target with no master token to write it, would be left on the old value
    while the run said every target was written, so either stops the paste first. A target the registry marks
    `inactive` is named as left unwritten, never counted as written (D-099).

    Args:
        entry: The registry entry being pasted
        envs: The environments the paste names, empty for none
        master_token: The Vercel master token, empty when the run holds none

    Returns:
        The active targets and the inactive ones
    """
    targets    = _vercel_targets(entry, envs)
    active     = [target for target in targets if not target.get("inactive")]
    inactive   = [target for target in targets if target.get("inactive")]
    unresolved = [str(target.get("project_name")) for target in active if not _is_project_id(target.get("project_id"))]
    if unresolved:
        sys.exit(
            f"Error: {entry['name']}'s Vercel target(s) {', '.join(unresolved)} have no project id. Fill each "
            "project_id in secret_registry.json, or mark the target inactive, and nothing is written until then."
        )
    if active and not master_token:
        sys.exit(
            f"Error: VERCEL_MASTER_TOKEN is not set and {entry['name']} has {len(active)} Vercel target(s), so "
            "nothing is written."
        )
    return active, inactive


def _refuse_unless_one_environment(entry: dict, envs: frozenset[str]) -> None:
    """
    Refuse a paste of a secret that lives in environments unless exactly one environment holding it is named.

    A value meant for one environment written to both would put DEV's value in PROD (the secrets fence), so the paste
    of such a secret writes the one environment named, and a copy kept in each is pasted once for each.

    An entry held in repository secrets alone takes no environment, since its repository copies are one global value
    and an environment would narrow its Vercel copies alone, leaving the rotation half done (D-099).

    Args:
        entry: The registry entry being pasted
        envs: The environments the paste names, empty for none
    """
    held = sorted({str(target.get("environment", "")).lower() for target in entry.get("github_env_secrets", [])})
    if not held:
        if envs:
            sys.exit(
                f"Error: {entry['name']} lives in no environment, so its paste names none, and every one of its "
                "targets is written."
            )
        return
    if len(envs) != 1:
        sys.exit(
            f"Error: {entry['name']} lives in environments ({', '.join(held)}), so its paste names exactly one "
            "environment, never both and never none."
        )
    (environment,) = envs
    if environment not in held:
        sys.exit(f"Error: {entry['name']} has no target in environment '{environment}', it lives in {', '.join(held)}.")


def cmd_paste(entry: dict, envs: frozenset[str], gh_token: str, master_token: str, value: str) -> int:
    """
    Write one staged value to one `paste` entry's targets, every refusal before the first write.

    Args:
        entry: The registry entry being pasted
        envs: The one environment named for an entry held in environments, empty otherwise
        gh_token: A token that writes the targets' secrets
        master_token: The Vercel master token, for the entry's Vercel targets
        value: The staged value, never printed

    Returns:
        0 when every active target was written, else 1
    """
    _refuse_unless_paste(entry)
    _refuse_if_terraform_managed(entry)
    _refuse_unless_one_environment(entry, envs)
    if not gh_token:
        sys.exit("Error: GH_TOKEN not set.")
    if not value:
        sys.exit("Error: no staged value, so nothing is written. Stage it in its slot in cicd's ops first.")
    vercel, inactive = _resolve_vercel(entry, envs, master_token)
    errors: list[str] = []
    gh = _gh_targets(entry, frozenset(), envs)
    print(f"Pasting {entry['name']} to {len(gh)} GitHub environment secret(s):")
    for t in gh:
        label = f"{t['repo']} [{t['environment']}] {t['secret_name']}"
        print(f"  {label}", end = " ... ", flush = True)
        try:
            update_github_env_secret(gh_token, t["repo"], t["environment"], t["secret_name"], value)
            print("OK")
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED - {exc}")
            errors.append(f"GitHub {label}: {exc}")

    # Repository-level (Actions) secrets — the ones CI reads when a job declares no
    # `environment:`. Distinct store from the env secrets above; both must be written or
    # CI is stranded on the old token while deploys use the new one (see github_repo_secrets).
    repo_targets = _gh_repo_targets(entry)
    repo_ok      = True
    if repo_targets:
        print(f"\nPasting {entry['name']} to {len(repo_targets)} GitHub repository (CI) secret(s):")
        for t in repo_targets:
            label = f"{t['repo']} [repo] {t['secret_name']}"
            print(f"  {label}", end = " ... ", flush = True)
            try:
                update_github_repo_secret(gh_token, t["repo"], t["secret_name"], value)
                print("OK")
            except Exception as exc:  # noqa: BLE001
                print(f"FAILED - {exc}")
                errors.append(f"GitHub {label}: {exc}")
                repo_ok = False

    # Reap retired env-level copies once the repo-level value is confirmed written — a leftover
    # env secret would shadow it (env wins over repo). If a repo write failed, keep the env copy.
    if entry.get("retired_github_env_secrets"):
        if repo_ok:
            _delete_retired_env_secrets(entry, gh_token, errors)
        else:
            print("  skipping retired env-secret cleanup — a repository write failed; env copy left in place.")

    if vercel:
        print(f"\nPasting to {len(vercel)} Vercel project(s):")
    for t in vercel:
        label = f"{t['project_name']} [{t['environment']}] {t['env_key']}"
        print(f"  {label}", end = " ... ", flush = True)
        try:
            upsert_vercel_env_var(master_token, t["project_id"], t["env_key"], value)
            print("OK")
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED - {exc}")
            errors.append(f"Vercel {label}: {exc}")
    return _summary(errors, [f"Vercel {target['project_name']} [{target['environment']}]" for target in inactive])

# ======================================================================================================================
# Mode: paste-staged
# ======================================================================================================================

def _staged_age_refusal(updated_at: str | None, now: datetime) -> str | None:
    """
    Why a slot's age refuses it, or None when it was set recently enough.

    Args:
        updated_at: When GitHub says the slot was last set, None when it is not set
        now: The run's time

    Returns:
        The reason, or None
    """
    if updated_at is None:
        return "is not set in ops"
    try:
        when = datetime.strptime(updated_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo = timezone.utc)
    except ValueError:
        return "has a time GitHub gave that cannot be read"
    if now - when > timedelta(days = STAGED_MAX_AGE_DAYS):
        return (
            f"was set {(now - when).days} days ago, more than {STAGED_MAX_AGE_DAYS}, so it may be a value left from an "
            "earlier rotation. Stage it again"
        )
    return None


def _record_staged_expiry(entry: dict, facts_token: str, repo: str, value: str, now: datetime) -> bool:
    """
    Read a distributed token's expiry live from the value itself and keep it as its fact, true only when both worked.

    A read that failed would leave the expiry unknown, and the run holds the one copy of the value it can read again,
    so the slot stays until the read and the write both succeed (Codex's second read of D-099). A token its provider
    says has no expiry is a fact read whole.

    Args:
        entry: The registry entry, marked `check.recorded`
        facts_token: A token that writes cicd's variables, empty when none was minted
        repo: cicd, owner/name
        value: The token just distributed, never printed
        now: The time recorded

    Returns:
        True when the expiry was read and its fact written
    """
    if not facts_token:
        print(f"  {RECORDED_PREFIX}{entry['name']}: NOT recorded, no token writes cicd's variables")
        return False
    date, status = live_expiry(entry, {entry["name"]: value})
    word = _status_word(status)
    if word not in ("ok", "no-expiry"):
        print(f"  {RECORDED_PREFIX}{entry['name']}: NOT recorded, its expiry could not be read, {word}")
        return False
    fact = f"expires={date or 'none'} status={word} recorded={now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    try:
        set_repo_variable(facts_token, repo, f"{RECORDED_PREFIX}{entry['name']}", fact)
    except Exception as exc:  # noqa: BLE001, the type alone, an exception's text could carry a request's details
        print(f"  {RECORDED_PREFIX}{entry['name']}: NOT recorded, {type(exc).__name__}")
        return False
    print(f"  {RECORDED_PREFIX}{entry['name']}: {fact}")
    return True


def _preflight_slot(
    slot: str,
    entry: dict,
    environment: str,
    environ: dict[str, str],
    gh_token: str,
    master_token: str,
    repo: str,
    now: datetime,
) -> str | None:
    """
    Why one selected slot is not ready, or None when it is, every check the paste would make and its age.

    Args:
        slot: The slot's name
        entry: Its registry entry
        environment: The one environment it feeds, empty for a repository held entry
        environ: Where the slot's value is read
        gh_token: A token that reads cicd's ops secrets
        master_token: The Vercel master token
        repo: cicd, owner/name
        now: The run's time

    Returns:
        The reason, or None
    """
    envs = frozenset({environment}) if environment else frozenset()
    try:
        _refuse_unless_paste(entry)
        _refuse_if_terraform_managed(entry)
        _refuse_unless_one_environment(entry, envs)
        _resolve_vercel(entry, envs, master_token)
    except SystemExit as exc:
        return str(exc.code).removeprefix("Error: ")
    if not environ.get(slot, ""):
        return "is not set in this run, stage it in ops first"
    try:
        updated_at = github_env_secret_updated_at(gh_token, repo, OPS_ENVIRONMENT, slot)
    except Exception as exc:  # noqa: BLE001, the type alone, an exception's text could carry a request's details
        return f"its age could not be read, {type(exc).__name__}"
    return _staged_age_refusal(updated_at, now)


def cmd_paste_staged(
    registry: dict,
    selected: list[str],
    gh_token: str,
    facts_token: str,
    master_token: str,
    repo: str,
    environ: dict[str, str] | None = None,
    now: datetime | None = None,
) -> int:
    """
    Distribute the staging slots the owner selected, each to its own entry's targets (D-099).

    Every selected slot is checked first, a `paste` entry's, set in this run and in ops, set within
    STAGED_MAX_AGE_DAYS, and every target resolved, and one not ready stops the run before anything is written. Then
    each is pasted, a recorded token's expiry kept as its fact from the value itself, and the slot deleted from ops
    once its targets are written and its expiry read and recorded, so a set slot always means a value whose
    distribution is not finished. A slot whose paste failed, or whose expiry could not be read or recorded, is kept for
    a retry, since it holds the one copy the run can read again, and the others go on.

    Args:
        registry: The parsed registry
        selected: The slots' names
        gh_token: A token that writes the targets' secrets, and reads and deletes cicd's ops secrets
        facts_token: A token that writes cicd's variables, empty when none was minted
        master_token: The Vercel master token
        repo: cicd, owner/name
        environ: Where each slot's value is read, this process's environment when None
        now: The run's time, the clock's when None

    Returns:
        0 when every selected slot was written, its fact recorded where its entry is recorded, and deleted, else 1
    """
    env   = os.environ if environ is None else environ
    when  = now or datetime.now(timezone.utc)
    known = staging_slots(registry)
    if not selected:
        sys.exit("Error: name the slots to distribute, --slots NAME[,NAME].")
    unknown = sorted(slot for slot in selected if slot not in known)
    if unknown:
        sys.exit(f"Error: no staging slot named {', '.join(unknown)}. The slots are {', '.join(sorted(known))}.")
    if len(set(selected)) != len(selected):
        sys.exit("Error: a slot is named twice.")
    if not gh_token or not repo:
        sys.exit("Error: GH_TOKEN and GITHUB_REPOSITORY are needed to distribute the staged slots.")

    print(f"Checking {len(selected)} staged slot(s) before anything is written:")
    not_ready = []
    for slot in selected:
        entry, environment = known[slot]
        why = _preflight_slot(slot, entry, environment, env, gh_token, master_token, repo, when)
        print(f"  {slot}: " + ("ready" if why is None else f"NOT READY, {why}"))
        if why is not None:
            not_ready.append(slot)
    if not_ready:
        print(f"\nNothing written, {len(not_ready)} slot(s) not ready: {', '.join(not_ready)}.")
        return 1

    results: dict[str, str] = {}
    for slot in selected:
        entry, environment = known[slot]
        envs = frozenset({environment}) if environment else frozenset()
        print(f"\n== {slot}, to {entry['name']}" + (f" in {environment}" if environment else ""))
        if cmd_paste(entry, envs, gh_token, master_token, env[slot]) != 0:
            results[slot] = "FAILED, the slot is kept for a retry"
            continue
        recorded = True
        if (entry.get("check") or {}).get("recorded"):
            recorded = _record_staged_expiry(entry, facts_token, repo, env[slot], when)
        if not recorded:
            # the slot holds the one copy of the value the run can read again, the npm token's above all, so it stays
            # until its expiry is recorded
            results[slot] = "written, its expiry NOT recorded, the slot is kept, dispatch it again to record it"
            continue
        try:
            delete_github_env_secret(gh_token, repo, OPS_ENVIRONMENT, slot)
            results[slot] = "written, the slot deleted"
        except Exception as exc:  # noqa: BLE001, the type alone, an exception's text could carry a request's details
            results[slot] = f"written, the slot NOT deleted, {type(exc).__name__}, delete it by hand"

    print("\nThe staged slots:")
    for slot in selected:
        print(f"  {slot}: {results[slot]}")
    return 0 if all(result == "written, the slot deleted" for result in results.values()) else 1

# ======================================================================================================================
# Mode: prove-master
# ======================================================================================================================

def cmd_prove_master(master_token: str, team_id: str) -> int:
    """
    Prove the master token can mint, by minting a throwaway token and deleting it at once.

    The sitting makes a fresh master token straight into ops, and this run is what shows it works before anything
    depends on it. The throwaway's value is never printed.

    Args:
        master_token: The Vercel master token
        team_id: The team the throwaway is scoped to, as the rotation scopes its token

    Returns:
        0 when the mint and the delete both succeeded, else 1
    """
    if not master_token:
        sys.exit("Error: VERCEL_MASTER_TOKEN not set.")
    try:
        token_id, _value = create_vercel_token(master_token, PROVE_MASTER_TOKEN_NAME, team_id)
    except Exception as exc:  # noqa: BLE001, the type alone, an exception's text could carry a request's details
        print(f"The master token could not mint a throwaway token, {type(exc).__name__}.")
        return 1
    print(f"Minted the throwaway token {PROVE_MASTER_TOKEN_NAME}, id {token_id}.")
    try:
        delete_vercel_token(master_token, token_id)
    except Exception as exc:  # noqa: BLE001
        print(f"The throwaway token {token_id} was not deleted, {type(exc).__name__}. Delete it in Vercel by hand.")
        return 1
    print(f"Deleted it. PROVED, the master token mints and deletes.")
    return 0

# ======================================================================================================================
# Shared summary
# ======================================================================================================================

def _summary(errors: list[str], inactive: list[str] | None = None) -> int:
    """
    The run's last lines, each failed target, then each target left unwritten because the registry marks it inactive.

    Args:
        errors: Each failed target and why
        inactive: Each target left unwritten on purpose, never counted as written

    Returns:
        1 when a target failed, else 0
    """
    print()
    if errors:
        print(f"{len(errors)} target(s) failed:")
        for e in errors:
            print(f"  - {e}")
    if inactive:
        print(f"{len(inactive)} inactive target(s) left unwritten, as the registry marks them:")
        for target in inactive:
            print(f"  - {target}")
    if errors:
        return 1
    print("All active targets updated successfully." if inactive else "All targets updated successfully.")
    return 0

# ======================================================================================================================
# CLI
# ======================================================================================================================

def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description = "Rotate CI-plane secrets across GitHub env secrets + Vercel projects.",
        formatter_class = argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        required = True,
        choices = ["generate", "paste", "paste-staged", "check", "record-expiry", "prove-master"],
    )
    parser.add_argument(
        "--secrets",
        default = "all",
        help = 'Comma-separated secret names, or "all". Paste mode requires exactly one.',
    )
    parser.add_argument(
        "--slots",
        default = "",
        help = "paste-staged, the staging slots to distribute, comma separated",
    )
    parser.add_argument("--apps", default = "all", help = 'Vercel app filter for generate, or "all".')
    parser.add_argument("--envs", default = "all", help = 'Environment filter (prod,dev,infra), or "all".')
    parser.add_argument(
        "--live",
        action = "store_true",
        help = "check mode, read each secret's real expiry from its provider where check.live says how (D-049).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args     = parse_cli_args(argv)
    registry = _load_registry()
    names    = _parse_filter(args.secrets)
    apps     = _parse_filter(args.apps)
    envs     = _parse_filter(args.envs)

    gh_token     = os.environ.get("GH_TOKEN", "").strip()
    master_token = os.environ.get("VERCEL_MASTER_TOKEN", "").strip()
    team_id      = os.environ.get("VERCEL_TEAM_ID", "").strip()
    staged_value = os.environ.get("STAGED_SECRET_VALUE", "")

    if args.mode == "paste-staged":
        slots = [slot.strip().upper() for slot in args.slots.replace(",", " ").split() if slot.strip()]
        sys.exit(cmd_paste_staged(
            registry,
            slots,
            gh_token,
            os.environ.get("FACTS_GH_TOKEN", "").strip(),
            master_token,
            os.environ.get("GITHUB_REPOSITORY", "").strip(),
        ))

    entries = _select_secrets(registry, names)

    if args.mode == "check":
        sys.exit(cmd_check(entries, live = args.live))

    if args.mode == "record-expiry":
        # Read each recorded token live in ops and keep its expiry as a cicd repository variable.
        sys.exit(cmd_record_expiry(entries, gh_token, os.environ.get("GITHUB_REPOSITORY", "").strip()))

    if args.mode == "prove-master":
        sys.exit(cmd_prove_master(master_token, team_id))

    if args.mode == "generate":
        # A Vercel token minted without a team is personal-account-scoped, and Vercel rejects it
        # ("The specified token is not valid") for team projects — so require the team id up front.
        if any(e.get("generator") == "vercel_token" for e in entries) and not team_id:
            sys.exit(
                "Error: VERCEL_TEAM_ID not set — required to mint team-scoped Vercel tokens (a "
                "personal-scoped token is rejected by Vercel for team projects). Set the VERCEL_TEAM_ID "
                "repo variable to your Vercel team id (the same value as VERCEL_ORG_ID)."
            )
        sys.exit(cmd_generate(entries, apps, envs, gh_token, master_token, team_id))

    # paste
    if len(entries) != 1:
        sys.exit("Error: paste mode requires exactly one secret (use --secrets NAME).")
    sys.exit(cmd_paste(entries[0], envs, gh_token, master_token, staged_value))


if __name__ == "__main__":
    main()
