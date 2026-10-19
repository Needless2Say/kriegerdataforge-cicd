"""
The images section of the ecosystem watch (ADR D-080, item 10).

It reads the copier, `.github/workflows/mirror-ci-images.yml`, from cicd's `main` as text, and parses its KEPT,
PINNED, FOLLOWED and WATCH blocks by the shapes cicd's image test holds. Then it asks, and writes nothing anywhere.

  watched   for each WATCH line, the line's publisher alone, never a mirror that can lag, for the line's upstream tag
            by a HEAD that Docker Hub counts toward no limit. A digest other than the kept one is read for its
            version, from its config, else, for an image whose config names none, as Mailpit's names none, from the
            publisher's release tag of the kept tag's shape whose index digest is the same (the owner's answer of
            2026-10-19). A newer version at the line's level, patch or Checkov's minor, is a finding. The same version
            or a newer one below the level is a rebuild, one quiet note line
  followed  for each followed tag, Docker Hub's tag list read for a newer tag of the same shape, `26-alpine` after
            `24-alpine`, named in a quiet note when one exists, never a finding, since moving runtime is a migration
            the owner chooses (the owner's answer of 2026-10-19)
  trivy     the Trivy release the terraform repo's security scan pins in its `version` input, beside Trivy's latest
            GitHub release, since the scan's rules move with that version alone
  schedule  the copier's newest scheduled run, named when red or more than two days old

GitHub is read through the watch's own transport. The registries are read through a client of their own with
anonymous pull tokens, never the App token, each read bounded in time and retries, every tag list in pages, and the
whole section in one time budget, so it ends well inside the watch's 15 minutes. A read that fails, copier text out of
its shapes, a tag list cut short, a config with no version and no matching tag, a missing scheduled run or a date that
does not parse names its image or its part unread, never current, which keeps the issue open.
"""

from __future__ import annotations

# standard imports
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

# ======================================================================================================================
# Configuration
# ======================================================================================================================

OWNER          = "Needless2Say"
CICD_REPO      = f"{OWNER}/kriegerdataforge-cicd"
COPIER_PATH    = ".github/workflows/mirror-ci-images.yml"
COPIER_FILE    = "mirror-ci-images.yml"
TERRAFORM_REPO = f"{OWNER}/kriegerdataforge-terraform"
SECURITY_PATH  = ".github/workflows/security.yml"
TRIVY_REPO     = "aquasecurity/trivy"

# each entry's exact shape, as cicd's image test holds them, `scripts/tests/copier_rule.py`
KEPT_ENTRY     = re.compile(r"^    (?P<digest>sha256:[0-9a-f]{64}) (?P<tag>[0-9][0-9.]*) (?P<version>[0-9]{6})$")
PINNED_ENTRY   = re.compile(r"^    (?P<name>[a-z0-9-]+) (?P<digest>sha256:[0-9a-f]{64}) (?P<tag>[0-9a-z][0-9a-z.-]*)$")
FOLLOWED_ENTRY = re.compile(r"^    (?P<name>[a-z0-9-]+) (?P<tag>[0-9][0-9a-z.-]*)(?: (?P<hold>sha256:[0-9a-f]{64}))?$")
WATCH_SHAPE    = (
    r"^    (?P<name>[a-z0-9-]+) (?P<tag>[0-9a-z][0-9a-z.-]*) (?P<publisher>[a-z0-9./-]+)"
    r" (?P<upstream>[0-9a-z][0-9a-z.-]*) (?P<level>patch|minor)$"
)
WATCH_ENTRY    = re.compile(WATCH_SHAPE)

DIGEST    = re.compile(r"^sha256:[0-9a-f]{64}$")
VERSION   = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?")
NEXT_PAGE = re.compile(r"""<(?P<url>/v2/[^>\s]+)>\s*;\s*rel="?next"?""")

# a version text a publisher writes, kept only in this shape, so no text of a publisher's reaches the issue as written
VERSION_TEXT = re.compile(r"^v?\d+\.\d+(?:\.\d+)?(?:[.+~-][0-9A-Za-z.+~-]{1,40})?$")
TRIVY_PIN    = re.compile(r"""^\s+version:\s*["']?(?P<version>v?\d+\.\d+\.\d+)["']?\s*$""")

