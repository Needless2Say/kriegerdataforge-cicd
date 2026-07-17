"""
check_oidc_drift.py — PL-084/HYG-3 interim OIDC-RP drift guard.

The OIDC relying-party core (PKCE/state/nonce helpers + the callback /
initiate / logout route cores) is copy-pasted between the two tenant
frontends until the shared ``@kriegerdataforge/oidc-rp`` package is extracted
(owner-deferred post-launch). Until then, this script is the cheap guard the
audit backlog called for: it compares each manifest pair across the two repos
and reports which pairs have diverged, so the identical core can't silently
rot further before extraction.

Usage:
  python scripts/check_oidc_drift.py            # compare all manifest pairs

Environment:
  GH_TOKEN    GitHub token with contents:read on BOTH frontend repos
              (App installation token or CICD_PAT — the repos are private).

Output (machine-readable lines consumed by check-oidc-rp-drift.yml):
  IDENTICAL: <path>
  DRIFTED:   <path> (<n> changed lines)
  MISSING:   <path> (<owner/repo>)
  DRIFT_COUNT: <n>
  DRIFTED_PATHS: <comma-separated paths>

Exit codes: 0 = all pairs identical; 1 = at least one pair drifted/missing;
2 = configuration/API error. Never prints file CONTENTS — only paths and
changed-line counts (the sources are private repos; the tracking issue must
not leak code).
"""

from __future__ import annotations

import base64
import difflib
import json
import os
import sys
from pathlib import Path

from common.http import build_session

GITHUB_API = "https://api.github.com"

SCRIPTS_DIR = Path(__file__).resolve().parent
MANIFEST_FILE = SCRIPTS_DIR / "oidc_drift_manifest.json"

# Shared HTTP session with retry/backoff (same hardening as distribute_kit /
# rotate_secret — see common/http.py). GETs only; fully idempotent.
_SESSION = build_session()


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def load_manifest(path: Path = MANIFEST_FILE) -> dict:
    if not path.is_file():
        sys.exit(f"Error: manifest not found: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for key in ("left", "right", "pairs"):
        if key not in manifest:
            sys.exit(f"Error: manifest missing required key: {key!r}")
    return manifest


def normalize(text: str) -> str:
    """Compare on content only: normalize CRLF/LF and strip trailing
    per-line whitespace (cosmetic editor differences are not RP drift)."""
    lines = text.replace("\r\n", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines)


def fetch_file(token: str, owner_repo: str, branch: str, path: str) -> str | None:
    """Return the decoded file content, or None if it does not exist."""
    owner, repo = owner_repo.split("/", 1)
    resp = _SESSION.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
        headers=_github_headers(token),
        params={"ref": branch},
        timeout=30,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return base64.b64decode(resp.json()["content"]).decode("utf-8")


def changed_line_count(left: str, right: str) -> int:
    """Number of +/- lines in the unified diff (headers excluded)."""
    diff = difflib.unified_diff(
        left.split("\n"), right.split("\n"), lineterm="", n=0
    )
    return sum(
        1
        for line in diff
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith(("+++", "---"))
    )


def compare_pairs(token: str, manifest: dict) -> list[dict]:
    """Compare every manifest pair; return one result dict per pair."""
    left_repo = manifest["left"]["repo"]
    left_branch = manifest["left"].get("branch", "main")
    right_repo = manifest["right"]["repo"]
    right_branch = manifest["right"].get("branch", "main")

    results: list[dict] = []
    for pair in manifest["pairs"]:
        path = pair["path"]
        left = fetch_file(token, left_repo, left_branch, path)
        right = fetch_file(token, right_repo, right_branch, path)

        if left is None or right is None:
            missing_in = left_repo if left is None else right_repo
            results.append({"path": path, "status": "missing", "missing_in": missing_in})
            continue

        left_n, right_n = normalize(left), normalize(right)
        if left_n == right_n:
            results.append({"path": path, "status": "identical"})
        else:
            results.append(
                {
                    "path": path,
                    "status": "drifted",
                    "changed_lines": changed_line_count(left_n, right_n),
                }
            )
    return results


def main() -> int:
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        print("Error: GH_TOKEN is not set (needs contents:read on both frontend repos).")
        return 2

    manifest = load_manifest()
    try:
        results = compare_pairs(token, manifest)
    except Exception as e:  # noqa: BLE001 — surface API errors as config errors
        print(f"Error: GitHub API failure during comparison: {e}")
        return 2

    bad: list[str] = []
    for r in results:
        if r["status"] == "identical":
            print(f"IDENTICAL: {r['path']}")
        elif r["status"] == "drifted":
            print(f"DRIFTED:   {r['path']} ({r['changed_lines']} changed lines)")
            bad.append(r["path"])
        else:
            print(f"MISSING:   {r['path']} ({r['missing_in']})")
            bad.append(r["path"])

    print(f"DRIFT_COUNT: {len(bad)}")
    print(f"DRIFTED_PATHS: {','.join(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
