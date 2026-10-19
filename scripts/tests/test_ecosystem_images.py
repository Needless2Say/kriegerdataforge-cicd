"""
Tests for the ecosystem watch's images section (D-080, item 10), `scripts/ecosystem_images.py`.

GitHub answers from a table through a fake of the watch's transport, and every registry from `registry_fakes.py`, so no
test touches a network. The copier's own text is the one parsed, so a change to its shapes is met here. Each case is a
row the plan and Codex's decision read named, a new version, a rebuild, Checkov's patch below its minor level, a
current line, an image whose config names no version read from its publisher's matching tag, a misleading higher tag,
numeric order, a tag list cut short, the time budget, a refused HEAD, a followed tag's newer runtime, the pinned Trivy
behind or current, the copier's scheduled run green, red, old or missing, and copier text out of its shapes.
"""

from __future__ import annotations

# standard imports
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# third party imports
import ecosystem_images as ei
import ecosystem_watch as ew
import pytest
from tests import copier_rule
from tests.registry_fakes import FakeRegistry, body, clean_table, client, digest, github_clean, head, image, url

COPIER_TEXT = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "mirror-ci-images.yml").read_text(
    encoding = "utf-8",
)
NOW         = datetime(2026, 10, 26, 10, 0, tzinfo = timezone.utc)
CADDY       = "docker.io/library/caddy"
MAILPIT     = "ghcr.io/axllent/mailpit"
CHECKOV     = "ghcr.io/bridgecrewio/checkov"
POSTGRES    = "docker.io/library/postgres"


def line(name: str, tag: str, publisher: str, upstream: str, level: str = "patch") -> dict[str, str]:
    return {"name": name, "tag": tag, "publisher": publisher, "upstream": upstream, "level": level}


class FakeGet:
    """
    The watch's transport's get, from a table of paths and their data, a missing path a 404.
    """
    def __init__(self, table: dict[str, Any]) -> None:
        self.table = table
        self.calls: list[str] = []


    def __call__(self, path: str, params: dict[str, Any] | None = None, raw: bool = False) -> ew.Response:
        self.calls.append(path)
        if path not in self.table:
            return ew.Response(404, {"message": "Not Found"})
        return ew.Response(200, self.table[path])

# ======================================================================================================================
# The copier's text
# ======================================================================================================================

def test_the_copiers_own_text_parses_in_its_shapes() -> None:
    entries = ei.parse_copier(COPIER_TEXT)

    assert [len(entries[key]) for key in ("KEPT", "PINNED", "FOLLOWED", "WATCH")] == [1, 4, 2, 5]
    assert {entry["level"] for entry in entries["WATCH"]} == {"patch", "minor"}


def test_the_shapes_are_the_image_tests_own() -> None:
    """
    The watch reads the copier by the shapes cicd's image test holds, so the two never drift apart.
    """
    pairs = [
        (ei.KEPT_ENTRY, copier_rule.KEPT_ENTRY),
        (ei.PINNED_ENTRY, copier_rule.PINNED_ENTRY),
        (ei.FOLLOWED_ENTRY, copier_rule.FOLLOWED_ENTRY),
        (ei.WATCH_ENTRY, copier_rule.WATCH_ENTRY),
    ]

    assert all(ours.pattern == theirs.pattern for ours, theirs in pairs)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("    caddy 2.10.2-alpine docker.io", "    caddy 2.10.2-alpine  docker.io"),
        ("  WATCH: |\n", "  WATCHED: |\n"),
        ("    node 24-alpine\n", "    node\n"),
    ],
)
def test_copier_text_out_of_its_shapes_is_unread(old: str, new: str) -> None:
    assert old in COPIER_TEXT

    with pytest.raises(ei.Unread):
        ei.parse_copier(COPIER_TEXT.replace(old, new, 1))

# ======================================================================================================================
# A watched line
# ======================================================================================================================

def test_a_current_line_reads_its_publisher_once_by_head() -> None:
    registry = FakeRegistry({("HEAD", url(CADDY, "manifests/2-alpine")): head(digest("a"))})
    judged   = ei.judge_watched(client(registry), line("caddy", "2.10.2-alpine", CADDY, "2-alpine"), digest("a"))

    assert judged["state"] == "current"
    assert [(method, address) for method, address, _ in registry.calls if "/token?" not in address] == [
        ("HEAD", url(CADDY, "manifests/2-alpine")),
    ]