# the media types a HEAD asks for and an index answers with
INDEX_TYPES = ("application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json")
IMAGE_TYPES = ("application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json")

# each publisher host, the registry it answers on and how an anonymous pull token is asked for a repository
REGISTRIES = {
    "docker.io": (
        "registry-1.docker.io",
        "https://auth.docker.io/token?service=registry.docker.io&scope=repository:{}:pull",
    ),
    "ghcr.io": ("ghcr.io", "https://ghcr.io/token?scope=repository:{}:pull"),
}

# where an image's config names its version beyond the OCI label, `<NAME>_VERSION` otherwise
VERSION_ENV = {"postgres": "PG_VERSION"}

TIMEOUT         = 20       # seconds a socket waits for one read
REQUEST_SECONDS = 60   # seconds one request's body may take in all
MAX_BODY        = 4194304  # bytes one answer may hold, a tag list page of 1000 tags being some 30000
RETRIES         = 2        # tries again after a refusal, a 5xx or a dead connection
BUDGET          = 300      # seconds for every registry read of the section, well inside the watch's 15 minutes
TAG_PAGE        = 1000     # tags asked for in one page
TAG_PAGES       = 20       # pages read of one tag list at most, 20000 tags, a longer list is cut short and unread
CANDIDATES      = 10       # release tags asked by HEAD at most for an image whose config names no version
RUN_DAYS        = 2        # a scheduled run older than this is named
NEWER_SHOWN     = 3        # newer followed tags named at most
STAMP           = "%Y-%m-%dT%H:%M:%SZ"

# ======================================================================================================================
# The registry client, anonymous
# ======================================================================================================================

@dataclass
class Reply:
    """
    One registry answer, its status, its headers with their names lower case, and its body.
    """
    status: int
    headers: dict[str, str] = field(default_factory = dict)
    body:    bytes = b""


class Unread(Exception):
    """
    A read that could not be made, its reason the message.
    """


class Fetch(Protocol):
    """
    One HTTP request, as the client makes it.
    """
    def __call__(self, url: str, headers: dict[str, str], method: str) -> Reply:
        """
        Args:
            url: the URL
            headers: the request's headers
            method: GET or HEAD

        Returns:
            Reply: the answer, an HTTP error's included
        """


def urllib_fetch(url: str, headers: dict[str, str], method: str) -> Reply:
    """
    One request over the standard library, an HTTP error answered as its status.

    Args:
        url: the URL
        headers: the request's headers
        method: GET or HEAD

    Returns:
        Reply: the answer, status 0 when no answer came, or when its body passed MAX_BODY bytes or took longer than
        REQUEST_SECONDS, so a publisher that streams slowly never holds the watch past its budget
    """
    request = urllib.request.Request(url, headers = headers, method = method)
    began   = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout = TIMEOUT) as answer:
            body = b""
            while method == "GET":
                chunk = answer.read(65536)
                if not chunk:
                    break
                body += chunk
                if len(body) > MAX_BODY or time.monotonic() - began > REQUEST_SECONDS:
                    return Reply(0)
            return Reply(answer.status, {key.lower(): value for key, value in answer.headers.items()}, body)
    except urllib.error.HTTPError as error:
        return Reply(error.code, {key.lower(): value for key, value in error.headers.items()})
    except (urllib.error.URLError, TimeoutError, OSError):
        return Reply(0)


