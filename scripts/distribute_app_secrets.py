"""
GitHub App credential distribution engine (`ops:distribute-app-secrets`).

Copies the read only GitHub App's credentials, held in cicd's ops environment as KDF_READER_APP_ID and
KDF_READER_APP_PRIVATE_KEY, to the repository secrets KDF_APP_ID and KDF_APP_PRIVATE_KEY of every consumer repo
listed in scripts/secret_registry.json (the entries carrying `distribute_source_env`), cicd's own among them and
written last. A run may select repos (--repos), each checked against the registry, and the ops workflow scopes its
mint to the same selection. Each repo gets both values before the next. Consumer repos need their own copies
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
  KDF_APP_ID             source value [execute] — from KDF_READER_APP_ID in cicd's ops environment
  KDF_APP_PRIVATE_KEY    source value [execute] — from KDF_READER_APP_PRIVATE_KEY in cicd's ops environment

SECURITY: source values arrive only via env, flow only into the libsodium sealed box
(rotate_secret.update_github_repo_secret), and are never printed — output is secret
NAMES, repos, and timestamps. The value sanity checks name the expected SHAPE on
failure, never the value.
"""

from __future__ import annotations

# standard imports
import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

# third party imports
from common.http import build_session
# The sealed-box PUT (libsodium encrypt against the target repo's public key) is
# single-sourced in the rotation engine — a second implementation here could drift on
# the crypto. Its module-level session also carries the shared retry/backoff config.
from rotate_secret import GITHUB_API, _github_headers, update_github_repo_secret

REGISTRY_FILE = Path(__file__).parent / "secret_registry.json"
CICD          = "Needless2Say/kriegerdataforge-cicd"
# the environment variable beside a source that holds the value cicd held before the run, where it is known
PREVIOUS_SUFFIX = "_PREVIOUS"
# one PEM private key block, and the shortest body a GitHub App's RSA key has, 2048 bits being about 1600 characters
PEM_BLOCK    = re.compile(
    r"-----BEGIN (?P<label>[A-Z ]*)PRIVATE KEY-----\s+"
    r"(?P<body>[A-Za-z0-9+/=\s]+?)\s*"
    r"-----END (?P=label)PRIVATE KEY-----"
)
PEM_BODY_MIN = 512

_SESSION = build_session()

_FORMAT_HUMAN = {
    "numeric": "an all-digits GitHub App id",
    "pem": "a PEM private key (-----BEGIN ... PRIVATE KEY-----)",
}


def _looks_valid(value: str, fmt: str) -> bool:
    """
    Best-effort shape check so swapped env wiring fails BEFORE any write.

    Callers report the expected shape (`_FORMAT_HUMAN`) on failure — never the value.
    An unknown/absent `value_format` label means no check (the write itself is the
    operation; this guard only catches obviously mis-wired sources).
    """
    if fmt == "numeric":
        return value.isdigit()
    if fmt == "pem":
        # the whole value one PEM block, its BEGIN and END labels alike, a base64 body of a real key's length, and that
        # body one DER sequence whose declared length is the bytes present, so a header alone or a key with lines
        # removed never replaces a working one
        block = PEM_BLOCK.fullmatch(value.strip())
        if not block:
            return False
        body = re.sub(r"\s", "", block.group("body"))
        if len(body) < PEM_BODY_MIN:
            return False
        try:
            return _der_whole(base64.b64decode(body, validate = True))
        except ValueError:
            return False
    return True


def _der_whole(der: bytes) -> bool:
    """
    Whether the bytes are one whole DER sequence, its declared length the bytes that follow its header.

    Args:
        der: The decoded body of a PEM block

    Returns:
        True when the sequence's length field names exactly the bytes present
    """
    if len(der) < 2 or der[0] != 0x30:
        return False
    if der[1] < 0x80:
        return 2 + der[1] == len(der)
    width = der[1] & 0x7F
    if not 1 <= width <= 4 or len(der) < 2 + width:
        return False
    return 2 + width + int.from_bytes(der[2:2 + width], "big") == len(der)

# ======================================================================================================================
# Registry + selection
# ======================================================================================================================

