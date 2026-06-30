"""
Unified CI-plane secret rotation engine.

One registry (scripts/secret_registry.json) maps each rotatable secret to every place
its value lives — GitHub Actions ENVIRONMENT secrets and/or non-Terraform Vercel project
env vars. This script is the single front-end behind both the scheduled rotation workflows
and the owner-only `ops:rotate-secrets` issue form.

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
  paste      Write an owner-supplied value (staged out-of-band in the STAGED_SECRET_VALUE env,
             never in the public issue body) to every registry target. Single secret only.
  check      Report time-to-expiry for secrets that carry a "check" block (advisory rotation).

Environment variables
  GH_TOKEN              GitHub PAT with secrets:write on all target repos (use CICD_PAT).   [generate/paste]
  VERCEL_MASTER_TOKEN   Vercel API token that can create/delete tokens + set project env.   [vercel_token generate / paste-to-vercel]
  STAGED_SECRET_VALUE   The value to distribute.                                            [paste]

Usage
  python rotate_secret.py --mode check    --secrets all
  python rotate_secret.py --mode generate --secrets VERCEL_TOKEN --apps fitness-frontend --envs prod
  python rotate_secret.py --mode paste    --secrets GH_PACKAGES_PAT          # value from STAGED_SECRET_VALUE
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets as _secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from nacl import encoding, public

# ============================================================
# Configuration
# ============================================================

REGISTRY_FILE = Path(__file__).parent / "secret_registry.json"
VERCEL_API = "https://api.vercel.com"
GITHUB_API = "https://api.github.com"

# New Vercel tokens expire after 45 days. The monthly cron rotates ~every 30 (worst-case 31-day gap),
# leaving ~2 weeks of slack so a single missed run never expires the one shared deploy token.
TOKEN_EXPIRY_DAYS = 45

# ============================================================
# GitHub helpers
# ============================================================


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_env_public_key(gh_token: str, owner: str, repo: str, environment: str) -> tuple[str, str]:
    """Return (key_id, base64_public_key) for a repo environment's secret box."""
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/environments/{environment}/secrets/public-key",
        headers=_github_headers(gh_token),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["key_id"], data["key"]


def _encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    """Seal `secret_value` to the repo's libsodium public key (base64 out)."""
    pub_key = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder)
    sealed = public.SealedBox(pub_key)
    encrypted = sealed.encrypt(secret_value.encode())
    return base64.b64encode(encrypted).decode()


def update_github_env_secret(
    gh_token: str,
    owner_repo: str,
    environment: str,
    secret_name: str,
    secret_value: str,
) -> None:
    """Encrypt + PUT a value into repo `owner_repo`'s environment secret."""
    owner, repo = owner_repo.split("/", 1)
    key_id, pub_key_b64 = _get_env_public_key(gh_token, owner, repo, environment)
    encrypted = _encrypt_secret(pub_key_b64, secret_value)
    resp = requests.put(
        f"{GITHUB_API}/repos/{owner}/{repo}/environments/{environment}/secrets/{secret_name}",
        headers=_github_headers(gh_token),
        json={"encrypted_value": encrypted, "key_id": key_id},
        timeout=30,
    )
    resp.raise_for_status()


# ============================================================
# Vercel helpers
# ============================================================


def _vercel_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


class VercelMasterScopeError(RuntimeError):
    """Raised when the Vercel token API returns 403 — VERCEL_MASTER_TOKEN lacks Full Account scope."""