@pytest.mark.parametrize(
    ("config", "level", "state"),
    [
        # a newer patch by the OCI label, a rebuild at the same version, an older one upstream a rebuild too
        ({"Labels": {"org.opencontainers.image.version": "v2.10.3"}}, "patch", "newer"),
        ({"Labels": {"org.opencontainers.image.version": "v2.10.2"}}, "patch", "rebuild"),
        ({"Labels": {"org.opencontainers.image.version": "v2.9.9"}}, "patch", "rebuild"),
        # Checkov's level, a patch below it a rebuild, a new minor a finding
        ({"Labels": {"org.opencontainers.image.version": "2.10.9"}}, "minor", "rebuild"),
        ({"Labels": {"org.opencontainers.image.version": "2.11.0"}}, "minor", "newer"),
        # the env when the label is absent
        ({"Env": ["PATH=/bin", "CADDY_VERSION=v2.11.0"]}, "patch", "newer"),
    ],
)
def test_a_moved_digest_is_judged_by_its_configs_version_at_the_lines_level(config, level, state) -> None:
    table = {("HEAD", url(CADDY, "manifests/2-alpine")): head(digest("b"))}
    image(table, CADDY, digest("b"), config)
    judged = ei.judge_watched(
        client(FakeRegistry(table)),
        line("caddy", "2.10.2-alpine", CADDY, "2-alpine", level),
        digest("a"),
    )

    assert (judged["state"], judged["source"]) == (state, "config")


@pytest.mark.parametrize(("shown", "state"), [("16.16", "newer"), ("16.15-1.pgdg13+2", "rebuild")])
def test_postgres_reads_its_pg_version(shown: str, state: str) -> None:
    table = {("HEAD", url(POSTGRES, "manifests/16")): head(digest("b"))}
    image(table, POSTGRES, digest("b"), {"Env": ["PG_MAJOR=16", f"PG_VERSION={shown}"]})
    judged = ei.judge_watched(client(FakeRegistry(table)), line("postgres", "16.15", POSTGRES, "16"), digest("a"))

    assert judged["state"] == state


def mailpit(tags: list[str], heads: dict[str, str]) -> dict:
    """
    Mailpit's latest moved to digest b, its config naming no version, its tag list and each tag's digest.
    """
    table = {("HEAD", url(MAILPIT, "manifests/latest")): head(digest("b"))}
    image(table, MAILPIT, digest("b"), {"Labels": {"org.opencontainers.image.title": "Mailpit"}, "Env": ["PATH=/"]})
    table[("GET", url(MAILPIT, f"tags/list?n={ei.TAG_PAGE}"))] = body({"tags": tags})
    for tag, found in heads.items():
        table[("HEAD", url(MAILPIT, f"manifests/{tag}"))] = head(found)
    return table


def test_an_image_whose_config_names_no_version_takes_its_publishers_matching_tag() -> None:
    """
    v1.40.0 is higher but on another digest, so it is passed over, and v1.32.0 is the one the line's tag names.
    """
    table  = mailpit(
        ["latest", "v1.31.2", "v1.32.0", "v1.40.0", "edge"],
        {"v1.40.0": digest("c"), "v1.32.0": digest("b")},
    )
    judged = ei.judge_watched(client(FakeRegistry(table)), line("mailpit", "v1.31.2", MAILPIT, "latest"), digest("a"))

    assert (judged["state"], judged["found"], judged["source"]) == ("newer", "v1.32.0", "tag")


def test_tags_are_ordered_by_number_not_by_text() -> None:
    """
    v1.10.0 is newer than v1.9.0, which a text sort would put first.
    """
    registry = FakeRegistry(mailpit(["v1.9.0", "v1.10.0"], {"v1.10.0": digest("b"), "v1.9.0": digest("b")}))
    judged   = ei.judge_watched(client(registry), line("mailpit", "v1.31.2", MAILPIT, "latest"), digest("a"))

    assert judged["found"] == "v1.10.0"


def test_no_matching_tag_is_unread() -> None:
    table  = mailpit(["v1.32.0"], {"v1.32.0": digest("c")})
    judged = ei.judge_watched(client(FakeRegistry(table)), line("mailpit", "v1.31.2", MAILPIT, "latest"), digest("a"))

    assert judged["state"] == "unread" and "no release tag" in judged["detail"]


