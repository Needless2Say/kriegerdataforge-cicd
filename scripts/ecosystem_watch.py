"""
The ecosystem watch, a weekly read only snapshot of the KDF repos (ADR D-049).

It reads four things across every repo of the kit registry and cicd itself, and writes to none of them.

  alerts    open Dependabot alerts, with the package, the severity, the fixed version and a link
  pins      each pin of a package built from one of the owner's repos (the requirements files, pyproject.toml,
            package.json, the kdf_fmt_ref of ci.yml, and cicd's canonical kdf-fmt pin) against that repo's latest
            release tag. A pin of `main` tracks the latest release, since every code merge there is one, and a
            commit that is no tag is current when GitHub's compare finds the latest tag in it
  drift     each repo's kit version against cicd's, and each vendored dev script against cicd's canonical copy, by git
            blob sha
  notices   the deprecation notices GitHub attached to the latest completed run of each workflow

The snapshot is JSON first (schema kdf-ecosystem-watch/1), so an admin dashboard can take the same data later, and an
issue body second. A private repo's open vulnerabilities belong in a private place, so a private repo's scheduled
workflow runs this through the reusable `.github/workflows/ecosystem-watch.yml`, and the log carries counts alone.

Commands:
  collect   read GitHub and write the snapshot
  render    turn a snapshot into the issue body, the news since the previous body, and the state, open or clear

Environment variables:
  GH_TOKEN  for the http transport, a token that reads Dependabot alerts, contents, actions and checks on every repo

Usage:
    GH_TOKEN=... python ecosystem_watch.py collect --out snapshot.json
    python ecosystem_watch.py collect --transport gh --out snapshot.json      # a local dry run on the gh login
    python ecosystem_watch.py render --snapshot snapshot.json --previous prev.md --body body.md --news news.md \
        --state state.txt
"""

from __future__ import annotations

# standard imports
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlparse

# ======================================================================================================================
# Configuration
# ======================================================================================================================

OWNER        = "Needless2Say"
SCHEMA       = "kdf-ecosystem-watch/1"
GITHUB_API   = "https://api.github.com"
SCRIPTS_DIR  = Path(__file__).resolve().parent
CICD_ROOT    = SCRIPTS_DIR.parent
CICD_REPO    = f"{OWNER}/kriegerdataforge-cicd"
KIT_REGISTRY = SCRIPTS_DIR / "kit_registry.json"
SCR_REGISTRY = SCRIPTS_DIR / "scripts_registry.json"
KIT_VERSION  = CICD_ROOT / "kit" / "KIT_VERSION"

# the files a repo pins a package of the owner's in, read when present
PIN_FILES = (
    "requirements.in",
    "requirements-dev.in",
    "requirements.txt",
    "vercel_api/requirements.txt",
    "pyproject.toml",
    "package.json",
    ".github/workflows/ci.yml",
)

# the repos whose release tags the watch always reads, a pin of any other owned repo reads that repo's on first sight
RELEASE_REPOS = (
    "kriegerdataforge-fmt",
    "kriegerdataforge-sdk",
    "kriegerdataforge-reports-sdk",
    "kriegerdataforge-report-form",
)

# `name[extras] @ git+https://github.com/<owner>/<repo>.git@<ref>`, at a line's start or inside a quoted toml string,
# never in a comment
_PIN_HEAD = r"""^[ \t]*["']?(?P<name>[A-Za-z0-9_.-]+)(?:\[[^\]\n]*\])?[ \t]*@[ \t]*git\+https://github\.com/"""
_PIN_TAIL = r"""/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?@(?P<ref>[A-Za-z0-9_.-]+)"""
GIT_PIN   = re.compile(_PIN_HEAD + re.escape(OWNER) + _PIN_TAIL, re.MULTILINE)

# the style lane's input in a repo's ci.yml, `kdf_fmt_ref: v1.3.0`, never in a comment
KDF_FMT_REF = re.compile(r"""^[ \t]*kdf_fmt_ref:[ \t]*["']?(?P<ref>v?\d+\.\d+\.\d+)["']?[ \t]*$""", re.MULTILINE)

# an npm package of the owner's, by its name, and the repo whose tags are its releases
NPM_SOURCES = {"@needless2say/report-form": "kriegerdataforge-report-form"}

SEMVER    = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
FULL_SHA  = re.compile(r"^[0-9a-f]{40}$")
NPM_RANGE = re.compile(r"^(?P<operator>\^|~|=)?v?(?P<version>\d+\.\d+\.\d+)$")

# the next page of a list GitHub pages by cursor, as its `Link` header names it
NEXT_LINK = re.compile(r"""<(?P<url>[^>]*)>\s*;\s*rel="next\"""")

# the words of a notice that announces a change, as GitHub words its runner, action and Node.js retirements
DEPRECATION_WORDS = (
    "deprecat",
    "will be removed",
    "no longer supported",
    "end of life",
    "end-of-life",
    "will migrate",
    "retir",
    "sunset",
    "brownout",
    "will stop working",
    "will be disabled",
)
DEPRECATION       = re.compile("|".join(re.escape(word) for word in DEPRECATION_WORDS), re.IGNORECASE)

SEVERITIES    = ("critical", "high", "medium", "low")
PAGE          = 100
PAGES         = 10     # pages read at most of any one list, 1000 items, a longer list is a blind spot
ALERTS_SHOWN  = 15     # alerts listed per repo in the issue, the counts are always whole
NOTICES_SHOWN = 20
NOTICE_DAYS   = 60     # a notice from an older run is listed, not counted, only a new run of its workflow clears it
STAMP         = "%Y-%m-%dT%H:%M:%SZ"
NEWS_SHOWN    = 100    # findings listed in one news comment
BODY_LIMIT    = 60000  # an issue body over 65536 characters is refused
KEYS_MARKER   = "kdf-watch-keys:"
KEY_HEX       = 10     # each finding is remembered as the first 10 hex of its key's sha1
KEYS_LIMIT    = 3000   # findings remembered at most, 30000 characters of the body

# ======================================================================================================================
# Transports
# ======================================================================================================================

@dataclass
class Response:
    """
    One GitHub API answer, its status, its parsed body (text for a raw file) and its headers.
    """
    status: int
    data: Any
    headers: dict[str, str] = field(default_factory = dict)


    @property
    def ok(self) -> bool:
        """
        Whether the call succeeded.

        Returns:
            bool: True for a 2xx status
        """
        return 200 <= self.status < 300


    def reason(self) -> str:
        """
        GitHub's own message for a failed call, or the status alone.

        Returns:
            str: `HTTP <status>`, or `no answer` when none came, with GitHub's message when the body carried one
        """
        message = self.data.get("message") if isinstance(self.data, dict) else None
        return (f"HTTP {self.status}" if self.status else "no answer") + (f", {message}" if message else "")