def _raise_for_token_api(resp: requests.Response) -> None:
    """``raise_for_status`` for the ``/v3/user/tokens`` calls, with a clear hint on 403.

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
    """Create a new Vercel API token (TOKEN_EXPIRY_DAYS expiry). Returns (token_id, token_value).

    When ``team_id`` is set, the token is scoped to that Vercel team (the ``teamId`` query param) so it
    can deploy/manage the team's projects. A token minted WITHOUT a team is personal-account-scoped, and
    Vercel rejects it ("The specified token is not valid") the moment the CLI targets a team project.
    """
    expires_at_ms = int(
        (datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRY_DAYS)).timestamp() * 1000
    )
    resp = requests.post(
        f"{VERCEL_API}/v3/user/tokens",
        headers=_vercel_headers(master_token),
        params={"teamId": team_id} if team_id else None,
        json={"name": name, "expiresAt": expires_at_ms},
        timeout=30,
    )
    _raise_for_token_api(resp)
    data = resp.json()
    return data["token"]["id"], data["bearerToken"]


def list_vercel_tokens(master_token: str) -> list[dict]:
    resp = requests.get(
        f"{VERCEL_API}/v3/user/tokens",
        headers=_vercel_headers(master_token),
        timeout=30,
    )
    _raise_for_token_api(resp)
    return resp.json().get("tokens", [])


def delete_vercel_token(master_token: str, token_id: str) -> None:
    resp = requests.delete(
        f"{VERCEL_API}/v3/user/tokens/{token_id}",
        headers=_vercel_headers(master_token),
        timeout=30,
    )
    _raise_for_token_api(resp)


def _list_vercel_env_vars(master_token: str, project_id: str) -> list[dict]:
    resp = requests.get(
        f"{VERCEL_API}/v10/projects/{project_id}/env",
        headers=_vercel_headers(master_token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("envs", [])


def upsert_vercel_env_var(master_token: str, project_id: str, key: str, value: str) -> None:
    """Patch every existing entry for `key` in place, or create one covering all 3 targets."""
    existing = [e for e in _list_vercel_env_vars(master_token, project_id) if e["key"] == key]
    if existing:
        for entry in existing:
            resp = requests.patch(
                f"{VERCEL_API}/v10/projects/{project_id}/env/{entry['id']}",
                headers=_vercel_headers(master_token),
                json={"value": value, "type": "encrypted", "target": entry["target"]},
                timeout=30,
            )
            resp.raise_for_status()
    else:
        resp = requests.post(
            f"{VERCEL_API}/v10/projects/{project_id}/env",
            headers=_vercel_headers(master_token),
            json={
                "key": key,
                "value": value,
                "type": "encrypted",
                "target": ["production", "preview", "development"],
            },
            timeout=30,
        )
        resp.raise_for_status()


# ============================================================
# Registry + filters
# ============================================================


def _load_registry() -> dict:
    if not REGISTRY_FILE.is_file():
        sys.exit(f"Error: registry file not found: {REGISTRY_FILE}")
    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))


def _parse_filter(raw: str) -> frozenset[str]:
    """Empty / 'all' -> empty frozenset (match all); else a set of lowercased names."""
    stripped = (raw or "").strip().lower()
    if stripped in ("", "all"):
        return frozenset()
    return frozenset(part.strip() for part in stripped.split(",") if part.strip())


def _select_secrets(registry: dict, names: frozenset[str]) -> list[dict]:
    """Registry entries matching `names` (empty = all). Exits if a named secret is unknown."""
    entries = registry.get("secrets", [])
    by_name = {e["name"].lower(): e for e in entries}
    if not names:
        return list(entries)
    unknown = sorted(n for n in names if n not in by_name)
    if unknown:
        known = ", ".join(sorted(by_name))
        sys.exit(f"Error: unknown secret(s): {', '.join(unknown)}. Known: {known}.")
    return [by_name[n] for n in sorted(names)]


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


def _vercel_targets(entry: dict, envs: frozenset[str]) -> list[dict]:
    out = []
    for t in entry.get("vercel_env_vars", []):
        if envs and t.get("environment", "").lower() not in envs:
            continue
        out.append(t)
    return out


# ============================================================
# Mode: check
# ============================================================


def _check_one(entry: dict) -> int:
    """Advisory expiry check for one secret. 0 = ok, 1 = warn/expired/misconfigured/no-check."""
    name = entry["name"]
    chk = entry.get("check")
    if not chk:
        print(f"  {name}: no expiry tracked (nothing to check).")
        return 0
    expiry_raw = chk.get("expiry", "")
    warn_days = chk.get("warn_days_before_expiry", 14)
    if not expiry_raw or str(expiry_raw).startswith("TODO"):
        print(f"  {name}: WARNING — expiry not set in the registry.")
        return 1
    try:
        expiry = datetime.strptime(expiry_raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        print(f"  {name}: ERROR — expiry '{expiry_raw}' is not YYYY-MM-DD.")
        return 1
    days = (expiry - datetime.now(timezone.utc)).days
    if days < 0:
        print(f"  {name}: EXPIRED {(-days)} day(s) ago ({expiry_raw}). Rotate now.")
        return 1
    if days <= warn_days:
        print(f"  {name}: WARNING — expires in {days} day(s) ({expiry_raw}, threshold {warn_days}).")
        return 1
    print(f"  {name}: OK — valid for {days} more day(s) (expires {expiry_raw}).")
    return 0


def cmd_check(entries: list[dict]) -> int:
    print(f"Checking expiry for {len(entries)} secret(s):")
    needs: list[str] = []
    for entry in entries:
        if _check_one(entry) != 0:
            needs.append(entry["name"])
    print()
    # Machine-readable line the scheduled monitor greps to build/close the rotation issue.
    print("NEEDS_ROTATION: " + ",".join(needs))
    return 1 if needs else 0


# ============================================================
# Mode: generate
# ============================================================


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
    """Delete EVERY existing Vercel token named ``token_name`` except ``new_id``.

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
    entry: dict, apps: frozenset[str], envs: frozenset[str], master_token: str, gh_token: str,
    team_id: str = "",
) -> list[str]:
    """Mint Vercel token(s) and write them to the GitHub env secret targets.

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
        label = f"{token_name} -> {t['repo']} [{t['environment']}] {t['secret_name']}"
        print(f"  {label}", end=" ... ", flush=True)
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
    entry: dict, apps: frozenset[str], envs: frozenset[str], master_token: str, gh_token: str,
    team_id: str = "",
) -> list[str]:
    """Mint ONE Vercel token and fan the same value out to every target.

    A shared token is a single value everywhere, so app/env filters are ignored (a partial write
    would leave repos out of sync). The previous token(s) of the same name are deleted only if EVERY
    write succeeded — on any failure both the old and new tokens stay valid, so no repo is left
    holding a revoked token. Cleanup is best-effort (a delete failure is a soft error, never a crash).
    ``team_id`` scopes the minted token to a Vercel team (required for team projects).
    """
    errors: list[str] = []
    targets = entry.get("github_env_secrets", [])
    if not targets:
        print(f"  {entry['name']}: no targets — skipped.")
        return errors
    if apps or envs:
        print(f"  {entry['name']}: shared token — ignoring app/env filter; writing all {len(targets)} target(s).")
    token_name = entry.get("vercel_token_name")
    if not token_name:
        return [f"{entry['name']}: shared entry is missing the entry-level 'vercel_token_name'."]
    all_tokens = list_vercel_tokens(master_token)
    print(f"  {entry['name']}: minting one shared token '{token_name}' for {len(targets)} target(s)")
    try:
        new_id, new_value = create_vercel_token(master_token, token_name, team_id)
    except VercelMasterScopeError:
        raise  # surfaced cleanly by cmd_generate — a config error, not a per-target failure
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED to mint '{token_name}': {exc}")
        return [f"{entry['name']} mint '{token_name}': {exc}"]
    wrote_all = True
    for t in targets:
        label = f"{t['repo']} [{t['environment']}] {t['secret_name']}"
        print(f"    {label}", end=" ... ", flush=True)
        try:
            update_github_env_secret(gh_token, t["repo"], t["environment"], t["secret_name"], new_value)
            print("OK")
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED - {exc}")
            errors.append(f"{label}: {exc}")
            wrote_all = False
    if wrote_all:
        _reap_old_vercel_tokens(master_token, all_tokens, token_name, new_id, errors, entry["name"])
    else:
        print(f"  keeping previous '{token_name}' token(s) — a write failed, so they stay valid.")
    return errors


def _generate_random_secret(
    entry: dict, envs: frozenset[str], gh_token: str, master_token: str
) -> list[str]:
    """A random value (per-environment when per_env) written to all matching targets."""
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
        print(f"  {label}", end=" ... ", flush=True)
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
                print(f"  {label}", end=" ... ", flush=True)
                try:
                    upsert_vercel_env_var(master_token, t["project_id"], t["env_key"], value(t["environment"]))
                    print("OK")
                except Exception as exc:  # noqa: BLE001
                    print(f"FAILED - {exc}")
                    errors.append(f"{label}: {exc}")
    return errors


def cmd_generate(
    entries: list[dict], apps: frozenset[str], envs: frozenset[str], gh_token: str, master_token: str,
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


# ============================================================
# Mode: paste
# ============================================================


def _actionable_vercel(targets: list[dict]) -> list[dict]:
    """Vercel targets whose project_id is real (skip TODO placeholders with a warning)."""
    actionable, skipped = [], []
    for t in targets:
        (skipped if str(t["project_id"]).startswith("TODO") else actionable).append(t)
    for t in skipped:
        print(f"  Skipping Vercel {t['project_name']} — fill in project_id in secret_registry.json")
    return actionable


def cmd_paste(entry: dict, envs: frozenset[str], gh_token: str, master_token: str, value: str) -> int:
    _refuse_if_terraform_managed(entry)
    if not gh_token:
        sys.exit("Error: GH_TOKEN not set.")
    if not value:
        sys.exit(
            "Error: STAGED_SECRET_VALUE not set — stage the value in the SECRET_VALUE_NEW repo "
            "secret first (never put a secret value in the public issue body)."
        )
    errors: list[str] = []
    gh = _gh_targets(entry, frozenset(), envs)
    print(f"Pasting {entry['name']} to {len(gh)} GitHub environment secret(s):")
    for t in gh:
        label = f"{t['repo']} [{t['environment']}] {t['secret_name']}"
        print(f"  {label}", end=" ... ", flush=True)
        try:
            update_github_env_secret(gh_token, t["repo"], t["environment"], t["secret_name"], value)
            print("OK")
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED - {exc}")
            errors.append(f"GitHub {label}: {exc}")

    vc = _vercel_targets(entry, envs)
    if vc:
        if not master_token:
            print(f"\nVERCEL_MASTER_TOKEN unset — skipping {len(vc)} Vercel target(s).")
        else:
            actionable = _actionable_vercel(vc)
            if actionable:
                print(f"\nPasting to {len(actionable)} Vercel project(s):")
            for t in actionable:
                label = f"{t['project_name']} [{t['environment']}] {t['env_key']}"
                print(f"  {label}", end=" ... ", flush=True)
                try:
                    upsert_vercel_env_var(master_token, t["project_id"], t["env_key"], value)
                    print("OK")
                except Exception as exc:  # noqa: BLE001
                    print(f"FAILED - {exc}")
                    errors.append(f"Vercel {label}: {exc}")
    return _summary(errors)


# ============================================================
# Shared summary
# ============================================================


def _summary(errors: list[str]) -> int:
    print()
    if errors:
        print(f"{len(errors)} target(s) failed:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("All targets updated successfully.")
    return 0


# ============================================================
# CLI
# ============================================================


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rotate CI-plane secrets across GitHub env secrets + Vercel projects.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mode", required=True, choices=["generate", "paste", "check"])
    parser.add_argument(
        "--secrets",
        default="all",
        help='Comma-separated secret names, or "all". Paste mode requires exactly one.',
    )
    parser.add_argument("--apps", default="all", help='Vercel app filter for generate, or "all".')
    parser.add_argument("--envs", default="all", help='Environment filter (prod,dev,infra), or "all".')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_cli_args(argv)
    registry = _load_registry()
    names = _parse_filter(args.secrets)
    apps = _parse_filter(args.apps)
    envs = _parse_filter(args.envs)

    gh_token = os.environ.get("GH_TOKEN", "").strip()
    master_token = os.environ.get("VERCEL_MASTER_TOKEN", "").strip()
    team_id = os.environ.get("VERCEL_TEAM_ID", "").strip()
    staged_value = os.environ.get("STAGED_SECRET_VALUE", "")

    entries = _select_secrets(registry, names)

    if args.mode == "check":
        sys.exit(cmd_check(entries))

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