def test_a_tag_list_cut_short_is_unread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ei, "TAG_PAGE", 2)
    monkeypatch.setattr(ei, "TAG_PAGES", 2)
    table = mailpit([], {})
    table[("GET", url(MAILPIT, "tags/list?n=2"))] = body({"tags": ["v1.1.0", "v1.2.0"]})
    table[("GET", url(MAILPIT, "tags/list?n=2&last=v1.2.0"))] = body({"tags": ["v1.3.0", "v1.4.0"]})
    judged = ei.judge_watched(client(FakeRegistry(table)), line("mailpit", "v1.31.2", MAILPIT, "latest"), digest("a"))

    assert judged["state"] == "unread" and "cut short" in judged["detail"]


def test_the_time_budget_ends_every_read_unread() -> None:
    ticks    = iter([0.0, 0.0, 500.0, 500.0, 500.0])
    registry = FakeRegistry({("HEAD", url(CADDY, "manifests/2-alpine")): head(digest("a"))})
    spent    = ei.RegistryClient(fetch = registry, budget = 300, clock = lambda: next(ticks), pause = lambda s: None)
    judged   = ei.judge_watched(spent, line("caddy", "2.10.2-alpine", CADDY, "2-alpine"), digest("a"))

    assert judged["state"] == "unread" and "time budget" in judged["detail"]


@pytest.mark.parametrize(
    "reply",
    [
        ei.Reply(429),
        ei.Reply(200, {"content-type": ei.IMAGE_TYPES[0], "docker-content-digest": digest("b")}),
        ei.Reply(200, {"content-type": ei.INDEX_TYPES[0], "docker-content-digest": "sha256:short"}),
        ei.Reply(0),
    ],
)
def test_a_refused_or_misshapen_head_is_unread_and_retried_within_bounds(reply: ei.Reply) -> None:
    registry = FakeRegistry({("HEAD", url(CADDY, "manifests/2-alpine")): reply})
    judged   = ei.judge_watched(client(registry), line("caddy", "2.10.2-alpine", CADDY, "2-alpine"), digest("a"))
    asked    = [call for call in registry.calls if call[0] == "HEAD"]

    assert judged["state"] == "unread"
    assert len(asked) == (ei.RETRIES + 1 if reply.status in (0, 429) else 1)


@pytest.mark.parametrize(
    ("token", "read"),
    [
        # Docker Hub's JWT, and GitHub's registry's base64, which a dry run of 2026-10-19 found refused
        ("eyJhbGciOi.eyJzdWIiOi.c2lnbmF0dXJl", True),
        ("djE6YXhsbGVudC9tYWlscGl0OjE3NjA4+/Zm9v==", True),
        ("two words", False),
        ("", False),
    ],
)
def test_an_anonymous_token_is_taken_in_a_registrys_own_shape(token: str, read: bool) -> None:
    registry = FakeRegistry({("HEAD", url(MAILPIT, "manifests/latest")): head(digest("a"))})
    answered = ei.Reply(200, {}, ('{"token":"' + token + '"}').encode())
    spent    = ei.RegistryClient(
        fetch = lambda address, headers, method: answered if "/token?" in address else registry(
            address,
            headers,
            method,
        ),
        clock = lambda: 0.0,
        pause = lambda seconds: None,
    )
    judged   = ei.judge_watched(spent, line("mailpit", "v1.31.2", MAILPIT, "latest"), digest("a"))

    assert (judged["state"] == "current") is read


def test_no_registry_read_carries_githubs_token() -> None:
    """
    Its registry reads go through a client of their own with anonymous tokens, never the App token.
    """
    registry = FakeRegistry({("HEAD", url(CADDY, "manifests/2-alpine")): head(digest("a"))})
    ei.judge_watched(client(registry), line("caddy", "2.10.2-alpine", CADDY, "2-alpine"), digest("a"))

    assert [headers for _, address, headers in registry.calls if "/token?" in address] == [{}]
    assert all(headers.get("Authorization") == "Bearer anonymous.pull-1"
               for _, address, headers in registry.calls if "/token?" not in address)

# ======================================================================================================================
# A followed tag, Trivy and the schedule
# ======================================================================================================================