class Transport(Protocol):
    """
    What the collectors need of GitHub, one GET.
    """
    def get(self, path: str, params: dict[str, Any] | None = None, raw: bool = False) -> Response:
        """
        One GET of GitHub's REST API.

        Args:
            path: the API path, `/repos/<owner>/<repo>/...`
            params: the query parameters
            raw: ask for a file's raw content rather than its JSON description

        Returns:
            Response: the answer, a failed one included
        """


class HttpTransport:
    """
    GitHub's REST API over requests, with cicd's retrying session, the token from GH_TOKEN.
    """
    def __init__(self, token: str) -> None:
        """
        Args:
            token: a token that reads every repo the watch reads
        """
        # third party imports
        from common.http import build_session

        self._session = build_session()
        self._token   = token


    def get(self, path: str, params: dict[str, Any] | None = None, raw: bool = False) -> Response:
        """
        One GET of GitHub's REST API with the token.

        Args:
            path: the API path
            params: the query parameters
            raw: ask for a file's raw content

        Returns:
            Response: the answer, a raw file's body kept as text, status 0 and the exception's type alone when the
            session's retries ended without one
        """
        # third party imports
        from requests import RequestException

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            resp = self._session.get(f"{GITHUB_API}{path}", headers = headers, params = params, timeout = 30)
        except RequestException as exc:
            # a dead connection or a timeout is a blind spot of this one call, never the end of the run
            return Response(0, {"message": type(exc).__name__})
        if raw and resp.ok:
            return Response(resp.status_code, resp.text, dict(resp.headers))
        try:
            data = resp.json()
        except ValueError:
            data = None
        return Response(resp.status_code, data, dict(resp.headers))


class GhTransport:
    """
    The same calls through the gh CLI, so a dry run on a developer machine uses its login and holds no token.
    """
    def get(self, path: str, params: dict[str, Any] | None = None, raw: bool = False) -> Response:
        """
        One GET through `gh api --include`.

        Args:
            path: the API path
            params: the query parameters
            raw: ask for a file's raw content

        Returns:
            Response: the answer, read from gh's output
        """
        url    = path + (f"?{urlencode(params)}" if params else "")
        accept = "application/vnd.github.raw+json" if raw else "application/vnd.github+json"
        done   = subprocess.run(
            ["gh", "api", "--method", "GET", "--include", "-H", f"Accept: {accept}", url],
            capture_output = True,
            text = True,
            encoding = "utf-8",
            check = False,
        )
        return parse_included(done.stdout, raw)


def parse_included(text: str, raw: bool = False) -> Response:
    """
    Split `gh api --include` output, a status line and headers, a blank line, then the body.

    Args:
        text: gh's output
        raw: the call asked for a raw file, whose body stays text when it succeeded, even when the file is JSON itself,
            as package.json is

    Returns:
        Response: the status, the body and the headers, status 0 when there was no status line
    """
    head, _, body = text.replace("\r\n", "\n").partition("\n\n")
    lines   = head.split("\n")
    match   = re.match(r"HTTP/\S+\s+(\d{3})", lines[0] if lines else "")
    status  = int(match.group(1)) if match else 0
    headers = {}
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        if sep:
            headers[name.strip().lower()] = value.strip()
    if raw and 200 <= status < 300:
        return Response(status, body, headers)
    try:
        data: Any = json.loads(body) if body.strip() else None
    except ValueError:
        data = body
    return Response(status, data, headers)


def next_params(headers: dict[str, str]) -> dict[str, str] | None:
    """
    The query of the next page an answer's `Link` header names, how GitHub pages a list by cursor.

    Args:
        headers: the answer's headers, their names in any case

    Returns:
        dict[str, str] | None: the next page's query parameters, None on the last page
    """
    link  = next((value for name, value in headers.items() if name.lower() == "link"), "")
    match = NEXT_LINK.search(link)
    return dict(parse_qsl(urlparse(match.group("url")).query)) if match else None


def read_pages(
    transport: Transport,
    path: str,
    params: dict[str, Any] | None = None,
    key: str | None = None,
) -> tuple[list[Any], str | None]:
    """
    Every item of a list GitHub pages by number, at most PAGES pages of it.

    Args:
        transport: how GitHub is reached
        path: the API path
        params: the query parameters besides the page's own
        key: the field of the answer that holds the list, None when the answer is the list

    Returns:
        tuple[list[Any], str | None]: the items read, and why the rest could not be, None when every page was read
    """
    items: list[Any] = []
    for page in range(1, PAGES + 1):
        resp = transport.get(path, {**(params or {}), "per_page": PAGE, "page": page})
        data = resp.data
        if key:
            data = resp.data.get(key) if isinstance(resp.data, dict) else None
        if not resp.ok:
            return items, resp.reason()
        if not isinstance(data, list):
            return items, "an answer of an unexpected shape"
        items.extend(data)
        if len(data) < PAGE:
            return items, None
    return items, f"more than {PAGES * PAGE}, the rest were not read"

# ======================================================================================================================
# Versions
# ======================================================================================================================

