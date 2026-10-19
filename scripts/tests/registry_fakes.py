"""
A registry from a table, for the tests of the ecosystem watch's images section (D-080), so no test touches a network.

Each request is answered by its method and URL, an anonymous token for any repository, and a missing one a 404. Every
request is logged with its headers, so a test can hold that no token of GitHub's ever reaches a registry.
"""

from __future__ import annotations

# standard imports
import json
from datetime import datetime, timedelta, timezone
from typing import Any

# third party imports
import ecosystem_images as ei

HUB  = "https://registry-1.docker.io/v2/"
GHCR = "https://ghcr.io/v2/"


class FakeRegistry:
    """
    A registry's answers by method and URL, and a log of every request.
    """
    def __init__(self, table: dict[tuple[str, str], ei.Reply] | None = None) -> None:
        self.table = table or {}
        self.calls: list[tuple[str, str, dict[str, str]]] = []


    def __call__(self, url: str, headers: dict[str, str], method: str) -> ei.Reply:
        self.calls.append((method, url, dict(headers)))
        if "/token?" in url:
            return ei.Reply(200, {}, b'{"token":"anonymous.pull-1"}')
        return self.table.get((method, url), ei.Reply(404))


def head(digest: str, kind: str = ei.INDEX_TYPES[0]) -> ei.Reply:
    """
    A HEAD's answer naming a digest.
    """
    return ei.Reply(200, {"content-type": kind, "docker-content-digest": digest})


def body(document: Any) -> ei.Reply:
    """
    A GET's answer with a JSON body.
    """
    return ei.Reply(200, {}, json.dumps(document).encode())


def url(reference: str, path: str) -> str:
    """
    The URL the client asks for a publisher's reference and a path.
    """
    host, _, repo = reference.partition("/")
    return (HUB if host == "docker.io" else GHCR) + f"{repo}/{path}"


def digest(char: str) -> str:
    """
    A digest of one repeated hex character.
    """
    return "sha256:" + char * 64


def image(table: dict[tuple[str, str], ei.Reply], reference: str, index: str, config: dict[str, Any]) -> None:
    """
    An index on a publisher with one linux/amd64 image whose config is the one given.
    """
    child, blob = digest("8"), digest("9")
    table[("GET", url(reference, f"manifests/{index}"))] = body({"manifests": [
        {"digest": digest("7"), "platform": {"os": "linux", "architecture": "arm64"}},
        {"digest": child, "platform": {"os": "linux", "architecture": "amd64"}},
    ]})
    table[("GET", url(reference, f"manifests/{child}"))] = body({"config": {"digest": blob}})
    table[("GET", url(reference, f"blobs/{blob}"))] = body({"config": config})


def client(registry: FakeRegistry, budget: float = 300) -> ei.RegistryClient:
    """
    A client on the fake registry that never waits, its clock still.
    """
    return ei.RegistryClient(fetch = registry, budget = budget, clock = lambda: 0.0, pause = lambda seconds: None)


def clean_table(copier_text: str) -> dict[tuple[str, str], ei.Reply]:
    """
    Every watched line current, its publisher naming the kept digest, and each followed tag the newest of its shape.
    """
    entries = ei.parse_copier(copier_text)
    kept    = {("postgres", entry["tag"]): entry["digest"] for entry in entries["KEPT"]}
    kept.update({(entry["name"], entry["tag"]): entry["digest"] for entry in entries["PINNED"]})
    table = {}
    for line in entries["WATCH"]:
        table[
            ("HEAD", url(line["publisher"], f"manifests/{line['upstream']}"))
        ] = head(kept[(line["name"], line["tag"])])
    for entry in entries["FOLLOWED"]:
        table[("GET", url(f"docker.io/library/{entry['name']}", f"tags/list?n={ei.TAG_PAGE}"))] = body(
            {"tags": [entry["tag"], "latest"]},
        )
    return table


def github_clean(copier_text: str, now: datetime | None = None) -> dict[str, Any]:
    """
    The GitHub answers of a clean images section, as `path: data` for a fake transport to wrap, the copier's text,
    a scan pinning the latest Trivy, and a green scheduled run an hour old.
    """
    began = (now or datetime.now(timezone.utc)) - timedelta(hours = 1)
    scan  = (
        "      - name: Run Trivy config scan\n"
        "        uses: aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25 # v0.36.0\n"
        "        with:\n"
        "          version: 'v0.70.0'\n"
        "      - name: Run Checkov scan\n"
    )
    return {
        f"/repos/{ei.CICD_REPO}/contents/{ei.COPIER_PATH}": copier_text,
        f"/repos/{ei.TERRAFORM_REPO}/contents/{ei.SECURITY_PATH}": scan,
        f"/repos/{ei.TRIVY_REPO}/releases/latest": {"tag_name": "v0.70.0"},
        f"/repos/{ei.CICD_REPO}/actions/workflows/{ei.COPIER_FILE}/runs": {"workflow_runs": [{
            "status": "completed",
            "conclusion": "success",
            "created_at": began.strftime(ei.STAMP),
            "html_url": "https://github.com/Needless2Say/kriegerdataforge-cicd/actions/runs/1",
        }]},
    }