@pytest.mark.parametrize(
    ("tags", "state", "newer"),
    [
        (["24-alpine", "25-alpine", "26-alpine", "26-alpine3.21", "24.10-alpine", "latest"], "newer",
         ["25-alpine", "26-alpine"]),
        (["22-alpine", "24-alpine", "24-alpine3.20"], "current", []),
    ],
)
def test_a_followed_tag_names_the_newer_tags_of_its_shape(tags: list[str], state: str, newer: list[str]) -> None:
    table  = {("GET", url("docker.io/library/node", f"tags/list?n={ei.TAG_PAGE}")): body({"tags": tags})}
    judged = ei.judge_followed(client(FakeRegistry(table)), {"name": "node", "tag": "24-alpine", "hold": None})

    assert (judged["state"], judged["newer"]) == (state, newer)


def test_a_followed_tag_whose_list_cannot_be_read_is_unread() -> None:
    judged = ei.judge_followed(client(FakeRegistry()), {"name": "python", "tag": "3.14-slim", "hold": None})

    assert judged["state"] == "unread"


def trivy(pinned: str | None, latest: str | None) -> dict[str, Any]:
    step = "        uses: aquasecurity/trivy-action@ed142fd0 # v0.36.0\n        with:\n"
    step += f"          version: '{pinned}'\n" if pinned else ""
    step += "      - name: Run Checkov scan\n        with:\n          version: 'v9.9.9'\n"
    table = {f"/repos/{ei.TERRAFORM_REPO}/contents/{ei.SECURITY_PATH}": step}
    if latest:
        table[f"/repos/{ei.TRIVY_REPO}/releases/latest"] = {"tag_name": latest}
    return table


@pytest.mark.parametrize(
    ("pinned", "latest", "state"),
    [
        ("v0.65.0", "v0.66.0", "newer"),
        ("v0.66.0", "v0.66.0", "current"),
        # no version in Trivy's own step, a later step's version never read for it
        (None, "v0.66.0", "unread"),
        ("v0.66.0", None, "unread"),
    ],
)
def test_the_scans_pinned_trivy_against_its_latest_release(pinned, latest, state) -> None:
    assert ei.judge_trivy(FakeGet(trivy(pinned, latest)))["state"] == state


def schedule(status: str, conclusion: str | None, at: str) -> FakeGet:
    return FakeGet({f"/repos/{ei.CICD_REPO}/actions/workflows/{ei.COPIER_FILE}/runs": {"workflow_runs": [{
        "status": status, "conclusion": conclusion, "created_at": at, "html_url": "https://github.com/x/runs/1",
    }]}})


@pytest.mark.parametrize(
    ("status", "conclusion", "at", "state"),
    [
        ("completed", "success", "2026-10-26T06:23:00Z", "green"),
        ("completed", "failure", "2026-10-26T06:23:00Z", "red"),
        ("completed", "success", "2026-10-22T06:23:00Z", "old"),
        ("in_progress", None, "2026-10-26T06:23:00Z", "running"),
        ("completed", "success", "last Monday", "unread"),
    ],
)
def test_the_copiers_scheduled_run(status, conclusion, at, state) -> None:
    assert ei.judge_schedule(schedule(status, conclusion, at), NOW)["state"] == state


def test_no_scheduled_run_is_unread() -> None:
    assert ei.judge_schedule(FakeGet({}), NOW)["state"] == "unread"

# ======================================================================================================================
# The section
# ======================================================================================================================

def test_the_copier_unread_reads_no_registry_and_counts_unread() -> None:
    registry = FakeRegistry()
    images   = ei.collect_images(FakeGet(trivy("v0.66.0", "v0.66.0")), client(registry), NOW)

    assert images["copier"] and registry.calls == []
    assert ei.counts(images) == (0, 2)


def test_a_newer_runtime_is_not_counted_behind() -> None:
    """
    The owner's answer of 2026-10-19, a followed tag's newer runtime a note alone.
    """
    images = {
        "watched": [{"state": "current"}],
        "followed": [{"state": "newer", "newer": ["26-alpine"]}],
        "trivy": {"state": "current"},
        "schedule": {"state": "green"},
        "copier": None,
    }

    assert ei.counts(images) == (0, 0)

# ======================================================================================================================
# The issue
# ======================================================================================================================