class RegistryClient:
    """
    Anonymous reads of a public registry, a pull token per repository, bounded in retries and in one time budget.
    """
    def __init__(
        self,
        fetch: Fetch = urllib_fetch,
        budget: float = BUDGET,
        clock: Callable[[], float] = time.monotonic,
        pause: Callable[[float], None] = time.sleep,
    ) -> None:
        """
        Args:
            fetch: how one request is made
            budget: seconds for every read this client makes
            clock: a monotonic clock
            pause: how the client waits between tries
        """
        self._fetch = fetch
        self._clock = clock
        self._pause = pause
        self._ends  = clock() + budget
        self._tokens: dict[tuple[str, str], str] = {}


    def _request(self, url: str, headers: dict[str, str], method: str) -> Reply:
        """
        One request, tried again after a refusal, a 5xx or no answer, never past the budget.

        Args:
            url: the URL
            headers: the request's headers
            method: GET or HEAD

        Returns:
            Reply: the last answer

        Raises:
            Unread: the budget ran out before a try, or while one ran, its answer then never used
        """
        reply = Reply(0)
        for attempt in range(RETRIES + 1):
            if self._clock() >= self._ends:
                raise Unread("the section's time budget ran out")
            reply = self._fetch(url, headers, method)
            if self._clock() >= self._ends:
                raise Unread("the section's time budget ran out")
            if reply.status and reply.status != 429 and reply.status < 500:
                return reply
            if attempt < RETRIES:
                self._pause(2 ** attempt)
        return reply


    def _token(self, host: str, repo: str) -> str:
        """
        An anonymous pull token for one repository, asked once.

        Args:
            host: the publisher's host, `docker.io` or `ghcr.io`
            repo: the repository on it

        Returns:
            str: the token, checked for its shape

        Raises:
            Unread: no token, or one of another shape
        """
        if (host, repo) not in self._tokens:
            reply = self._request(REGISTRIES[host][1].format(repo), {}, "GET")
            try:
                token = json.loads(reply.body or b"{}").get("token") or ""
            except ValueError:
                token = ""
            # a JWT's characters, or base64's, as GitHub's registry answers its anonymous token
            if reply.status != 200 or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", token):
                raise Unread(f"no anonymous token for {host}/{repo}, answer {reply.status or 'none'}")
            self._tokens[(host, repo)] = token
        return self._tokens[(host, repo)]


    def get(self, reference: str, path: str, accept: tuple[str, ...] = (), method: str = "GET") -> Reply:
        """
        One read of a publisher's repository.

        Args:
            reference: `docker.io/library/caddy` or `ghcr.io/axllent/mailpit`
            path: what follows `/v2/<repo>/`, such as `manifests/<tag>` or `tags/list?n=1000`
            accept: the media types asked for
            method: GET or HEAD

        Returns:
            Reply: the answer, any status

        Raises:
            Unread: a reference on no registry the watch reads, no token, or the budget spent
        """
        host, _, repo = reference.partition("/")
        if host not in REGISTRIES or not repo:
            raise Unread(f"{reference} is on no registry the watch reads")
        headers = {"Authorization": f"Bearer {self._token(host, repo)}"}
        if accept:
            headers["Accept"] = ", ".join(accept)
        return self._request(f"https://{REGISTRIES[host][0]}/v2/{repo}/{path}", headers, method)


    def head_digest(self, reference: str, tag: str) -> str:
        """
        The index digest a tag names, by a HEAD asking for an index, its line end stripped and its shape checked.

        Args:
            reference: the publisher's repository
            tag: the tag, or a digest

        Returns:
            str: the digest

        Raises:
            Unread: an answer that is not a 200 with an index's type and a digest of its shape
        """
        reply  = self.get(reference, f"manifests/{tag}", INDEX_TYPES, "HEAD")
        kind   = reply.headers.get("content-type", "").split(";")[0].strip()
        digest = reply.headers.get("docker-content-digest", "").strip()
        if reply.status != 200 or kind not in INDEX_TYPES or not DIGEST.match(digest):
            raise Unread(f"{reference}:{tag} answered {reply.status or 'nothing'}, not an index's digest")
        return digest


    def json(self, reference: str, path: str, accept: tuple[str, ...] = ()) -> Any:
        """
        A GET whose body is JSON.

        Args:
            reference: the publisher's repository
            path: what follows `/v2/<repo>/`
            accept: the media types asked for

        Returns:
            Any: the parsed body

        Raises:
            Unread: a status other than 200, or a body that is not JSON
        """
        reply = self.get(reference, path, accept)
        if reply.status != 200:
            raise Unread(f"{reference} {path.split('?')[0]} answered {reply.status or 'nothing'}")
        try:
            return json.loads(reply.body)
        except ValueError as exc:
            raise Unread(f"{reference} {path.split('?')[0]} answered no JSON") from exc


    def tags(self, reference: str) -> list[str]:
        """
        Every tag of a repository, page by page, at most TAG_PAGES pages.

        Args:
            reference: the publisher's repository

        Returns:
            list[str]: every tag

        Raises:
            Unread: a page that failed, a next page outside the repository, or a list longer than the pages read, cut
                short
        """
        found: list[str] = []
        root = f"/v2/{reference.partition('/')[2]}/"
        path = f"tags/list?n={TAG_PAGE}"
        for _ in range(TAG_PAGES):
            reply = self.get(reference, path)
            if reply.status != 200:
                raise Unread(f"{reference}'s tag list answered {reply.status or 'nothing'}")
            try:
                page = json.loads(reply.body)
            except ValueError as exc:
                raise Unread(f"{reference}'s tag list answered no JSON") from exc
            names = page.get("tags") if isinstance(page, dict) else None
            if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
                raise Unread(f"{reference}'s tag list has an unexpected shape")
            found += names
            following = NEXT_PAGE.search(reply.headers.get("link", ""))
            if following:
                # the registry names the next page, which is read whatever this page's length
                if not following.group("url").startswith(root):
                    raise Unread(f"{reference}'s tag list names a next page outside the repository")
                path = following.group("url")[len(root):]
            elif len(names) < TAG_PAGE:
                return found
            else:
                path = f"tags/list?n={TAG_PAGE}&last={names[-1]}"
        raise Unread(f"{reference}'s tag list is longer than {TAG_PAGES} pages, cut short")