def _load_registry() -> dict:
    if not REGISTRY_FILE.is_file():
        sys.exit(f"Error: registry file not found: {REGISTRY_FILE}")
    return json.loads(REGISTRY_FILE.read_text(encoding = "utf-8"))


def _distributable(registry: dict) -> list[dict]:
    """
    Entries opted into distribution (they carry `distribute_source_env`).
    """
    return [e for e in registry.get("secrets", []) if e.get("distribute_source_env")]


def _select_entries(registry: dict, raw: str) -> list[dict]:
    """
    Distributable entries matching the CSV filter (empty / 'all' = every one).

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
    wanted  = {p.strip() for p in stripped.split(",") if p.strip()}
    unknown = sorted(w for w in wanted if w not in by_name)
    if unknown:
        sys.exit(
            f"Error: not distributable: {', '.join(unknown)}. " f"Distributable secrets: {', '.join(sorted(by_name))}.",
        )
    return [e for e in entries if e["name"].lower() in wanted]


def _target_repos(entries: list[dict]) -> list[str]:
    """
    Sorted union of `owner/repo` targets across the entries.
    """
    return sorted({t["repo"] for e in entries for t in e.get("github_repo_secrets", [])})


def _select_repos(entries: list[dict], raw: str) -> list[str]:
    """
    The repos a run writes, checked against the registry, in the order they are written.

    Empty or 'all' names every target. Otherwise each comma separated name, short or `owner/repo`, must be a target
    of the entries, else the run stops before any mint or write. cicd's own pair comes last, since writing it ends the
    bootstrap's authority (the secrets fence).

    Args:
        entries: The distributable entries
        raw: The selector as the issue form or the command line gave it

    Returns:
        The selected `owner/repo` names, every other repo sorted and cicd last
    """
    targets  = _target_repos(entries)
    by_name  = {repo.lower(): repo for repo in targets}
    by_short = {repo.split("/", 1)[1].lower(): repo for repo in targets}
    stripped = (raw or "").strip().lower()
    if stripped in ("", "all"):
        chosen = targets
    else:
        chosen = []
        for part in (piece.strip() for piece in stripped.split(",")):
            if not part:
                continue
            repo = by_name.get(part) or by_short.get(part)
            if repo is None:
                sys.exit(f"Error: '{part}' is not a distribution target in the registry. Nothing was written.")
            chosen.append(repo)
        if not chosen:
            # an empty repositories list would mint a token over the App's whole installation
            sys.exit("Error: the selection names no repo. Name the repos, or ALL. Nothing was minted or written.")
    return sorted(set(chosen), key = lambda repo: (repo.lower() == CICD.lower(), repo))

# ======================================================================================================================
# GitHub read helper (check mode)
# ======================================================================================================================

def list_repo_secret_meta(gh_token: str, owner_repo: str) -> dict[str, str]:
    """
    Map of secret NAME -> updated_at for a repo's Actions secrets.

    The list endpoint returns metadata only (GitHub cannot return secret values).
    GitHub caps a repo at 100 Actions secrets, so one `per_page=100` call is complete.
    """
    owner, repo = owner_repo.split("/", 1)
    resp = _SESSION.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/actions/secrets",
        headers = _github_headers(gh_token),
        params = {"per_page": 100},
        timeout = 30,
    )
    resp.raise_for_status()
    return {s["name"]: s.get("updated_at", "?") for s in resp.json().get("secrets", [])}

# ======================================================================================================================
# Mode: check
# ======================================================================================================================

def cmd_check(entries: list[dict], gh_token: str, repos: list[str] | None = None) -> int:
    """
    Audit which targets hold / lack each distributable secret. Read-only.

    Prints a machine-greppable `MISSING: <n>` line for the ops workflow's summary.

    Args:
        entries: The distributable entries to audit
        gh_token: A token that reads the targets' secret names
        repos: The selected targets, every target when None

    Returns:
        0 when the audit completed, 1 when a repo could not be audited
    """
    if not gh_token:
        sys.exit("Error: GH_TOKEN not set.")
    repos = repos if repos is not None else _select_repos(entries, "all")
    names = [e["name"] for e in entries]
    print(f"Auditing {len(repos)} target repo(s) for {len(names)} distributable " f"secret(s): {', '.join(names)}\n")
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

# ======================================================================================================================
# Mode: execute
# ======================================================================================================================

def cmd_execute(entries: list[dict], gh_token: str, repos: list[str] | None = None) -> int:
    """
    Write every source value to the selected repos, both values to a repo before the next and cicd's own pair last.

    A repo left with one half of the pair would mint from a mismatched id and key, so each repo is written whole
    before the run moves on, and a failure leaves at most the one repo it struck half written.

    Args:
        entries: The distributable entries to write
        gh_token: A token that writes the targets' secrets
        repos: The selected targets in the order to write them, every target with cicd last when None

    Returns:
        0 when every write succeeded, else 1
    """
    if not gh_token:
        sys.exit("Error: GH_TOKEN not set.")
    repos = repos if repos is not None else _select_repos(entries, "all")
    # Resolve + sanity-check EVERY source value before the first write, so a missing or
    # mis-wired env var can never half-distribute the pair.
    values: dict[str, str] = {}
    for entry in entries:
        env_name = entry["distribute_source_env"]
        value    = os.environ.get(env_name, "")
        if not value:
            sys.exit(
                f"Error: {env_name} is not set — the ops workflow passes it from the reader's pair in "
                "cicd's ops environment (execute mode only). Nothing was written."
            )
        fmt = entry.get("value_format", "")
        if fmt and not _looks_valid(value, fmt):
            sys.exit(
                f"Error: {env_name} does not look like {_FORMAT_HUMAN.get(fmt, fmt)} — "
                "refusing to distribute a mis-wired value. Nothing was written."
            )
        values[entry["name"]] = value

    # each value cicd held before, where known, so cicd's own pair, written last and the bootstrap's authority, gets
    # its whole old pair back when a write fails, the workflow passing cicd's repository pair this run holds itself,
    # and no other repo's is known, since a retry finds some repos already on the new pair, so none of theirs is
    # put back
    previous: dict[str, str] = {}
    for entry in entries:
        before = os.environ.get(f"{entry['distribute_source_env']}{PREVIOUS_SUFFIX}", "")
        fmt    = entry.get("value_format", "")
        if before and (not fmt or _looks_valid(before, fmt)):
            previous[entry["name"]] = before
    # the writes that can be put back go first
    entries = sorted(entries, key = lambda entry: entry["name"] not in previous)

    errors: list[str] = []
    print(f"Distributing {', '.join(entry['name'] for entry in entries)} to {len(repos)} repo(s):")
    for owner_repo in repos:
        if owner_repo == CICD and errors:
            # cicd's own pair is what a rerun mints from, the bootstrap's authority, so it is replaced only once every
            # other write succeeded
            print(f"{owner_repo}: skipped, another write failed, so cicd's own pair is left as it is for a rerun")
            continue
        print(f"{owner_repo}:")
        _write_repo(owner_repo, entries, values, gh_token, errors, previous if owner_repo == CICD else {})
    print()
    if errors:
        print(f"{len(errors)} target(s) failed (PUT is idempotent — fix and re-run to converge):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("All targets updated successfully.")
    return 0


def _write_repo(
    owner_repo: str,
    entries: list[dict],
    values: dict[str, str],
    gh_token: str,
    errors: list[str],
    previous: dict[str, str] | None = None,
) -> None:
    """
    Write each value one repo holds, in the entries' order, and stop at the first failure.

    A failed write may still have been taken, its answer lost, so after any failure no repo is said to hold its old
    pair unless it was put back whole. cicd's own pair, the bootstrap's authority, is put back whole from its previous
    pair, the failed value included, with the token already minted, never the damaged pair. Another repo is said to
    hold half a pair, which a rerun writes again.

    Args:
        owner_repo: The repo, owner/name
        entries: The distributable entries, those whose previous value is known first
        values: Each entry's source value by its name
        gh_token: A token that writes the repo's secrets
        errors: The run's failures, added to
        previous: Each entry's previous value by its name, where known, cicd's alone
    """
    for entry in entries:
        for target in entry.get("github_repo_secrets", []):
            if target["repo"] != owner_repo:
                continue
            label = f"{owner_repo} [repo] {target['secret_name']}"
            print(f"  {target['secret_name']}", end = " ... ", flush = True)
            try:
                update_github_repo_secret(gh_token, owner_repo, target["secret_name"], values[entry["name"]])
                print("OK")
            except Exception as exc:  # noqa: BLE001
                print(f"FAILED - {exc}")
                errors.append(f"{label}: {exc}")
                if owner_repo == CICD:
                    _restore_cicd(entries, previous or {}, gh_token, errors)
                else:
                    print(f"  {owner_repo} may hold half a pair, a write that failed may still have been taken. "
                          "A rerun once the cause is fixed writes both values again.")
                return


def _restore_cicd(entries: list[dict], previous: dict[str, str], gh_token: str, errors: list[str]) -> None:
    """
    Put cicd's whole previous pair back after a failed write, so a bootstrap rerun still mints from it.

    Every value is written back, the one whose write failed included, since it may have been taken with its answer
    lost. With either previous value unknown nothing is put back, since an old id beside a key that may be new mints
    nothing, and the pair is said to be uncertain with the way to recover by hand.

    Args:
        entries: The distributable entries
        previous: Each entry's previous value by its name, cicd's own
        gh_token: A token that writes cicd's secrets
        errors: The run's failures, added to
    """
    targets = [
        (entry, target["secret_name"])
        for entry in entries
        for target in entry.get("github_repo_secrets", [])
        if target["repo"] == CICD
    ]
    recover = (
        f"  {CICD}'s pair is uncertain, so a bootstrap rerun may not mint. Make a new key in the writing App's "
        f"settings and set {CICD}'s KDF_APP_ID and KDF_APP_PRIVATE_KEY from a prompt, then rerun."
    )
    if any(entry["name"] not in previous for entry, _ in targets):
        print(recover)
        errors.append(f"{CICD}: its pair is uncertain, its previous pair not known whole")
        return
    for entry, secret_name in targets:
        print(f"  {secret_name} put back to its previous value", end = " ... ", flush = True)
        try:
            update_github_repo_secret(gh_token, CICD, secret_name, previous[entry["name"]])
            print("OK")
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED - {exc}")
            print(recover)
            errors.append(f"{CICD} [repo] {secret_name}: the put back failed, {exc}")
            return
    print(f"  {CICD} holds its previous pair again")

# ======================================================================================================================
# Mode: targets
# ======================================================================================================================

def cmd_targets(registry: dict, raw: str = "all") -> int:
    """
    Print the comma-separated SHORT names of the selected distribution targets.

    The union over ALL distributable entries (ignores --secrets), narrowed by the --repos selector, so the ops
    workflow scopes its App token to exactly the repos the run writes. `actions/create-github-app-token`'s
    `repositories:` input takes bare repo names — every target shares the one account owner.

    Args:
        registry: The loaded registry
        raw: The --repos selector

    Returns:
        0, once the names are printed
    """
    repos = _select_repos(_distributable(registry), raw)
    print(",".join(r.split("/", 1)[1] for r in repos))
    return 0

# ======================================================================================================================
# CLI
# ======================================================================================================================

def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description = (
            "Distribute the cicd-held GitHub App credentials to every consumer repo " "in secret_registry.json (entries carrying distribute_source_env)."
        ),
        formatter_class = argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("mode", choices = ["check", "execute", "targets"])
    parser.add_argument(
        "--secrets",
        default = "all",
        help = 'Comma-separated distributable secret names, or "all" (targets mode ignores this).',
    )
    parser.add_argument(
        "--repos",
        default = "all",
        help = 'Comma-separated target repos, short or owner/repo, each checked against the registry, or "all".',
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args     = parse_cli_args(argv)
    registry = _load_registry()
    if args.mode == "targets":
        sys.exit(cmd_targets(registry, args.repos))
    entries  = _select_entries(registry, args.secrets)
    repos    = _select_repos(_distributable(registry), args.repos)
    gh_token = os.environ.get("GH_TOKEN", "").strip()
    if args.mode == "check":
        sys.exit(cmd_check(entries, gh_token, repos))
    sys.exit(cmd_execute(entries, gh_token, repos))


if __name__ == "__main__":
    main()
