"""
Rotate per app Vercel tokens and update corresponding GitHub environment secrets.

Each Vercel token maps 1:1 to one GitHub repo+environment + secret via
scripts/vercel_token_registry.json. The script:
	1. Creates a new Vercel token (with TOKEN_EXPIRY_DAYS expiry)
	2. Encrypts it with target repo's public key
	3. Writes it to GitHub environment secret
	4. Deletes old Vercel token

If any entry fails, the script continues, then exits non-zero so the CI job
shows as failed and you get a notification.

Requirements (install before running):
    pip install requests PyNaCl

Environment variables:
    VERCEL_MASTER_TOKEN — Vercel API token that can create/delete tokens. Store as a repo-level secret in kriegerdataforge-cicd.
    GH_TOKEN            — GitHub PAT with secrets:write on all target repos. Use existing CICD_PAT value.

Usage examples:
    # Rotate everything (default, used by scheduled run)
    python rotate_vercel_tokens.py

    # Rotate only the fitness frontend tokens (both envs)
    python rotate_vercel_tokens.py --apps fitness-frontend

    # Rotate prod tokens for fitness frontend and auth backend
    python rotate_vercel_tokens.py --apps fitness-frontend,auth-backend --envs prod

    # Rotate all dev tokens across every app
    python rotate_vercel_tokens.py --envs dev

    # Rotate a single specific token
    python rotate_vercel_tokens.py --apps tiffanys-frontend --envs prod

Available app names  (from vercel_token_registry.json "app" field):
    auth-backend, fitness-frontend, tiffanys-frontend, infra

Available environment names:
    prod, dev, infra
"""

from __future__ import annotations

# standard library imports
import argparse
import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# third party imports
import requests

# PyNaCl (for GitHub secret encryption)
from nacl import encoding, public

# ============================================================
# Configuration
# ============================================================

REGISTRY_FILE = Path(__file__).parent / "vercel_token_registry.json"
VERCEL_API = "https://api.vercel.com"
GITHUB_API = "https://api.github.com"

# rotate every 30 days
# tokens expire after 35 days as a hard safety cutoff
# if rotation fails one month, the token remains valid for 5 extra days
TOKEN_EXPIRY_DAYS = 35

# ============================================================
# Vercel helpers
# ============================================================