# ======================================================================================================================
# The copier's text
# ======================================================================================================================

def env_block(text: str, key: str) -> list[str]:
    """
    One of the copier's env blocks.

    Args:
        text: the copier's text
        key: the block's key, such as `WATCH`

    Returns:
        list[str]: each line below `  <key>: |` that sits four spaces in, none when the key is absent
    """
    lines = text.replace("\r\n", "\n").split("\n")
    if f"  {key}: |" not in lines:
        return []
    block = []
    for line in lines[lines.index(f"  {key}: |") + 1:]:
        if not line.startswith("    "):
            break
        block.append(line)
    return block


def parse_copier(text: str) -> dict[str, list[dict[str, str]]]:
    """
    The copier's kept, pinned, followed and watched entries, each in its exact shape.

    Args:
        text: the copier's text

    Returns:
        dict[str, list[dict[str, str]]]: each block's entries by its key, each entry its named fields

    Raises:
        Unread: a block missing or a line out of its shape
    """
    shapes  = {"KEPT": KEPT_ENTRY, "PINNED": PINNED_ENTRY, "FOLLOWED": FOLLOWED_ENTRY, "WATCH": WATCH_ENTRY}
    entries = {}
    for key, shape in shapes.items():
        lines   = env_block(text, key)
        matched = [shape.match(line) for line in lines]
        if not lines or not all(matched):
            raise Unread(f"the copier's {key} block is missing or holds a line out of its shape")
        entries[key] = [entry.groupdict() for entry in matched if entry]
    return entries

# ======================================================================================================================
# Versions
# ======================================================================================================================

def version(text: str) -> tuple[int, int, int] | None:
    """
    The version at the start of a tag or an image's version text.

    Args:
        text: `v1.31.2`, `16.15-alpine` or `16.15-1.pgdg13+2`

    Returns:
        tuple[int, int, int] | None: its major, minor and patch, a missing patch 0, None when it starts with none
    """
    match = VERSION.match(text or "")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)) if match else None


def at_level(found: tuple[int, int, int], kept: tuple[int, int, int], level: str) -> bool:
    """
    Whether a version is newer than the kept one at the line's level.

    Args:
        found: the publisher's version
        kept: the kept entry's version
        level: `patch`, or `minor`, which compares the major and minor alone

    Returns:
        bool: True when it is a finding
    """
    return found > kept if level == "patch" else found[:2] > kept[:2]