def semver(text: str) -> tuple[int, int, int] | None:
    """
    The version of a plain release name.

    Args:
        text: `v1.2.3` or `1.2.3`

    Returns:
        tuple[int, int, int] | None: (major, minor, patch), None for anything else, a pre-release included
    """
    match = SEMVER.match(text.strip())
    return (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None


def npm_allows(spec: str, version: tuple[int, int, int]) -> bool | None:
    """
    Whether an npm range of the three plain shapes, `^1.2.3`, `~1.2.3` or `1.2.3`, admits a version.

    Args:
        spec: the range a package.json names
        version: the version to test

    Returns:
        bool | None: whether it admits it, None for any other range, which the watch reports without judging
    """
    match = NPM_RANGE.match(spec.strip())
    if not match:
        return None
    floor = semver(match.group("version"))
    if floor is None:
        return None
    operator = match.group("operator") or "="
    if version < floor:
        return False
    if operator == "=":
        return version == floor
    if operator == "~":
        return version[:2] == floor[:2]
    if floor[0] > 0:
        return version[0] == floor[0]
    if floor[1] > 0:
        return version[:2] == floor[:2]
    return version == floor


@dataclass
class Release:
    """
    The latest release tag of one of the owner's repos, and every tag it read by commit, for a pin made by sha.
    """
    tag: str | None
    sha: str | None
    by_sha: dict[str, str]
    error: str | None = None


def latest_release(transport: Transport, repo: str) -> Release:
    """
    The highest `vX.Y.Z` tag of a repo, every page of its tags read, since GitHub lists them by name and not by version.

    Args:
        transport: how GitHub is reached
        repo: the repo's name, without the owner

    Returns:
        Release: the tag and its commit, every plain tag by commit, or why the tags could not be read
    """
    items, error = read_pages(transport, f"/repos/{OWNER}/{repo}/tags")
    if error:
        return Release(None, None, {}, error)
    tagged = [(semver(item["name"]), item["name"], item["commit"]["sha"]) for item in items]
    by_sha = {sha: name for version, name, sha in tagged if version}
    best   = max((item for item in tagged if item[0]), default = None, key = lambda item: item[0])
    return Release(best[1] if best else None, best[2] if best else None, by_sha)


def judge(ref: str, release: Release, holds_latest: Callable[[str], bool | None] | None = None) -> dict[str, Any]:
    """
    Whether a pinned ref is behind its repo's latest release.

    A pin of `main` tracks the latest release, since every merge that changes an owned package's code bumps its
    version and is released, and only kit and script syncs land on main between releases. A lockfile made from such a
    pin holds a commit after the latest tag, which is current when the tag is in it.

    Args:
        ref: a version tag, `main` or a full commit sha
        release: the source repo's latest release
        holds_latest: whether a commit that is no release tag holds the latest release, None when that could not be
            told, and when not given such a commit is called behind

    Returns:
        dict[str, Any]: the pinned ref, the latest tag, whether it is behind, whether it could be judged at all, and a
        note when the verdict needs one
    """
    out: dict[str, Any] = {"pinned": ref, "latest": release.tag, "behind": False, "judged": True, "note": None}
    if release.error or not release.tag:
        out["note"] = f"latest release unknown ({release.error or 'no vX.Y.Z tag'})"
        out["judged"] = False
        return out
    latest = semver(release.tag)
    if ref == "main":
        out["note"] = "tracks main"
        return out
    if FULL_SHA.match(ref):
        tag = release.by_sha.get(ref)
        if ref == release.sha:
            out["note"] = f"commit of {release.tag}"
        elif tag:
            out["note"] = f"commit of {tag}"
            out["behind"] = semver(tag) < latest
        elif holds_latest is not None and holds_latest(ref):
            out["note"] = f"a commit after {release.tag}"
        else:
            out["note"] = "a commit that is no release tag"
            out["behind"] = True
        return out
    pinned = semver(ref)
    if pinned is None:
        out["note"] = "not a version tag"
        out["judged"] = False
        return out
    out["behind"] = pinned < latest
    return out


class Releases:
    """
    The latest release of each source repo, read once by whichever worker asks first while the others wait, so every
    pin of a source is judged against one answer, a failed read included. A commit's compare with it is asked once
    too, under a lock of its own, so a slow compare never holds up a release lookup.
    """
    def __init__(self, transport: Transport) -> None:
        """
        Args:
            transport: how GitHub is reached
        """
        self._transport    = transport
        self._lock         = threading.Lock()
        self._compare_lock = threading.Lock()
        self.known:    dict[str, Release] = {}
        self.compared: dict[tuple[str, str], bool | None] = {}


    def get(self, repo: str) -> Release:
        """
        A source repo's latest release, read on its first sight.

        Args:
            repo: the repo's name, without the owner

        Returns:
            Release: the release, or why it could not be read, an answer of a shape the watch does not know included
        """
        with self._lock:
            if repo not in self.known:
                try:
                    self.known[repo] = latest_release(self._transport, repo)
                except Exception as exc:  # noqa: BLE001, a blind spot named by its type, never the run's end
                    self.known[repo] = Release(None, None, {}, f"the read failed, {type(exc).__name__}")
            return self.known[repo]


    def holds_latest(self, repo: str, sha: str) -> bool | None:
        """
        Whether a commit holds its repo's latest release, by GitHub's compare of the tag with it, asked once a commit.

        Args:
            repo: the repo's name, without the owner
            sha: a full commit sha that is no release tag

        Returns:
            bool | None: True when the compare finds the commit ahead of the tag or the same, False when behind it or
            split from it, None when the release or the compare could not be read
        """
        release = self.get(repo)
        if not release.tag:
            return None
        with self._compare_lock:
            if (repo, sha) not in self.compared:
                answer: bool | None = None
                try:
                    resp = self._transport.get(f"/repos/{OWNER}/{repo}/compare/{release.tag}...{sha}")
                    if resp.ok and isinstance(resp.data, dict) and resp.data.get("status"):
                        answer = resp.data["status"] in ("ahead", "identical")
                except Exception:  # noqa: BLE001, an unread compare leaves the commit behind, never the run's end
                    answer = None
                self.compared[(repo, sha)] = answer
            return self.compared[(repo, sha)]

# ======================================================================================================================
# Collection
# ======================================================================================================================

def read_registries() -> tuple[list[str], set[str], dict[str, list[dict]], str, str]:
    """
    What to watch, from this checkout of cicd.

    Returns:
        tuple: the repos, cicd and every kit target, the kit targets, each scripts target's vendored files (a file whose
        entry names its own `repos`, the mutation engine, only in those, D-040), cicd's kit version and its canonical
        kdf-fmt pin
    """
    kit     = json.loads(KIT_REGISTRY.read_text(encoding = "utf-8"))
    scr     = json.loads(SCR_REGISTRY.read_text(encoding = "utf-8"))
    kit_set = {entry["repo"] for entry in kit["repos"]}
    scripts = {
        entry["repo"]: [item for item in scr["files"] if "repos" not in item or entry["repo"] in item["repos"]]
        for entry in scr["repos"]
    }
    repos   = [CICD_REPO] + sorted(kit_set - {CICD_REPO})
    fmt_pin = scr["requirements_patch"]["kdf_fmt_ref"]
    kit_ver = KIT_VERSION.read_text(encoding = "utf-8").strip()
    return repos, kit_set, scripts, kit_ver, fmt_pin


def _alert(alert: dict[str, Any]) -> dict[str, Any]:
    """
    The fields of one Dependabot alert the watch keeps.

    Args:
        alert: the alert as GitHub gives it

    Returns:
        dict[str, Any]: its number, severity, package, manifest, versions, advisory and link
    """
    advisory = alert.get("security_advisory") or {}
    vuln     = alert.get("security_vulnerability") or {}
    package  = (alert.get("dependency") or {}).get("package") or {}
    patched  = vuln.get("first_patched_version") or {}
    return {
        "number": alert.get("number"),
        "severity": (vuln.get("severity") or advisory.get("severity") or "unknown").lower(),
        "ecosystem": package.get("ecosystem"),
        "package": package.get("name"),
        "manifest": (alert.get("dependency") or {}).get("manifest_path"),
        "vulnerable": vuln.get("vulnerable_version_range"),
        "patched": patched.get("identifier"),
        "advisory": advisory.get("ghsa_id"),
        "cve": advisory.get("cve_id"),
        "summary": advisory.get("summary"),
        "url": alert.get("html_url"),
    }


def collect_alerts(transport: Transport, repo: str) -> dict[str, Any]:
    """
    A repo's open Dependabot alerts, every page of them, by the cursor GitHub's `Link` header gives, since a critical
    alert can sit on any page.

    Args:
        transport: how GitHub is reached
        repo: `owner/name`

    Returns:
        dict[str, Any]: `ok` and the alerts, or `unavailable`, why, and the alerts read before a page failed or the
        PAGES limit was reached
    """
    alerts: list[dict[str, Any]] = []
    params: dict[str, Any]       = {"state": "open", "per_page": PAGE}
    for _page in range(PAGES):
        resp = transport.get(f"/repos/{repo}/dependabot/alerts", params)
        if not resp.ok or not isinstance(resp.data, list):
            return {"status": "unavailable", "reason": resp.reason(), "open": alerts}
        alerts.extend(_alert(alert) for alert in resp.data)
        following = next_params(resp.headers)
        if following is None:
            return {"status": "ok", "reason": None, "open": alerts}
        params = {**following, "state": "open", "per_page": PAGE}
    reason = f"more than {PAGES * PAGE} open alerts, the rest were not read"
    return {"status": "unavailable", "reason": reason, "open": alerts}


def find_pins(path: str, text: str) -> list[dict[str, str]]:
    """
    Every pin of an owner's package in one file.

    Args:
        path: the file's path in its repo, which says how to read it
        text: the file's content

    Returns:
        list[dict[str, str]]: each pin's file, package name, source repo and ref or range, `npm` set on a range
    """
    pins: list[dict[str, str]] = []
    if path == "package.json":
        try:
            manifest = json.loads(text)
        except ValueError:
            return pins
        for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            for name, spec in (manifest.get(section) or {}).items():
                if name in NPM_SOURCES and isinstance(spec, str):
                    pins.append({"file": path, "package": name, "repo": NPM_SOURCES[name], "ref": spec, "npm": "1"})
        return pins
    if path.endswith("ci.yml"):
        for match in KDF_FMT_REF.finditer(text):
            pins.append({
                "file": path,
                "package": "kdf-fmt (kdf_fmt_ref)",
                "repo": "kriegerdataforge-fmt",
                "ref": match.group("ref"),
            })
        return pins
    for match in GIT_PIN.finditer(text):
        pins.append({
            "file": path,
            "package": match.group("name"),
            "repo": match.group("repo"),
            "ref": match.group("ref"),
        })
    return pins


def collect_pins(transport: Transport, repo: str) -> tuple[list[dict[str, str]], list[str]]:
    """
    The pins of a repo's pin files that exist.

    Args:
        transport: how GitHub is reached
        repo: `owner/name`

    Returns:
        tuple[list[dict[str, str]], list[str]]: the pins, and each file that could not be read for a reason other
        than its absence
    """
    pins:   list[dict[str, str]] = []
    errors: list[str]          = []
    for path in PIN_FILES:
        resp = transport.get(f"/repos/{repo}/contents/{path}", raw = True)
        if resp.status == 404:
            continue
        if not resp.ok or not isinstance(resp.data, str):
            errors.append(f"{path}: {resp.reason()}")
            continue
        pins.extend(find_pins(path, resp.data))
    return pins, errors


def collect_drift(
    transport: Transport,
    repo: str,
    kit_set: set[str],
    scripts: dict[str, list[dict]],
    kit_version: str,
    canonical: dict[str, str | None],
) -> tuple[list[dict[str, str]], list[str]]:
    """
    A repo's kit version against cicd's, and each vendored script's blob sha against cicd's canonical copy.

    Args:
        transport: how GitHub is reached
        repo: `owner/name`
        kit_set: the kit's targets
        scripts: each scripts target's vendored files
        kit_version: cicd's kit version
        canonical: each script source's blob sha on cicd's main

    Returns:
        tuple[list[dict[str, str]], list[str]]: the drift, and each file that could not be read
    """
    drift:  list[dict[str, str]] = []
    errors: list[str]           = []
    if repo in kit_set:
        resp = transport.get(f"/repos/{repo}/contents/docs/agent/KIT_VERSION", raw = True)
        if resp.ok and isinstance(resp.data, str):
            if resp.data.strip() != kit_version:
                drift.append({
                    "kind": "kit",
                    "path": "docs/agent/KIT_VERSION",
                    "have": resp.data.strip(),
                    "want": kit_version,
                })
        else:
            errors.append(f"docs/agent/KIT_VERSION: {resp.reason()}")
    for entry in scripts.get(repo, []):
        want = canonical.get(entry["src"])
        if want is None:
            continue
        resp = transport.get(f"/repos/{repo}/contents/{entry['dest']}")
        if resp.status == 404:
            drift.append({"kind": "scripts", "path": entry["dest"], "have": "missing", "want": want[:10]})
        elif resp.ok and isinstance(resp.data, dict):
            if resp.data.get("sha") != want:
                have = str(resp.data.get("sha"))[:10]
                drift.append({"kind": "scripts", "path": entry["dest"], "have": have, "want": want[:10]})
        else:
            errors.append(f"{entry['dest']}: {resp.reason()}")
    return drift, errors


def run_notices(transport: Transport, repo: str, run: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
    """
    The deprecation notices on one run, from every job that carries an annotation.

    Args:
        transport: how GitHub is reached
        repo: `owner/name`
        run: the run, as GitHub lists it

    Returns:
        tuple[list[dict[str, str]], list[str]]: each notice's message, level, workflow, job and the run's start, and
        what could not be read
    """
    checks, error = read_pages(
        transport,
        f"/repos/{repo}/check-suites/{run['check_suite_id']}/check-runs",
        key = "check_runs",
    )
    errors = [f"check runs of {run.get('name')}: {error}"] if error else []
    notices: list[dict[str, str]] = []
    for check in checks:
        if not (check.get("output") or {}).get("annotations_count"):
            continue
        notes, failed = read_pages(transport, f"/repos/{repo}/check-runs/{check.get('id')}/annotations")
        if failed:
            errors.append(f"annotations of {check.get('name')}: {failed}")
        for note in notes:
            message = " ".join(str(note.get("message") or "").split())
            # the runner's own notices carry the path .github, a linter's warning the file it flagged
            runner = str(note.get("path") or "").startswith(".github")
            if runner and note.get("annotation_level") in ("notice", "warning") and DEPRECATION.search(message):
                notices.append({
                    "message": message,
                    "level": note.get("annotation_level"),
                    "workflow": str(run.get("name")),
                    "job": str(check.get("name")),
                    "run_at": str(run.get("created_at") or ""),
                })
    return notices, errors


def is_old(notice: dict[str, Any], as_of: str) -> bool:
    """
    Whether a notice comes from a run older than NOTICE_DAYS, which a workflow that rarely runs, a deploy or a token
    rotation, keeps showing long after its code changed.

    Args:
        notice: the notice, its `run_at` the run's start as GitHub gives it
        as_of: the time it is measured from, the snapshot's own

    Returns:
        bool: True for a run older than NOTICE_DAYS, False when either time is missing, so an undated notice counts
    """
    try:
        ran  = datetime.strptime(str(notice.get("run_at") or ""), STAMP)
        when = datetime.strptime(as_of, STAMP)
    except ValueError:
        return False
    return (when - ran).days > NOTICE_DAYS


def collect_notices(transport: Transport, repo: str) -> tuple[list[dict[str, str]], list[str]]:
    """
    The deprecation notices on the latest completed run of each of a repo's active workflows, each asked of its own
    workflow, so a busy one never hides another's. GitHub's own dynamic workflows (Dependabot's, CodeQL's default
    setup) are left out.

    Args:
        transport: how GitHub is reached
        repo: `owner/name`

    Returns:
        tuple[list[dict[str, str]], list[str]]: each notice's message, level, workflow and job, and what could not be
        read
    """
    flows, error = read_pages(transport, f"/repos/{repo}/actions/workflows", key = "workflows")
    errors = [f"workflows: {error}"] if error else []
    notices: list[dict[str, str]] = []
    for flow in flows:
        if flow.get("state") != "active" or str(flow.get("path") or "").startswith("dynamic/"):
            continue
        resp = transport.get(
            f"/repos/{repo}/actions/workflows/{flow.get('id')}/runs",
            {"status": "completed", "per_page": 1},
        )
        runs = resp.data.get("workflow_runs") if resp.ok and isinstance(resp.data, dict) else None
        if not isinstance(runs, list):
            errors.append(f"runs of {flow.get('name')}: {resp.reason()}")
            continue
        if runs and runs[0].get("check_suite_id"):
            found, failed = run_notices(transport, repo, runs[0])
            notices      += found
            errors       += failed
    return notices, errors


def judge_pin(
    pin: dict[str, str],
    release: Release,
    holds_latest: Callable[[str], bool | None] | None = None,
) -> dict[str, Any]:
    """
    One pin's verdict, a ref against the latest tag, or an npm range against the latest version.

    Args:
        pin: the pin, as find_pins gives it
        release: its source repo's latest release
        holds_latest: whether a commit of its source repo holds the latest release, as judge takes it

    Returns:
        dict[str, Any]: the pin's file, package and source with the verdict of judge
    """
    if pin.get("npm"):
        latest  = semver(release.tag) if release.tag else None
        allowed = npm_allows(pin["ref"], latest) if latest else None
        if allowed:
            note = "range admits the latest"
        elif allowed is False:
            note = "range does not admit the latest"
        else:
            note = "range not judged" + (f", latest release unknown ({release.error})" if release.error else "")
        verdict = {
            "pinned": pin["ref"],
            "latest": release.tag,
            "behind": allowed is False,
            "judged": allowed is not None,
            "note": note,
        }
    else:
        verdict = judge(pin["ref"], release, holds_latest)
    return {"file": pin["file"], "package": pin["package"], "source": pin["repo"], **verdict}


def collect_repo(
    transport: Transport,
    repo: str,
    releases: Releases,
    kit_set: set[str],
    scripts: dict[str, list[dict]],
    kit_version: str,
    canonical: dict[str, str | None],
) -> dict[str, Any]:
    """
    Everything the watch reads for one repo, an answer of a shape it does not know made this repo's blind spot rather
    than the end of the run.

    Args:
        transport: how GitHub is reached
        repo: `owner/name`
        releases: each source repo's release, a new source repo read on its first sight
        kit_set: the kit's targets
        scripts: each scripts target's vendored files
        kit_version: cicd's kit version
        canonical: each script source's blob sha on cicd's main

    Returns:
        dict[str, Any]: the repo's alerts, judged pins, drift, notices and what could not be read
    """
    try:
        alerts = collect_alerts(transport, repo)
        pins, pin_errors = collect_pins(transport, repo)
        drift, drift_errors = collect_drift(transport, repo, kit_set, scripts, kit_version, canonical)
        notices, run_errors = collect_notices(transport, repo)
        judged = [
            judge_pin(pin, releases.get(pin["repo"]), partial(releases.holds_latest, pin["repo"])) for pin in pins
        ]
    except Exception as exc:  # noqa: BLE001, a blind spot named by its type, never the run's end
        detail = f"the read failed, {type(exc).__name__}"
        empty  = {"status": "unavailable", "reason": detail, "open": []}
        failed = [{"section": "repo", "detail": detail}]
        return {"repo": repo, "alerts": empty, "pins": [], "drift": [], "notices": [], "errors": failed}
    errors = [{"section": "pins", "detail": detail} for detail in pin_errors]
    errors += [{"section": "drift", "detail": detail} for detail in drift_errors]
    errors += [{"section": "notices", "detail": detail} for detail in run_errors]
    if alerts["status"] != "ok":
        errors.append({"section": "alerts", "detail": alerts["reason"]})
    return {"repo": repo, "alerts": alerts, "pins": judged, "drift": drift, "notices": notices, "errors": errors}


def canonical_scripts(transport: Transport, scripts: dict[str, list[dict]]) -> dict[str, str | None]:
    """
    The blob sha of each vendored script's source on cicd's main, the copy every repo should hold.

    Args:
        transport: how GitHub is reached
        scripts: each scripts target's vendored files

    Returns:
        dict[str, str | None]: each source path's blob sha, None when it could not be read
    """
    sources = sorted({entry["src"] for files in scripts.values() for entry in files})
    out: dict[str, str | None] = {}
    for src in sources:
        resp = transport.get(f"/repos/{CICD_REPO}/contents/{src}")
        out[src] = resp.data.get("sha") if resp.ok and isinstance(resp.data, dict) else None
    return out


def collect(transport: Transport, workers: int = 8, now: datetime | None = None) -> dict[str, Any]:
    """
    The whole snapshot, every repo read in parallel and none of them written.

    Args:
        transport: how GitHub is reached
        workers: how many repos are read at once
        now: the snapshot's time, now when None

    Returns:
        dict[str, Any]: the snapshot, schema kdf-ecosystem-watch/1
    """
    repos, kit_set, scripts, kit_version, fmt_pin = read_registries()
    releases = Releases(transport)
    for source in RELEASE_REPOS:
        releases.get(source)
    canonical = canonical_scripts(transport, scripts)
    with ThreadPoolExecutor(max_workers = workers) as pool:
        results = list(pool.map(
            lambda repo: collect_repo(transport, repo, releases, kit_set, scripts, kit_version, canonical),
            repos,
        ))
    canonical_pin = {
        "file": "scripts/scripts_registry.json",
        "package": "kdf-fmt (canonical pin)",
        "source": "kriegerdataforge-fmt",
        **judge(fmt_pin, releases.get("kriegerdataforge-fmt")),
    }
    for result in results:
        if result["repo"] == CICD_REPO:
            result["pins"].append(canonical_pin)
    missing = sorted(src for src, sha in canonical.items() if sha is None)
    stamp   = (now or datetime.now(timezone.utc)).strftime(STAMP)
    known   = sorted(releases.known.items())
    summary = summarize(results, stamp)
    # an unreadable tag list or script source is a blind spot, counted with the repos' own
    summary["errors"] += sum(1 for source, release in known if release.error) + len(missing)
    return {
        "schema": SCHEMA,
        "generated_at": stamp,
        "owner": OWNER,
        "kit_version": kit_version,
        "releases": {name: {"tag": release.tag, "error": release.error} for name, release in known},
        "canonical_scripts_unreadable": missing,
        "repos": results,
        "summary": summary,
    }


def summarize(results: list[dict[str, Any]], as_of: str = "") -> dict[str, Any]:
    """
    The counts the log and the issue's first line carry.

    Args:
        results: every repo's result
        as_of: the snapshot's time, which tells a notice of a recent run from an old one, every notice recent without
            it

    Returns:
        dict[str, Any]: alerts by severity and in all, pins behind and pins not judged, drift, distinct notices of
        recent runs and of old ones, and errors
    """
    severity = {name: 0 for name in (*SEVERITIES, "unknown")}
    for result in results:
        for alert in result["alerts"]["open"]:
            severity[alert["severity"] if alert["severity"] in severity else "unknown"] += 1
    every  = [notice for result in results for notice in result["notices"]]
    recent = {notice["message"] for notice in every if not is_old(notice, as_of)}
    old    = {notice["message"] for notice in every if is_old(notice, as_of)} - recent
    return {
        "alerts": severity,
        "alerts_total": sum(severity.values()),
        "pins_behind": sum(1 for result in results for pin in result["pins"] if pin["behind"]),
        "pins_unjudged": sum(1 for result in results for pin in result["pins"] if not pin["judged"]),
        "drift": sum(len(result["drift"]) for result in results),
        "notices": len(recent),
        "notices_old": len(old),
        "errors": sum(len(result["errors"]) for result in results),
    }

# ======================================================================================================================
# Rendering
# ======================================================================================================================

def _short(text: str) -> str:
    """
    A short stable id for a text in a finding's key.

    Args:
        text: a notice's message or an error's detail

    Returns:
        str: the first 12 hex of its sha1
    """
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def remembered(key: str) -> str:
    """
    How a finding's key is kept in the body, short and fixed in length, so a body of thousands stays under the limit.

    Args:
        key: the finding's key

    Returns:
        str: the first KEY_HEX hex of its sha1
    """
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:KEY_HEX]


def previous_keys(body: str) -> set[str]:
    """
    The remembered findings an earlier body carried in its hidden marker.

    Args:
        body: the open issue's current body

    Returns:
        set[str]: the remembered keys, empty when it has no marker or a broken one
    """
    # only the marker that closes the body counts, so a marker inside a notice or an error text never does
    match = re.search(r"<!--\s*" + re.escape(KEYS_MARKER) + r"([0-9a-f]*)\s*-->\s*\Z", body or "")
    if not match or len(match.group(1)) % KEY_HEX:
        return set()
    hexes = match.group(1)
    return {hexes[index:index + KEY_HEX] for index in range(0, len(hexes), KEY_HEX)}


def _cell(text: Any) -> str:
    """
    A value made safe for a markdown table cell.

    Args:
        text: the value

    Returns:
        str: the value with its pipes escaped and its newlines made spaces
    """
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def _safe(text: str) -> str:
    """
    A string from GitHub made inert in an issue body. A notice's message, a workflow's name or an error's text is
    written by whatever ran in a repo, a third party action or a fork's run included, so it may open an HTML comment
    that hides the rest of the body, close a code span, or mention a person.

    Args:
        text: the string

    Returns:
        str: the string with `&`, `<` and `>` escaped, backticks made quotes, `@` unable to mention and newlines made
        spaces
    """
    out = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out = out.replace("`", "'").replace("@", "@\u200b")
    return out.replace("\r", " ").replace("\n", " ")


def _sanitized(value: Any) -> Any:
    """
    A copy of a snapshot with every string in it made inert, and a link kept only when it points at github.com.

    Args:
        value: the snapshot, or any part of it

    Returns:
        Any: the copy
    """
    if isinstance(value, str):
        return _safe(value)
    if isinstance(value, list):
        return [_sanitized(item) for item in value]
    if isinstance(value, dict):
        out = {key: _sanitized(item) for key, item in value.items()}
        if "url" in out and not str(value.get("url") or "").startswith("https://github.com/"):
            out["url"] = None
        return out
    return value


def _name(repo: str) -> str:
    """
    A repo's name without its owner.

    Args:
        repo: `owner/name`

    Returns:
        str: the name
    """
    return repo.split("/")[1]


def _alerts_section(repos: list[dict[str, Any]], findings: dict[str, str]) -> list[str]:
    """
    The alerts table and each repo's alerts, most severe first, at most ALERTS_SHOWN listed.

    Args:
        repos: every repo's result
        findings: each finding's key and its news line, added to

    Returns:
        list[str]: the section's lines
    """
    lines       = ["", "### Dependabot alerts", ""]
    with_alerts = [result for result in repos if result["alerts"]["open"]]
    if not with_alerts:
        return lines + ["None open."]
    lines += ["| Repo | Critical | High | Medium | Low |", "| --- | --- | --- | --- | --- |"]
    for result in with_alerts:
        counts = [sum(1 for alert in result["alerts"]["open"] if alert["severity"] == level) for level in SEVERITIES]
        lines.append(f"| {_name(result['repo'])} | " + " | ".join(str(count) for count in counts) + " |")
    for result in with_alerts:
        name   = _name(result["repo"])
        ranked = sorted(
            result["alerts"]["open"],
            key = lambda alert: (
                SEVERITIES.index(alert["severity"]) if alert["severity"] in SEVERITIES else 9,
                str(alert["package"]),
            ),
        )
        lines += ["", f"**{name}**"]
        for alert in ranked[:ALERTS_SHOWN]:
            fixed    = f", fixed in {alert['patched']}" if alert["patched"] else ", no fixed version yet"
            advisory = alert["advisory"] or alert["cve"] or "no advisory id"
            link     = f"[alert {alert['number']}]({alert['url']})" if alert["url"] else f"alert {alert['number']}"
            lines.append(f"- **{alert['severity']}** {alert['ecosystem']} `{alert['package']}` in "
                         f"`{alert['manifest']}`{fixed}, {advisory}, {link}")
        for alert in result["alerts"]["open"]:
            findings[f"alert:{result['repo']}:{alert['number']}"] = (
                f"{name}, {alert['severity']} alert on `{alert['package']}` ({alert['advisory'] or alert['cve']})"
            )
        if len(ranked) > ALERTS_SHOWN:
            lines.append(f"- and {len(ranked) - ALERTS_SHOWN} more, see the repo's Security tab")
    return lines


def _pins_section(repos: list[dict[str, Any]], findings: dict[str, str]) -> list[str]:
    """
    The pins behind their latest release, and the pins the watch could not judge, each a finding, since a pin of an
    unknown release may be behind it.

    Args:
        repos: every repo's result
        findings: each finding's key and its news line, added to

    Returns:
        list[str]: the section's lines
    """
    lines    = ["", "### Pins behind their latest release", ""]
    behind   = [(_name(result["repo"]), pin) for result in repos for pin in result["pins"] if pin["behind"]]
    unjudged = [(_name(result["repo"]), pin) for result in repos for pin in result["pins"] if not pin["judged"]]
    if behind:
        lines += ["| Repo | File | Package | Pinned | Latest | Note |", "| --- | --- | --- | --- | --- | --- |"]
        for name, pin in behind:
            pinned = pin["pinned"][:12] if FULL_SHA.match(pin["pinned"]) else pin["pinned"]
            lines.append(f"| {name} | `{_cell(pin['file'])}` | {_cell(pin['package'])} | `{_cell(pinned)}` | "
                         f"{_cell(pin['latest'])} | {_cell(pin['note'] or '')} |")
            findings[f"pin:{name}:{pin['file']}:{pin['package']}:{pin['pinned']}"] = (
                f"{name}, `{pin['package']}` in `{pin['file']}` pinned at `{pinned}`, latest {pin['latest']}"
            )
    elif unjudged:
        lines.append("No pin that could be judged is behind.")
    else:
        lines.append("Every pin is at its latest release.")
    for name, pin in unjudged:
        lines.append(f"- not judged, {name} `{pin['file']}` `{pin['package']}` `{pin['pinned']}`, {pin['note']}")
        findings[f"unjudged:{name}:{pin['file']}:{pin['package']}:{pin['pinned']}"] = (
            f"{name}, `{pin['package']}` in `{pin['file']}` could not be judged, {pin['note']}"
        )
    return lines


def _drift_section(snapshot: dict[str, Any], findings: dict[str, str]) -> list[str]:
    """
    The kit and script drift.

    Args:
        snapshot: the snapshot
        findings: each finding's key and its news line, added to

    Returns:
        list[str]: the section's lines
    """
    lines   = ["", "### Kit and script drift", ""]
    drifted = [(_name(result["repo"]), drift) for result in snapshot["repos"] for drift in result["drift"]]
    if not drifted:
        return lines + [f"Every repo is on kit {snapshot['kit_version']} and cicd's dev scripts."]
    lines += ["| Repo | What | Path | Has | Should have |", "| --- | --- | --- | --- | --- |"]
    for name, drift in drifted:
        lines.append(f"| {name} | {drift['kind']} | `{drift['path']}` | `{drift['have']}` | `{drift['want']}` |")
        findings[f"drift:{name}:{drift['path']}:{drift['have']}"] = f"{name}, `{drift['path']}` drifted from cicd"
    return lines + ["", "A Distribute of the kit or the scripts brings them back."]


def _notice_lines(seen: dict[str, list[str]]) -> list[str]:
    """
    Each notice once, with where it was seen, at most NOTICES_SHOWN of them.

    Args:
        seen: each notice's message and the places it was seen in

    Returns:
        list[str]: the lines
    """
    lines = []
    for message, where in list(seen.items())[:NOTICES_SHOWN]:
        lines += [f"- {message}", f"  Seen in {', '.join(where)}."]
    if len(seen) > NOTICES_SHOWN:
        lines.append(f"- and {len(seen) - NOTICES_SHOWN} more")
    return lines


def _notices_section(repos: list[dict[str, Any]], findings: dict[str, str], as_of: str) -> list[str]:
    """
    Each distinct deprecation notice once, with every repo and workflow it was seen in. A notice seen only on runs
    older than NOTICE_DAYS is listed apart with its run's date and is no finding, since only a new run of that
    workflow can clear it, and for a deploy that is no reason to run one.

    Args:
        repos: every repo's result
        findings: each finding's key and its news line, added to
        as_of: the snapshot's time

    Returns:
        list[str]: the section's lines
    """
    lines = ["", "### Deprecation notices", ""]
    recent: dict[str, list[str]] = {}
    old:    dict[str, list[str]] = {}
    for result in repos:
        for notice in result["notices"]:
            stale = is_old(notice, as_of)
            ran   = f", last ran {notice['run_at'][:10]}" if stale else ""
            where = f"{_name(result['repo'])} ({notice['workflow']}{ran})"
            group = old if stale else recent
            if where not in group.setdefault(notice["message"], []):
                group[notice["message"]].append(where)
    # a notice that a recent run carries too is a finding, its old sightings listed with the recent ones
    for message in [message for message in old if message in recent]:
        recent[message] += old.pop(message)
    lines += _notice_lines(recent) if recent else ["None on the latest runs."]
    for message in list(recent)[:NOTICES_SHOWN]:
        findings[f"notice:{_short(message)}"] = f"a deprecation notice, {message[:160]}"
    if old:
        note = f"Only on runs older than {NOTICE_DAYS} days, so not counted. A new run of the workflow clears them."
        lines += ["", note, ""] + _notice_lines(old)
    return lines


def _errors_section(snapshot: dict[str, Any], findings: dict[str, str]) -> list[str]:
    """
    What could not be read, which keeps the issue open, since a blind spot is a finding too.

    Args:
        snapshot: the snapshot
        findings: each finding's key and its news line, added to

    Returns:
        list[str]: the section's lines
    """
    lines   = ["", "### Could not read", ""]
    errored = [(_name(result["repo"]), error) for result in snapshot["repos"] for error in result["errors"]]
    if errored:
        for name, error in errored:
            lines.append(f"- {name}, {error['section']}, {error['detail']}")
            findings[f"error:{name}:{error['section']}:{_short(error['detail'])}"] = (
                f"{name} could not be read, {error['detail']}"
            )
        lines += ["", "A 403 on alerts usually means the KDF GitHub App lacks 'Dependabot alerts: Read' on that repo."]
    else:
        lines.append("Everything was read.")
    for src in snapshot.get("canonical_scripts_unreadable", []):
        lines.append(f"- cicd's own `{src}` could not be read, so its copies were not compared")
        findings[f"error:cicd:{src}"] = f"cicd's own `{src}` could not be read"
    # a source repo whose tags could not be read leaves every pin of it unjudged, which is a blind spot too
    for source, release in sorted(snapshot.get("releases", {}).items()):
        if release.get("error"):
            lines.append(
                f"- the release tags of {source} could not be read, {release['error']}, so no pin of it was " "judged",
            )
            findings[f"error:release:{source}:{_short(release['error'])}"] = (
                f"the release tags of {source} could not be read, {release['error']}"
            )
    return lines


def render(snapshot: dict[str, Any], previous_body: str = "", run_url: str = "") -> tuple[str, str, str]:
    """
    The issue's body, the news since the previous body, and the state.

    Args:
        snapshot: the snapshot
        previous_body: the open issue's current body, empty when there is none
        run_url: the run's link for the footer

    Returns:
        tuple[str, str, str]: the body, the news (empty on a first body or when nothing is new), and `open` while
        anything is found or unreadable, `clear` when nothing is
    """
    snapshot = _sanitized(snapshot)
    findings: dict[str, str] = {}
    summary   = snapshot["summary"]
    counts    = summary["alerts"]
    breakdown = f"{counts['critical']} critical, {counts['high']} high, {counts['medium']} medium, {counts['low']} low"
    headline  = ", ".join([
        f"**{summary['alerts_total']} open Dependabot alerts** ({breakdown})",
        f"**{summary['pins_behind']} pins behind**",
        f"**{summary['pins_unjudged']} pins not judged**",
        f"**{summary['drift']} kit or script drifts**",
        f"**{summary['notices']} deprecation notices**",
        f"**{summary['errors']} could not be read**",
    ])
    lines     = [f"## Ecosystem watch, {snapshot['generated_at'][:10]}", "", headline + "."]
    lines += _alerts_section(snapshot["repos"], findings)
    lines += _pins_section(snapshot["repos"], findings)
    lines += _drift_section(snapshot, findings)
    lines += _notices_section(snapshot["repos"], findings, snapshot["generated_at"])
    lines += _errors_section(snapshot, findings)
    run   = f", [run]({run_url})" if run_url else ""
    stamp = f"Snapshot `{snapshot['schema']}` of {snapshot['generated_at']}{run}."
    lines += ["", "---", f"{stamp} Read only, cicd's ecosystem watch (D-049)."]

    kept   = sorted({remembered(key) for key in findings})[:KEYS_LIMIT]
    marker = f"<!-- {KEYS_MARKER}{''.join(kept)} -->"
    body   = "\n".join(lines)
    if len(body) + len(marker) > BODY_LIMIT:
        body = body[: BODY_LIMIT - len(marker) - 200] + "\n\n_The body was cut at GitHub's size limit._"
    body = body + "\n\n" + marker + "\n"

    before   = previous_keys(previous_body)
    new_keys = sorted(key for key in findings if remembered(key) not in before)
    news     = ""
    if new_keys and previous_body:
        shown = new_keys[:NEWS_SHOWN]
        news  = "New since the last run:\n\n" + "\n".join(f"- {findings[key]}" for key in shown) + "\n"
        if len(new_keys) > len(shown):
            news += f"- and {len(new_keys) - len(shown)} more, see the body\n"
    state = "open" if findings else "clear"
    return body, news, state

# ======================================================================================================================
# Command line
# ======================================================================================================================

def main(argv: list[str] | None = None) -> int:
    """
    Collect or render, as the command line says.

    Args:
        argv: the arguments, sys.argv's when None

    Returns:
        int: 0 done, 2 no token for the http transport
    """
    parser = argparse.ArgumentParser(description = "The KDF ecosystem watch, read only (ADR D-049).")
    sub    = parser.add_subparsers(dest = "command", required = True)

    run = sub.add_parser("collect", help = "read GitHub and write the snapshot")
    run.add_argument("--out", required = True, help = "where the snapshot JSON goes")
    run.add_argument("--transport", choices = ("http", "gh"), default = "http")

    out = sub.add_parser("render", help = "turn a snapshot into the issue body, the news and the state")
    out.add_argument("--snapshot", required = True)
    out.add_argument("--previous", help = "the open issue's current body, when there is one")
    out.add_argument("--body", required = True)
    out.add_argument("--news", required = True)
    out.add_argument("--state", required = True)
    out.add_argument("--run-url", default = "")

    args = parser.parse_args(argv)
    if args.command == "collect":
        if args.transport == "gh":
            transport: Transport = GhTransport()
        else:
            token = os.environ.get("GH_TOKEN", "")
            if not token:
                print("ecosystem-watch: GH_TOKEN is not set", file = sys.stderr)
                return 2
            transport = HttpTransport(token)
        snapshot = collect(transport)
        Path(args.out).write_text(json.dumps(snapshot, indent = 2) + "\n", encoding = "utf-8")
        summary = snapshot["summary"]
        print(f"ecosystem-watch: {len(snapshot['repos'])} repos, {summary['alerts_total']} open alerts, "
              f"{summary['pins_behind']} pins behind, {summary['pins_unjudged']} not judged, {summary['drift']} "
              f"drifts, {summary['notices']} notices, {summary['errors']} could not be read")
        return 0

    snapshot = json.loads(Path(args.snapshot).read_text(encoding = "utf-8"))
    previous = ""
    if args.previous and Path(args.previous).exists():
        previous = Path(args.previous).read_text(encoding = "utf-8")
    body, news, state = render(snapshot, previous, args.run_url)
    Path(args.body).write_text(body, encoding = "utf-8")
    Path(args.news).write_text(news, encoding = "utf-8")
    Path(args.state).write_text(state + "\n", encoding = "utf-8")
    print(f"ecosystem-watch: state {state}, {len(news.splitlines())} news lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
