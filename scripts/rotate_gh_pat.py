"""
Check and distribute the GH_PACKAGES_PAT across all GitHub environments and Vercel projects
that need it to build kdf-auth-sdk.

GitHub does not support creating PAT values programmatically, so rotation is semi-automated:
  1. You create a new fine-grained PAT in GitHub UI (github.com/settings/tokens)
  2. Store it as GH_PACKAGES_PAT_NEW in kriegerdataforge-cicd repo-level secrets
  3. Trigger the 'Distribute GH_PACKAGES_PAT' workflow (or run distribute locally)
  4. After distribution, update pat_expiry in scripts/gh_pat_registry.json and commit

Modes:
  check       Reads pat_expiry from the registry; exits non-zero if expiry is within
              warn_days_before_expiry days. Used by the scheduled check workflow — a
              failed workflow sends a GitHub Actions failure notification.
  distribute  Reads GH_PACKAGES_PAT_NEW from env and pushes it to all GitHub environment
              secrets and Vercel project env vars in the registry. Vercel entries whose
              project_id starts with "TODO" are skipped with a warning.

Requirements:
    pip install requests PyNaCl

Environment variables:
  check mode:
    (none — reads from registry file only)

  distribute mode:
    GH_PACKAGES_PAT_NEW    — new PAT value to distribute (required)
    GH_TOKEN               — GitHub PAT with secrets:write on all target repos (required)
                             Use the CICD_PAT value from kriegerdataforge-cicd secrets.
    VERCEL_MASTER_TOKEN    — Vercel API token for setting project env vars (optional;
                             if unset, Vercel distribution is skipped entirely)

Usage:
    python rotate_gh_pat.py check
    python rotate_gh_pat.py distribute
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from nacl import encoding, public

# ============================================================
# Configuration
# ============================================================

REGISTRY_FILE = Path(__file__).parent / "gh_pat_registry.json"
VERCEL_API = "https://api.vercel.com"
GITHUB_API = "https://api.github.com"

# ============================================================
# GitHub helpers  (shared with rotate_vercel_tokens.py)
# ============================================================


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_env_public_key(
    gh_token: str,
    owner: str,
    repo: str,
    environment: str,
) -> tuple[str, str]:
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/environments/{environment}/secrets/public-key",
        headers=_github_headers(gh_token),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["key_id"], data["key"]


def _encrypt_secret(public_key_b64: str, secret_value: str) -> str:
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


def _list_vercel_env_vars(master_token: str, project_id: str) -> list[dict]:
    """Return all env var entries for a Vercel project."""
    resp = requests.get(
        f"{VERCEL_API}/v10/projects/{project_id}/env",
        headers=_vercel_headers(master_token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("envs", [])


def upsert_vercel_env_var(
    master_token: str,
    project_id: str,
    key: str,
    value: str,
) -> None:
    """Create or update all entries for `key` in the given Vercel project.

    If matching entries already exist (one per target environment), each is patched
    in place so existing targets are preserved. If none exist, a new entry covering
    all three environments (production, preview, development) is created.
    """
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
# Registry helpers
# ============================================================


def _load_registry() -> dict:
    if not REGISTRY_FILE.is_file():
        sys.exit(f"Error: registry file not found: {REGISTRY_FILE}")
    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))


# ============================================================
# Modes
# ============================================================


def cmd_check(registry: dict) -> int:
    """Exit 1 if the stored pat_expiry is within warn_days_before_expiry days."""
    expiry_raw: str = registry.get("pat_expiry", "")
    warn_days: int = registry.get("warn_days_before_expiry", 14)

    if not expiry_raw or expiry_raw.startswith("TODO"):
        print("Warning: pat_expiry is not set in gh_pat_registry.json.")
        print("Update it with the expiry date of your current GH_PACKAGES_PAT.")
        return 1

    try:
        expiry = datetime.strptime(expiry_raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        print(f"Error: pat_expiry '{expiry_raw}' is not a valid YYYY-MM-DD date.")
        return 1

    now = datetime.now(timezone.utc)
    days_remaining = (expiry - now).days

    if days_remaining < 0:
        print(f"EXPIRED: GH_PACKAGES_PAT expired {-days_remaining} day(s) ago ({expiry_raw}).")
        print("Create a new fine-grained PAT and run the 'Distribute GH_PACKAGES_PAT' workflow.")
        return 1

    if days_remaining <= warn_days:
        print(
            f"WARNING: GH_PACKAGES_PAT expires in {days_remaining} day(s) ({expiry_raw}). "
            f"Threshold is {warn_days} days."
        )
        print("Create a new fine-grained PAT and run the 'Distribute GH_PACKAGES_PAT' workflow.")
        return 1

    print(f"OK: GH_PACKAGES_PAT is valid for {days_remaining} more day(s) (expires {expiry_raw}).")
    return 0


def cmd_distribute(registry: dict) -> int:
    """Push GH_PACKAGES_PAT_NEW to every GitHub env secret and Vercel project in the registry."""
    new_pat = os.environ.get("GH_PACKAGES_PAT_NEW", "").strip()
    gh_token = os.environ.get("GH_TOKEN", "").strip()
    vercel_token = os.environ.get("VERCEL_MASTER_TOKEN", "").strip()

    if not new_pat:
        sys.exit(
            "Error: GH_PACKAGES_PAT_NEW environment variable not set.\n"
            "Store the new PAT as 'GH_PACKAGES_PAT_NEW' in kriegerdataforge-cicd repo secrets "
            "and re-trigger the workflow."
        )
    if not gh_token:
        sys.exit("Error: GH_TOKEN environment variable not set.")

    if not vercel_token:
        print(
            "Warning: VERCEL_MASTER_TOKEN not set — Vercel project env vars will be SKIPPED.\n"
            "To update Vercel projects, set VERCEL_MASTER_TOKEN and re-run distribute.\n"
        )

    gh_targets: list[dict] = registry.get("github_env_secrets", [])
    vercel_targets: list[dict] = registry.get("vercel_env_vars", [])

    # ── GitHub environment secrets ────────────────────────────────────────────
    print(f"Distributing to {len(gh_targets)} GitHub environment secret(s):")

    errors: list[str] = []

    for t in gh_targets:
        label = f"{t['repo']} [{t['environment']}] → {t['secret_name']}"
        print(f"  {label}", end=" ... ", flush=True)
        try:
            update_github_env_secret(
                gh_token,
                t["repo"],
                t["environment"],
                t["secret_name"],
                new_pat,
            )
            print("OK")
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED — {exc}")
            errors.append(f"GitHub {label}: {exc}")

    # ── Vercel project env vars ───────────────────────────────────────────────
    if vercel_token:
        actionable = [v for v in vercel_targets if not v["project_id"].startswith("TODO")]
        skipped    = [v for v in vercel_targets if v["project_id"].startswith("TODO")]

        if skipped:
            print(f"\nSkipping {len(skipped)} Vercel project(s) with TODO project_id:")
            for v in skipped:
                print(f"  {v['project_name']} — fill in project_id in gh_pat_registry.json")

        if actionable:
            print(f"\nDistributing to {len(actionable)} Vercel project(s):")
            for v in actionable:
                label = f"{v['project_name']} ({v['project_id']}) → {v['env_key']}"
                print(f"  {label}", end=" ... ", flush=True)
                try:
                    upsert_vercel_env_var(vercel_token, v["project_id"], v["env_key"], new_pat)
                    print("OK")
                except Exception as exc:  # noqa: BLE001
                    print(f"FAILED — {exc}")
                    errors.append(f"Vercel {label}: {exc}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    if errors:
        print(f"{len(errors)} target(s) failed:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("All targets updated successfully.")
    print()
    print("ACTION REQUIRED — manual follow-up steps:")
    print("  1. Update 'pat_expiry' in scripts/gh_pat_registry.json to the new token's expiry date (YYYY-MM-DD).")
    print("  2. Commit and push the change.")
    print("  3. Delete the GH_PACKAGES_PAT_NEW secret from kriegerdataforge-cicd repo secrets")
    print("     (Settings → Secrets and variables → Actions → GH_PACKAGES_PAT_NEW → Delete).")
    print("  4. Optionally revoke the old PAT in GitHub: Settings → Developer settings → Fine-grained tokens.")
    return 0


# ============================================================
# CLI
# ============================================================


def parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check expiry or distribute the GH_PACKAGES_PAT.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Check if PAT is expiring soon (used by scheduled workflow)\n"
            "  python rotate_gh_pat.py check\n\n"
            "  # Push new PAT to all GitHub secrets and Vercel projects\n"
            "  GH_PACKAGES_PAT_NEW=ghp_... GH_TOKEN=... python rotate_gh_pat.py distribute"
        ),
    )
    parser.add_argument(
        "mode",
        choices=["check", "distribute"],
        help="'check' reads pat_expiry and exits non-zero if near/past. 'distribute' pushes the new PAT everywhere.",
    )
    return parser.parse_args()


# ============================================================
# Entry point
# ============================================================


def main() -> None:
    args = parse_cli_args()
    registry = _load_registry()

    if args.mode == "check":
        sys.exit(cmd_check(registry))
    else:
        sys.exit(cmd_distribute(registry))


if __name__ == "__main__":
    main()