def tag_shape(tag: str) -> re.Pattern[str]:
    """
    The shape of a tag, each run of digits any number.

    Args:
        tag: such as `v1.31.2` or `24-alpine`

    Returns:
        re.Pattern[str]: a pattern that matches `v1.32.0` or `26-alpine`, and nothing with another suffix
    """
    return re.compile("^" + re.sub(r"\d+", r"\\d+", re.escape(tag)) + "$")


def numbers(tag: str) -> tuple[int, ...]:
    """
    A tag's runs of digits, by which tags of one shape are ordered.

    Args:
        tag: the tag

    Returns:
        tuple[int, ...]: its numbers in order
    """
    return tuple(int(run) for run in re.findall(r"\d+", tag))


def config_version(client: RegistryClient, publisher: str, name: str, digest: str) -> str | None:
    """
    The version the image's config names, its OCI version label, then `<NAME>_VERSION` in its env, read by the
    digest's linux/amd64 manifest.

    Args:
        client: the registry client
        publisher: the line's publisher
        name: the image's package name, which names its env variable
        digest: the index digest

    Returns:
        str | None: the version text in VERSION_TEXT's shape, None when the config names none in that shape, so a
        publisher's text reaches the issue only as a version

    Raises:
        Unread: an index, a manifest or a config that could not be read, or one of an unexpected shape
    """
    index = client.json(publisher, f"manifests/{digest}", INDEX_TYPES)
    child = None
    for entry in _mapping(index).get("manifests") or []:
        platform = _mapping(_mapping(entry).get("platform"))
        if platform.get("os") == "linux" and platform.get("architecture") == "amd64":
            child = str(_mapping(entry).get("digest") or "")
            break
    if not child or not DIGEST.match(child):
        raise Unread(f"{publisher}@{digest} lists no linux/amd64 image")
    manifest = _mapping(client.json(publisher, f"manifests/{child}", IMAGE_TYPES))
    blob     = str(_mapping(manifest.get("config")).get("digest") or "")
    if not DIGEST.match(blob):
        raise Unread(f"{publisher}@{child} names no config")
    config = _mapping(_mapping(client.json(publisher, f"blobs/{blob}")).get("config"))
    label  = _mapping(config.get("Labels")).get("org.opencontainers.image.version")
    wanted = VERSION_ENV.get(name, f"{name.upper().replace('-', '_')}_VERSION") + "="
    env    = config.get("Env") if isinstance(config.get("Env"), list) else []
    found  = [str(label or ""), *(str(item)[len(wanted):] for item in env if str(item).startswith(wanted))]
    return next((text for text in found if VERSION_TEXT.match(text)), None)


def _mapping(value: Any) -> dict[str, Any]:
    """
    A value from a registry's JSON as a mapping, or an empty one when it is anything else.

    Args:
        value: the value

    Returns:
        dict[str, Any]: the value when it is a mapping, else an empty one
    """
    return value if isinstance(value, dict) else {}


def tag_version(client: RegistryClient, publisher: str, kept_tag: str, digest: str) -> str | None:
    """
    For an image whose config names no version, the publisher's release tag of the kept tag's shape whose index
    digest is the one the line's tag names, the newest first, at most CANDIDATES asked. A higher tag on another digest
    is passed over, so a misleading tag never counts. A higher tag that cannot be read is no pass, since it may be the
    newer version, so the line is then unread rather than matched to a lower tag (Codex's review of 2026-10-19).

    Args:
        client: the registry client
        publisher: the line's publisher
        kept_tag: the kept entry's tag, whose shape release tags take
        digest: the index digest the line's tag names

    Returns:
        str | None: the matching tag, None when none of the candidates matches

    Raises:
        Unread: the tag list could not be read whole, or a tag above the match could not be read
    """
    shape  = tag_shape(kept_tag)
    ranked = sorted((tag for tag in client.tags(publisher) if shape.match(tag)), key = numbers, reverse = True)
    for tag in ranked[:CANDIDATES]:
        if client.head_digest(publisher, tag) == digest:
            return tag
    return None

# ======================================================================================================================
# The four reads
# ======================================================================================================================