def _vercel_headers(token: str) -> dict[str, str]:
    """
    Return headers for Vercel API requests authenticated with given token.
    
    Args:
		token: Vercel API token value (not ID)

    Returns:
		Dict of HTTP headers to include in Vercel API requests.
    """
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def create_vercel_token(master_token: str, name: str) -> tuple[str, str]:
    """
    Create a new Vercel API token.

	Args:
		master_token: Vercel API token value (not ID) with permissions to create tokens
		name: Name for the new token (e.g. "fitness-frontend-prod"). If a token with this name already exists, it is not deleted automatically — caller should delete old tokens after creating the new one to avoid downtime
		
    Returns:
        (token_id, token_value)
    """
    expires_at_ms = int(
        (datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRY_DAYS)).timestamp()
        * 1000
    )
    resp = requests.post(
        f"{VERCEL_API}/v3/user/tokens",
        headers=_vercel_headers(master_token),
        json={"name": name, "expiresAt": expires_at_ms},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["token"]["id"], data["token"]["token"]


def list_vercel_tokens(master_token: str) -> list[dict]:
    """
    Return all Vercel tokens visible to master_token.

    Args:
		master_token: Vercel API token value (not ID) with permissions to list tokens

    Returns:
		List of tokens, each a dict with at least "id" and "name" keys
    """
    resp = requests.get(
        f"{VERCEL_API}/v3/user/tokens",
        headers=_vercel_headers(master_token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("tokens", [])


def delete_vercel_token(master_token: str, token_id: str) -> None:
    """
    Delete a Vercel token by its ID.
    
    Args:
		master_token: Vercel API token value (not ID) with permissions to delete tokens
		token_id: ID of the token to delete (not the token value)

    Returns:
		None. Raises an exception if deletion fails.
    """
    resp = requests.delete(
        f"{VERCEL_API}/v3/user/tokens/{token_id}",
        headers=_vercel_headers(master_token),
        timeout=30,
    )
    resp.raise_for_status()

# ============================================================
# GitHub helpers
# ============================================================

def _github_headers(token: str) -> dict[str, str]:
    """
    Return headers for GitHub API requests authenticated with given token.
    
    Args:
		token: GitHub API token value (PAT)

    Returns:
		Dict of HTTP headers to include in GitHub API requests
    """
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
    """
    Return (key_id, base64_public_key) for the given environment.

    Args:
        gh_token: GitHub API token value (PAT)
        owner: Repository owner
        repo: Repository name
        environment: Environment name

    Returns:
        Tuple of (key_id, base64_public_key)
    """
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/environments/{environment}/secrets/public-key",
        headers=_github_headers(gh_token),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["key_id"], data["key"]


def _encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    """
    Encrypt secret_value with the repo's libsodium public key.

    Args:
        public_key_b64: Base64-encoded public key
        secret_value: Secret value to encrypt

    Returns:
        Base64-encoded encrypted secret
    """
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
    """
    Update a GitHub environment secret with a new value.

    Args:
        gh_token: GitHub API token value (PAT)
        owner_repo: Repository owner and name in the format "owner/repo"
        environment: Environment name
        secret_name: Name of the secret to update
        secret_value: New value for the secret

    Returns:
        None

    Raises:
		HTTPError if the API request fails (e.g. due to permissions or non-existent repo/env/secret)
    """
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
# Filtering
# ============================================================

def _parse_filter(raw: str) -> frozenset[str]:
    """
    Return an empty frozenset (match all) or a set of lowercased names.
    Args:
        raw: Comma-separated string of names, or "all"/empty for no filtering

    Returns:
        frozenset of lowercased names, or empty frozenset if no filtering
    """
    stripped = raw.strip().lower()
    if stripped in ("", "all"):
        return frozenset()
    return frozenset(part.strip() for part in stripped.split(",") if part.strip())

# ============================================================
# CLI
# ============================================================

def parse_cli_args() -> argparse.Namespace:
	"""
	Parse command line arguments for filtering which tokens to rotate.

	Returns:
		argparse.Namespace with 'apps' and 'envs' attributes containing the raw filter strings.
	"""
	parser = argparse.ArgumentParser(
		description="Rotate per-app Vercel tokens and push them to GitHub environment secrets.",
		formatter_class=argparse.RawDescriptionHelpFormatter,
		epilog=(
			"Examples:\n"
			"  # Rotate everything (scheduled monthly run)\n"
			"  python rotate_vercel_tokens.py\n\n"
			"  # Rotate only fitness frontend (both envs)\n"
			"  python rotate_vercel_tokens.py --apps fitness-frontend\n\n"
			"  # Rotate prod tokens for two apps\n"
			"  python rotate_vercel_tokens.py --apps fitness-frontend,auth-backend --envs prod\n\n"
			"  # Rotate all dev tokens\n"
			"  python rotate_vercel_tokens.py --envs dev"
		),
	)
	parser.add_argument(
		"--apps",
		default="all",
		metavar="APP[,APP...]",
		help=(
			'Comma-separated app names to rotate, or "all" (default). '
			"Available: auth-backend, fitness-frontend, tiffanys-frontend, infra"
		),
	)
	parser.add_argument(
		"--envs",
		default="all",
		metavar="ENV[,ENV...]",
		help=(
			'Comma-separated environment names to rotate, or "all" (default). '
			"Available: prod, dev, infra"
		),
	)
	return parser.parse_args()


# ============================================================
# Main
# ============================================================

def main() -> None:
    """
    Main function to rotate Vercel tokens based on command line filters and update GitHub secrets accordingly.
    """
    # grab cli args
    args = parse_cli_args()

	# parse filters into sets for easy membership testing
	# empty set means "match all"
    apps_filter = _parse_filter(args.apps)
    envs_filter = _parse_filter(args.envs)

	# validate environment variables and registry file presence before doing any API calls
    master_token = os.environ.get("VERCEL_MASTER_TOKEN", "").strip()
    gh_token     = os.environ.get("GH_TOKEN", "").strip()

	# if any of these are missing, no point starting rotation process since it will just fail for every token,
	# and we want to avoid creating new Vercel tokens if we won't be able to update GitHub secrets with them
    if not master_token:
        sys.exit("Error: VERCEL_MASTER_TOKEN environment variable not set.")
    if not gh_token:
        sys.exit("Error: GH_TOKEN environment variable not set.")
    if not REGISTRY_FILE.is_file():
        sys.exit(f"Error: registry file not found: {REGISTRY_FILE}")

	# load registry and apply filters to find candidate tokens for rotation
    registry = json.loads(REGISTRY_FILE.read_text())

    # apply filters
    candidates = [
        entry for entry in registry["tokens"]
        if (not apps_filter or entry["app"] in apps_filter)
        and (not envs_filter or entry["environment"] in envs_filter)
    ]

	# if no candidates after filtering, exit with error to avoid silent no-op and to help user debug filter values
    if not candidates:
        filter_desc = []

		# describe filters in error message to help user debug (e.g. typo in app/env name that doesn't match registry)
        if apps_filter:
            filter_desc.append(f"apps={','.join(sorted(apps_filter))}")
        if envs_filter:
            filter_desc.append(f"envs={','.join(sorted(envs_filter))}")

        sys.exit(
            f"Error: no registry entries matched filters ({'; '.join(filter_desc)}).\n"
            f"Check app/env names against vercel_token_registry.json."
        )

    # summarise what will be rotated before touching anything
    filter_parts = []
    if apps_filter:
        filter_parts.append(f"apps=[{', '.join(sorted(apps_filter))}]")
    if envs_filter:
        filter_parts.append(f"envs=[{', '.join(sorted(envs_filter))}]")

    scope = f" ({', '.join(filter_parts)})" if filter_parts else " (all)"
    print(f"Rotating {len(candidates)} token(s){scope}:")

    for entry in candidates:
        print(f"  - {entry['vercel_token_name']}  ->  {entry['repo']} [{entry['environment']}]")
    print()

    # build name -> id map of currently existing Vercel tokens to delete old one after creating its replacement
    existing: dict[str, str] = {
        t["name"]: t["id"] for t in list_vercel_tokens(master_token)
    }

    errors: list[str] = []
    for entry in candidates:
        token_name: str = entry["vercel_token_name"]
        owner_repo: str = entry["repo"]
        environment: str = entry["environment"]
        secret_name: str = entry["secret_name"]

        print(
            f"  Rotating {token_name!r} -> {owner_repo} [{environment}] ...",
            end=" ",
            flush=True,
        )

        try:
			# Step 1: create new token first (GitHub is never left without a valid token)
            new_id, new_value = create_vercel_token(master_token, token_name)

            # Step 2: push new token to GitHub environment secret
            update_github_env_secret(
                gh_token, owner_repo, environment, secret_name, new_value
            )

            # Step 3: delete old token (if it existed under this name before rotation)
            old_id = existing.get(token_name)
            if old_id and old_id != new_id:
                delete_vercel_token(master_token, old_id)

            print("OK")

        except Exception as exc:
            # noqa: BLE001
            print(f"FAILED - {exc}")
            errors.append(f"{token_name}: {exc}")

	# log summary of results and exit with non-zero code if any failures to signal CI job failure and send notification
    print()
    if errors:
        print(f"{len(errors)} rotation(s) failed:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    else:
        print(f"All {len(candidates)} token(s) rotated successfully.")


if __name__ == "__main__":
    main()