def issue(table: dict, github: dict[str, Any] | None = None) -> tuple[str, str, str]:
    """
    The watch's issue rendered from a snapshot that holds nothing but this images section, collected from the copier's
    own text on the fakes, its other parts clean.
    """
    answers = {**github_clean(COPIER_TEXT, NOW), **(github or {})}
    images  = ei.collect_images(FakeGet(answers), client(FakeRegistry(table)), NOW)
    behind, unread = ei.counts(images)
    summary  = {
        "alerts": {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0},
        "alerts_total": 0,
        "pins_behind": 0,
        "pins_unjudged": 0,
        "drift": 0,
        "notices": 0,
        "notices_old": 0,
        "errors": unread,
        "images_behind": behind,
    }
    snapshot = {
        "schema": ew.SCHEMA,
        "generated_at": NOW.strftime(ei.STAMP),
        "owner": ew.OWNER,
        "kit_version": "v9.0.0",
        "releases": {},
        "canonical_scripts_unreadable": [],
        "repos": [],
        "images": images,
        "summary": summary,
    }
    return ew.render(snapshot, "previous body")


def test_a_clean_section_clears_the_issue() -> None:
    body, news, state = issue(clean_table(COPIER_TEXT))

    assert state == "clear" and news == ""
    assert "Every image the copier keeps is current upstream" in body and "**0 images behind**" in body


def test_a_newer_version_is_a_finding_with_its_news() -> None:
    table = clean_table(COPIER_TEXT)
    table[("HEAD", url(CADDY, "manifests/2-alpine"))] = head(digest("b"))
    image(table, CADDY, digest("b"), {"Labels": {"org.opencontainers.image.version": "v2.11.0"}})
    body, news, state = issue(table)

    assert state == "open" and "**1 images behind**" in body
    assert "| caddy | `2.10.2-alpine` | `v2.11.0` | config of docker.io/library/caddy:2-alpine | patch |" in body
    assert "caddy kept at `2.10.2-alpine`, and its publisher has `v2.11.0`" in news


def test_a_rebuild_and_a_newer_runtime_are_notes_that_keep_nothing_open() -> None:
    """
    A rebuild at the same version, and node 26 beside the followed node 24, the owner's answers of 2026-10-18 and
    2026-10-19.
    """
    table = clean_table(COPIER_TEXT)
    table[("HEAD", url(CHECKOV, "manifests/latest"))] = head(digest("b"))
    image(table, CHECKOV, digest("b"), {"Labels": {"org.opencontainers.image.version": "3.3.9"}})
    table[("GET", url("docker.io/library/node", f"tags/list?n={ei.TAG_PAGE}"))] = body(
        {"tags": ["24-alpine", "25-alpine", "26-alpine"]},
    )
    body_text, _, state = issue(table)

    assert state == "clear"
    assert "nothing to do: checkov 3.3.6 (3.3.9)." in body_text
    assert "`node:24-alpine`, Docker Hub has `25-alpine`, `26-alpine`" in body_text


@pytest.mark.parametrize(
    ("github", "expected"),
    [
        # the copier's text unreadable, every image unread
        ({f"/repos/{ei.CICD_REPO}/contents/{ei.COPIER_PATH}": "  KEPT: |\n    nothing\n"}, "unread, the copier's"),
        # Trivy behind its latest release
        ({f"/repos/{ei.TRIVY_REPO}/releases/latest": {"tag_name": "v0.71.0"}}, "and `v0.71.0` is out"),
        # the copier's scheduled run red
        ({f"/repos/{ei.CICD_REPO}/actions/workflows/{ei.COPIER_FILE}/runs": {"workflow_runs": [{
            "status": "completed", "conclusion": "failure", "created_at": "2026-10-26T06:23:00Z",
            "html_url": "https://github.com/x/runs/2",
        }]}}, "ended red, [run](https://github.com/x/runs/2)"),
    ],
)
def test_an_unread_part_a_newer_trivy_or_a_red_schedule_keeps_the_issue_open(github, expected) -> None:
    body_text, _, state = issue(clean_table(COPIER_TEXT), github)

    assert state == "open" and expected in body_text


@pytest.mark.parametrize(("text", "found"), [("v1.31.2", (1, 31, 2)), ("16.15-alpine", (16, 15, 0)), ("x1", None)])
def test_a_version_is_read_from_a_tags_start(text: str, found: tuple[int, int, int] | None) -> None:
    assert ei.version(text) == found


def test_a_tags_shape_holds_its_runs_of_digits_alone() -> None:
    shape = ei.tag_shape("3.14-slim")

    assert [tag for tag in ("3.15-slim", "3.15-slim-bookworm", "3.15", "4.0-slim") if shape.match(tag)] == [
        "3.15-slim",
        "4.0-slim",
    ]
    assert isinstance(shape, re.Pattern)