def judge_watched(client: RegistryClient, line: dict[str, str], kept: str) -> dict[str, Any]:
    """
    One watched line against its kept entry.

    Args:
        client: the registry client
        line: the watched line's fields
        kept: the kept or pinned entry's digest

    Returns:
        dict[str, Any]: the line, the publisher's digest, and its state, `current`, `newer` (a finding), `rebuild` (a
        note) or `unread`, with the version found and where it was read
    """
    out = {**line, "kept_digest": kept, "digest": None, "found": None, "source": None, "state": "unread", "detail": ""}
    try:
        digest = client.head_digest(line["publisher"], line["upstream"])
        out["digest"] = digest
        if digest == kept:
            out["state"] = "current"
            return out
        found, source = config_version(client, line["publisher"], line["name"], digest), "config"
        if not version(found or ""):
            found, source = tag_version(client, line["publisher"], line["tag"], digest), "tag"
        kept_version = version(line["tag"])
        if not version(found or "") or not kept_version:
            out["detail"] = "no version in its config and no release tag on its digest"
            return out
        out["found"], out["source"] = found, source
        out["state"] = "newer" if at_level(version(found), kept_version, line["level"]) else "rebuild"
    except Unread as exc:
        out["detail"] = str(exc)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        # an answer of a shape no rule expected leaves this one line unread, never the whole watch
        out["detail"] = f"an answer of an unexpected shape, {type(exc).__name__}"
    return out


def judge_followed(client: RegistryClient, entry: dict[str, str]) -> dict[str, Any]:
    """
    A followed tag against Docker Hub's tag list, the newer tags of its shape named.

    Args:
        client: the registry client
        entry: the followed entry's fields

    Returns:
        dict[str, Any]: the tag, the newer ones in order, and its state, `current`, `newer` (a note) or `unread`
    """
    out = {"name": entry["name"], "tag": entry["tag"], "newer": [], "state": "unread", "detail": ""}
    try:
        shape = tag_shape(entry["tag"])
        tags  = client.tags(f"docker.io/library/{entry['name']}")
        newer = {tag for tag in tags if shape.match(tag) and numbers(tag) > numbers(entry["tag"])}
        out["newer"] = sorted(newer, key = numbers)
        out["state"] = "newer" if newer else "current"
    except Unread as exc:
        out["detail"] = str(exc)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        out["detail"] = f"an answer of an unexpected shape, {type(exc).__name__}"
    return out


def judge_trivy(get: Callable[..., Any]) -> dict[str, Any]:
    """
    The Trivy release the terraform scan pins beside Trivy's latest release.

    Args:
        get: the watch's transport's get

    Returns:
        dict[str, Any]: the pinned and latest versions and the state, `current`, `newer` or `unread`
    """
    out  = {"pinned": None, "latest": None, "state": "unread", "detail": ""}
    scan = get(f"/repos/{TERRAFORM_REPO}/contents/{SECURITY_PATH}", raw = True)
    if not scan.ok or not isinstance(scan.data, str):
        out["detail"] = f"the scan's workflow could not be read, {scan.reason()}"
        return out
    lines = scan.data.replace("\r\n", "\n").split("\n")
    start = next((index for index, line in enumerate(lines) if "uses: aquasecurity/trivy-action@" in line), None)
    step  = []
    for line in lines[start + 1:] if start is not None else []:
        if line.strip().startswith("- "):
            break
        step.append(line)
    pinned = next((match.group("version") for match in map(TRIVY_PIN.match, step) if match), None)
    latest = get(f"/repos/{TRIVY_REPO}/releases/latest")
    tag    = latest.data.get("tag_name") if latest.ok and isinstance(latest.data, dict) else None
    out["pinned"], out["latest"] = pinned, tag
    if not version(pinned or ""):
        out["detail"] = "the scan's Trivy step names no version"
    elif not version(tag or ""):
        out["detail"] = f"Trivy's latest release could not be read, {latest.reason()}"
    else:
        out["state"] = "newer" if version(tag) > version(pinned) else "current"
    return out


def judge_schedule(get: Callable[..., Any], now: datetime) -> dict[str, Any]:
    """
    The copier's newest scheduled run, red, older than RUN_DAYS days, or green.

    Args:
        get: the watch's transport's get
        now: the snapshot's time

    Returns:
        dict[str, Any]: the run's state, `green`, `running`, `red`, `old` or `unread`, its conclusion, time and link
    """
    out    = {"state": "unread", "conclusion": None, "at": None, "url": None, "detail": ""}
    runs   = get(f"/repos/{CICD_REPO}/actions/workflows/{COPIER_FILE}/runs", {"event": "schedule", "per_page": 1})
    listed = (runs.data.get("workflow_runs") or [None]) if runs.ok and isinstance(runs.data, dict) else [None]
    newest = listed[0]
    if not isinstance(newest, dict):
        out["detail"] = f"no scheduled run of the copier was found, {runs.reason() if not runs.ok else 'none listed'}"
        return out
    out["conclusion"], out["at"] = newest.get("conclusion"), newest.get("created_at")
    url = str(newest.get("html_url") or "")
    out["url"] = url if url.startswith("https://github.com/") else None
    try:
        began = datetime.strptime(str(out["at"]), STAMP).replace(tzinfo = timezone.utc)
    except ValueError:
        out["detail"] = "its run's date does not parse"
        return out
    if newest.get("status") == "completed" and out["conclusion"] != "success":
        out["state"] = "red"
    elif (now - began).total_seconds() > RUN_DAYS * 86400:
        out["state"] = "old"
    else:
        out["state"] = "green" if newest.get("status") == "completed" else "running"
    return out


def collect_images(get: Callable[..., Any], client: RegistryClient, now: datetime) -> dict[str, Any]:
    """
    The images section of the snapshot.

    Args:
        get: the watch's transport's get, for GitHub alone
        client: the anonymous registry client
        now: the snapshot's time

    Returns:
        dict[str, Any]: the watched lines, the followed tags, Trivy and the copier's schedule, or the copier unread
    """
    out: dict[str, Any] = {"copier": None, "watched": [], "followed": [], "trivy": judge_trivy(get)}
    out["schedule"] = judge_schedule(get, now)
    copier = get(f"/repos/{CICD_REPO}/contents/{COPIER_PATH}", {"ref": "main"}, raw = True)
    if not copier.ok or not isinstance(copier.data, str):
        out["copier"] = f"the copier's text could not be read, {copier.reason()}"
        return out
    try:
        entries = parse_copier(copier.data)
    except Unread as exc:
        out["copier"] = str(exc)
        return out
    kept = {("postgres", entry["tag"]): entry["digest"] for entry in entries["KEPT"]}
    kept.update({(entry["name"], entry["tag"]): entry["digest"] for entry in entries["PINNED"]})
    for line in entries["WATCH"]:
        if (line["name"], line["tag"]) not in kept:
            out["watched"].append({**line, "state": "unread", "detail": "names no kept or pinned image"})
            continue
        out["watched"].append(judge_watched(client, line, kept[(line["name"], line["tag"])]))
    out["followed"] = [judge_followed(client, entry) for entry in entries["FOLLOWED"]]
    return out


def counts(images: dict[str, Any] | None) -> tuple[int, int]:
    """
    How many of the section's parts are behind, and how many are unread, each a finding. A followed tag with a newer
    one of its shape is a runtime the owner chooses to move to, a note alone, so it is not counted behind.

    Args:
        images: the section, None in a snapshot without one

    Returns:
        tuple[int, int]: the parts behind and the parts unread
    """
    if not images:
        return 0, 0
    behind = sum(1 for part in [*images.get("watched", []), images.get("trivy") or {}] if part.get("state") == "newer")
    behind += 1 if (images.get("schedule") or {}).get("state") in ("red", "old") else 0
    parts  = [*images.get("watched", []), *images.get("followed", []), images.get("trivy") or {}]
    unread = sum(1 for part in parts if part.get("state") == "unread")
    unread += 1 if (images.get("schedule") or {}).get("state") == "unread" else 0
    return behind, unread + (1 if images.get("copier") else 0)
