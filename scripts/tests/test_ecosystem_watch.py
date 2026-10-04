"""
Tests for the ecosystem watch (D-049), `scripts/ecosystem_watch.py`.

A fake transport answers every GitHub call from a table, so no test touches a network, and a small registry stands in
for the real ones. The collector was also run read only against the owner's repos on 2026-10-04 with the gh transport,
18 repos in 30 seconds, and its findings were checked by hand, the pull request of D-049 records that run.
"""

from __future__ import annotations

# standard imports
import json
from pathlib import Path
from typing import Any

# third party imports
import ecosystem_watch as ew
import pytest

OWNER      = ew.OWNER
A          = f"{OWNER}/repo-a"
B          = f"{OWNER}/repo-b"
SHA_LATEST = "a" * 40
SHA_OLDER  = "b" * 40
SHA_ENGINE = "e" * 40
SHA_CHECK  = "c" * 40

# the mutation engine, which only the repos its own entry names carry (D-040)
ENGINE_SRC  = "scripts/common/mutation_runner.py"
ENGINE_DEST = "scripts/kdf_scripts/mutation_runner.py"

# the runner's own notice of 2026-10-04, as GitHub words it
UBUNTU = "The ubuntu-latest label will migrate to Ubuntu 26."


class FakeTransport:
    """
    GitHub from a table, keyed by path, a missing path answering 404, and a log of every call.
    """
    def __init__(self, table: dict[str, ew.Response]) -> None:
        self.table = table
        self.calls: list[str] = []


    def get(self, path: str, params: dict[str, Any] | None = None, raw: bool = False) -> ew.Response:
        self.calls.append(path)
        page = (params or {}).get("page")
        if page and f"{path}#page={page}" in self.table:
            return self.table[f"{path}#page={page}"]
        if page and page > 1:
            return ok([])
        return self.table.get(path, ew.Response(404, {"message": "Not Found"}))


def ok(data: Any) -> ew.Response:
    return ew.Response(200, data)


def tags(*pairs: tuple[str, str]) -> ew.Response:
    return ok([{"name": name, "commit": {"sha": sha}} for name, sha in pairs])


def alert(number: int, severity: str, package: str = "urllib3") -> dict[str, Any]:
    return {
        "number": number,
        "html_url": f"https://github.com/x/alerts/{number}",
        "dependency": {"package": {"ecosystem": "pip", "name": package}, "manifest_path": "requirements.txt"},
        "security_advisory": {"ghsa_id": f"GHSA-{number}", "cve_id": None, "severity": severity, "summary": "s"},
        "security_vulnerability": {
            "severity": severity,
            "vulnerable_version_range": "< 2.5.0",
            "first_patched_version": {"identifier": "2.5.0"},
        },
    }


@pytest.fixture()
def registries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Two repos, A a kit and scripts target that carries the mutation engine, B a kit and scripts target that does not,
    cicd's kit at v9.0.0 and its canonical kdf-fmt pin at v1.3.0.
    """
    kit = {"repos": [{"repo": A, "branch": "main"}, {"repo": B, "branch": "main"}]}
    scr = {
        "files": [
            {"src": "scripts/common/check_version.py", "dest": "scripts/kdf_scripts/check_version.py"},
            {"src": ENGINE_SRC, "dest": ENGINE_DEST, "repos": [A]},
        ],
        "repos": [{"repo": A, "branch": "main"}, {"repo": B, "branch": "main"}],
        "requirements_patch": {"kdf_fmt_ref": "v1.3.0"},
    }
    (tmp_path / "kit.json").write_text(json.dumps(kit), encoding = "utf-8")
    (tmp_path / "scr.json").write_text(json.dumps(scr), encoding = "utf-8")
    (tmp_path / "KIT_VERSION").write_text("v9.0.0\n", encoding = "utf-8")
    monkeypatch.setattr(ew, "KIT_REGISTRY", tmp_path / "kit.json")
    monkeypatch.setattr(ew, "SCR_REGISTRY", tmp_path / "scr.json")
    monkeypatch.setattr(ew, "KIT_VERSION", tmp_path / "KIT_VERSION")


def base_table() -> dict[str, ew.Response]:
    """
    Every repo clean, the four release repos tagged, cicd's scripts readable.
    """
    table = {
        f"/repos/{OWNER}/kriegerdataforge-fmt/tags": tags(("v1.3.0", SHA_LATEST), ("v1.2.0", SHA_OLDER)),
        f"/repos/{OWNER}/kriegerdataforge-sdk/tags": tags(("v0.12.2", "d" * 40), ("v0.12.10-rc1", "f" * 40)),
        f"/repos/{OWNER}/kriegerdataforge-reports-sdk/tags": tags(("v0.2.11", "1" * 40)),
        f"/repos/{OWNER}/kriegerdataforge-report-form/tags": tags(("v0.2.10", "2" * 40), ("v0.2.9", "3" * 40)),
        f"/repos/{ew.CICD_REPO}/contents/scripts/common/check_version.py": ok({"sha": SHA_CHECK}),
        f"/repos/{ew.CICD_REPO}/contents/scripts/common/mutation_runner.py": ok({"sha": SHA_ENGINE}),
    }
    for repo in (ew.CICD_REPO, A, B):
        table[f"/repos/{repo}/dependabot/alerts"] = ok([])
        table[f"/repos/{repo}/actions/runs"] = ok({"workflow_runs": []})
    for repo in (A, B):
        table[f"/repos/{repo}/contents/docs/agent/KIT_VERSION"] = ok("v9.0.0\n")
        table[f"/repos/{repo}/contents/scripts/kdf_scripts/check_version.py"] = ok({"sha": SHA_CHECK})
    table[f"/repos/{A}/contents/scripts/kdf_scripts/mutation_runner.py"] = ok({"sha": SHA_ENGINE})
    return table

# ======================================================================================================================
# Versions and pins
# ======================================================================================================================

@pytest.mark.parametrize(
    ("text", "want"),
    [("v1.2.3", (1, 2, 3)), ("1.2.3", (1, 2, 3)), ("v1.2", None), ("v1.2.3-rc1", None), ("main", None)],
)
def test_semver_reads_plain_versions_alone(text: str, want: tuple[int, int, int] | None) -> None:
    assert ew.semver(text) == want


@pytest.mark.parametrize(
    ("spec", "version", "want"),
    [
        ("^0.2.1", (0, 2, 10), True),
        ("^0.2.3", (0, 3, 0), False),
        ("^0.2.3", (0, 2, 2), False),
        ("^1.2.0", (1, 9, 9), True),
        ("^1.2.0", (2, 0, 0), False),
        ("^0.0.3", (0, 0, 4), False),
        ("~1.2.3", (1, 2, 9), True),
        ("~1.2.3", (1, 3, 0), False),
        ("1.2.3", (1, 2, 3), True),
        ("1.2.3", (1, 2, 4), False),
        (">=1.0.0", (1, 2, 3), None),
        ("latest", (1, 2, 3), None),
    ],
)
def test_npm_allows_judges_the_three_plain_range_shapes(spec: str, version: tuple[int, int, int], want: bool) -> None:
    assert ew.npm_allows(spec, version) is want


def test_latest_release_takes_the_highest_plain_tag_and_maps_every_commit() -> None:
    transport = FakeTransport({f"/repos/{OWNER}/x/tags": tags(("v0.9.0", "9" * 40), ("v0.10.0", "0" * 40),
                                                              ("v0.11.0-rc1", "r" * 40), ("nightly", "n" * 40))})
    release   = ew.latest_release(transport, "x")
    assert (release.tag, release.sha) == ("v0.10.0", "0" * 40)
    assert release.by_sha == {"9" * 40: "v0.9.0", "0" * 40: "v0.10.0"}
    missing = ew.latest_release(FakeTransport({}), "gone")
    assert missing.tag is None and "404" in missing.error


@pytest.mark.parametrize(
    ("ref", "behind", "note"),
    [
        ("v1.3.0", False, None),
        ("v1.2.0", True, None),
        (SHA_LATEST, False, "commit of v1.3.0"),
        (SHA_OLDER, True, "commit of v1.2.0"),
        ("f" * 40, True, "a commit that is no release tag"),
        ("main", False, "not a version tag"),
    ],
)
def test_judge_reads_a_tag_or_a_full_commit(ref: str, behind: bool, note: str | None) -> None:
    release = ew.Release("v1.3.0", SHA_LATEST, {SHA_LATEST: "v1.3.0", SHA_OLDER: "v1.2.0"})
    verdict = ew.judge(ref, release)
    assert (verdict["behind"], verdict["note"]) == (behind, note)


def test_judge_never_calls_a_pin_behind_an_unknown_release() -> None:
    verdict = ew.judge("v0.1.0", ew.Release(None, None, {}, "HTTP 403"))
    assert verdict["behind"] is False
    assert "latest release unknown" in verdict["note"]


def test_find_pins_reads_every_shape_and_skips_comments_and_other_owners() -> None:
    text = "\n".join([
        "kriegerdataforge-sdk[fastapi,database] @ git+https://github.com/Needless2Say/kriegerdataforge-sdk.git@v0.12.2",
        "kdf-fmt @ git+https://github.com/Needless2Say/kriegerdataforge-fmt@v1.3.0",
        "# kdf-fmt @ git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@v1.0.0",
        "other @ git+https://github.com/someone/other.git@v9.9.9",
        "  \"kriegerdataforge-reports-sdk @ git+https://github.com/Needless2Say/kriegerdataforge-reports-sdk.git@"
        + "1" * 40 + "\",",
        "requests==2.32.0",
    ])
    pins = ew.find_pins("requirements.in", text)
    assert [(p["package"], p["repo"], p["ref"]) for p in pins] == [
        ("kriegerdataforge-sdk", "kriegerdataforge-sdk", "v0.12.2"),
        ("kdf-fmt", "kriegerdataforge-fmt", "v1.3.0"),
        ("kriegerdataforge-reports-sdk", "kriegerdataforge-reports-sdk", "1" * 40),
    ]


def test_find_pins_reads_the_style_lane_ref_and_npm_ranges() -> None:
    ci = "jobs:\n  style:\n    with:\n      kdf_fmt_ref: v1.3.0\n#      kdf_fmt_ref: v1.0.0\n"
    assert [p["ref"] for p in ew.find_pins(".github/workflows/ci.yml", ci)] == ["v1.3.0"]
    manifest = json.dumps({"dependencies": {"@needless2say/report-form": "^0.2.3", "@other/x": "^1.0.0"},
                           "devDependencies": {"next": "16.0.0"}})
    pins     = ew.find_pins("package.json", manifest)
    assert [(p["package"], p["repo"], p["ref"]) for p in pins] == [
        ("@needless2say/report-form", "kriegerdataforge-report-form", "^0.2.3"),
    ]
    assert ew.find_pins("package.json", "{not json") == []


def test_parse_included_splits_status_headers_and_body() -> None:
    text = "HTTP/2.0 200 OK\r\nContent-Type: application/json\r\n\r\n[1, 2]"
    resp = ew.parse_included(text)
    assert (resp.status, resp.data, resp.headers["content-type"]) == (200, [1, 2], "application/json")
    raw = ew.parse_included("HTTP/2.0 200 OK\n\n{\"name\": \"pkg\"}", raw = True)
    assert raw.data == "{\"name\": \"pkg\"}"
    missing = ew.parse_included("HTTP/2.0 404 Not Found\n\n{\"message\": \"Not Found\"}", raw = True)
    assert missing.status == 404 and missing.reason() == "HTTP 404, Not Found"
    assert ew.parse_included("").status == 0

# ======================================================================================================================
# Collection
# ======================================================================================================================

def test_a_clean_ecosystem_has_nothing_to_report(registries: None) -> None:
    snapshot = ew.collect(FakeTransport(base_table()), workers = 1)
    assert snapshot["schema"] == ew.SCHEMA
    assert [r["repo"] for r in snapshot["repos"]] == [ew.CICD_REPO, A, B]
    assert snapshot["summary"] == {
        "alerts": {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0},
        "alerts_total": 0,
        "pins_behind": 0,
        "drift": 0,
        "notices": 0,
        "errors": 0,
    }
    canonical = [p for p in snapshot["repos"][0]["pins"] if p["package"] == "kdf-fmt (canonical pin)"]
    assert canonical and canonical[0]["behind"] is False


def test_the_mutation_engine_is_compared_only_where_it_is_vendored(registries: None) -> None:
    """
    The engine's registry entry names repo A alone (D-040), so repo B, which never carries it, is no drift. The
    first live run reported thirteen false drifts before this held.
    """
    transport = FakeTransport(base_table())
    snapshot  = ew.collect(transport, workers = 1)
    assert snapshot["summary"]["drift"] == 0
    assert f"/repos/{B}/contents/scripts/kdf_scripts/mutation_runner.py" not in transport.calls
    assert f"/repos/{A}/contents/scripts/kdf_scripts/mutation_runner.py" in transport.calls


def test_kit_and_script_drift_are_found(registries: None) -> None:
    table = base_table()
    table[f"/repos/{A}/contents/docs/agent/KIT_VERSION"] = ok("v8.0.0\n")
    table[f"/repos/{A}/contents/scripts/kdf_scripts/mutation_runner.py"] = ok({"sha": "9" * 40})
    del table[f"/repos/{B}/contents/scripts/kdf_scripts/check_version.py"]
    snapshot = ew.collect(FakeTransport(table), workers = 1)
    drift    = {(r["repo"], d["kind"], d["path"], d["have"]) for r in snapshot["repos"] for d in r["drift"]}
    assert drift == {
        (A, "kit", "docs/agent/KIT_VERSION", "v8.0.0"),
        (A, "scripts", "scripts/kdf_scripts/mutation_runner.py", "9" * 10),
        (B, "scripts", "scripts/kdf_scripts/check_version.py", "missing"),
    }


def test_alerts_are_read_and_an_unreadable_repo_is_an_error_not_a_crash(registries: None) -> None:
    table = base_table()
    table[f"/repos/{A}/dependabot/alerts"] = ok([alert(1, "high"), alert(2, "critical", "jinja2"), alert(3, "low")])
    table[f"/repos/{B}/dependabot/alerts"] = ew.Response(403, {"message": "Resource not accessible by integration"})
    snapshot = ew.collect(FakeTransport(table), workers = 1)
    assert snapshot["summary"]["alerts"] == {"critical": 1, "high": 1, "medium": 0, "low": 1, "unknown": 0}
    repo_b = next(r for r in snapshot["repos"] if r["repo"] == B)
    assert repo_b["alerts"]["status"] == "unavailable"
    assert repo_b["errors"] == [{"section": "alerts", "detail": "HTTP 403, Resource not accessible by integration"}]
    first = next(r for r in snapshot["repos"] if r["repo"] == A)["alerts"]["open"][0]
    assert {k: first[k] for k in ("number", "severity", "package", "patched", "advisory")} == {
        "number": 1,
        "severity": "high",
        "package": "urllib3",
        "patched": "2.5.0",
        "advisory": "GHSA-1",
    }


def test_pins_are_judged_against_each_source_repos_latest_release(registries: None) -> None:
    table = base_table()
    table[f"/repos/{A}/contents/requirements.in"] = ok(
        "kdf-fmt @ git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@v1.2.0\n"
        "kriegerdataforge-sdk @ git+https://github.com/Needless2Say/kriegerdataforge-sdk.git@v0.12.2\n")
    table[f"/repos/{A}/contents/requirements.txt"] = ok(
        f"kdf-fmt @ git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@{SHA_LATEST}\n",
    )
    table[f"/repos/{A}/contents/package.json"] = ok(
        json.dumps( {"dependencies": {"@needless2say/report-form": "^0.1.0"}}),
    )
    table[f"/repos/{B}/contents/.github/workflows/ci.yml"] = ok("      kdf_fmt_ref: v1.3.0\n")
    table[f"/repos/{B}/contents/pyproject.toml"] = ew.Response(500, {"message": "Server Error"})
    snapshot = ew.collect(FakeTransport(table), workers = 1)
    pins     = {(r["repo"], p["file"], p["package"]): p for r in snapshot["repos"] for p in r["pins"]}
    assert pins[(A, "requirements.in", "kdf-fmt")]["behind"] is True
    assert pins[(A, "requirements.in", "kriegerdataforge-sdk")]["behind"] is False
    assert pins[(A, "requirements.txt", "kdf-fmt")]["note"] == "commit of v1.3.0"
    assert pins[(A, "package.json", "@needless2say/report-form")]["behind"] is True
    assert pins[(B, ".github/workflows/ci.yml", "kdf-fmt (kdf_fmt_ref)")]["behind"] is False
    assert snapshot["summary"]["pins_behind"] == 2
    repo_b = next(r for r in snapshot["repos"] if r["repo"] == B)
    assert repo_b["errors"] == [{"section": "pins", "detail": "pyproject.toml: HTTP 500, Server Error"}]


def test_a_pin_of_another_owned_repo_reads_that_repos_tags_once(registries: None) -> None:
    table = base_table()
    table[f"/repos/{A}/contents/requirements.in"] = ok(
        "extra @ git+https://github.com/Needless2Say/kriegerdataforge-extra.git@v2.0.0\n",
    )
    table[f"/repos/{OWNER}/kriegerdataforge-extra/tags"] = tags(("v2.1.0", "4" * 40))
    transport = FakeTransport(table)
    snapshot  = ew.collect(transport, workers = 1)
    pin       = next(p for r in snapshot["repos"] for p in r["pins"] if p["package"] == "extra")
    assert (pin["latest"], pin["behind"]) == ("v2.1.0", True)
    assert snapshot["releases"]["kriegerdataforge-extra"]["tag"] == "v2.1.0"


def notice_table(table: dict[str, ew.Response]) -> dict[str, ew.Response]:
    """
    Repo A with three workflows. CI's older and newer runs, a Dependabot run, and a run with no check suite. The newer
    CI run carries the runner's deprecation notice and warning, a plain warning, a failure, and a linter's warning about
    a deprecated call in the code, which is no notice of the platform.
    """
    table[f"/repos/{A}/actions/runs"] = ok({"workflow_runs": [
        {"workflow_id": 1, "name": "CI", "event": "push", "created_at": "2026-10-01T00:00:00Z", "check_suite_id": 10},
        {"workflow_id": 1, "name": "CI", "event": "pull_request", "created_at": "2026-10-03T00:00:00Z",
         "check_suite_id": 11},
        {"workflow_id": 2, "name": "pip in /", "event": "dynamic", "created_at": "2026-10-04T00:00:00Z",
         "check_suite_id": 12},
        {"workflow_id": 3, "name": "Release", "event": "push", "created_at": "2026-10-02T00:00:00Z",
         "check_suite_id": None},
    ]})
    table[f"/repos/{A}/check-suites/11/check-runs"] = ok({"check_runs": [
        {"id": 100, "name": "lint", "output": {"annotations_count": 5}},
        {"id": 101, "name": "test", "output": {"annotations_count": 0}},
    ]})
    table[f"/repos/{A}/check-runs/100/annotations"] = ok([
        {"path": ".github", "annotation_level": "notice", "message": UBUNTU},
        {"path": ".github", "annotation_level": "warning", "message": "Node.js 20 actions are deprecated."},
        {"path": ".github", "annotation_level": "warning", "message": "Unused variable x"},
        {"path": ".github", "annotation_level": "failure", "message": "This step is deprecated and failed"},
        {"path": "src/app.ts", "annotation_level": "warning", "message": "'oldCall' is deprecated, use newCall"},
    ])
    return table


def test_notices_read_the_latest_run_of_each_workflow_and_keep_deprecations_alone(registries: None) -> None:
    transport = FakeTransport(notice_table(base_table()))
    snapshot  = ew.collect(transport, workers = 1)
    repo_a    = next(r for r in snapshot["repos"] if r["repo"] == A)
    assert [(n["message"], n["level"], n["workflow"], n["job"]) for n in repo_a["notices"]] == [
        ("The ubuntu-latest label will migrate to Ubuntu 26.", "notice", "CI", "lint"),
        ("Node.js 20 actions are deprecated.", "warning", "CI", "lint"),
    ]
    assert f"/repos/{A}/check-suites/10/check-runs" not in transport.calls
    assert f"/repos/{A}/check-suites/12/check-runs" not in transport.calls
    assert f"/repos/{A}/check-suites/None/check-runs" not in transport.calls
    assert f"/repos/{A}/check-runs/101/annotations" not in transport.calls
    assert snapshot["summary"]["notices"] == 2


def test_an_unreadable_run_list_is_an_error(registries: None) -> None:
    table = base_table()
    table[f"/repos/{B}/actions/runs"] = ew.Response(403, {"message": "Forbidden"})
    snapshot = ew.collect(FakeTransport(table), workers = 1)
    repo_b   = next(r for r in snapshot["repos"] if r["repo"] == B)
    assert repo_b["errors"] == [{"section": "notices", "detail": "workflow runs: HTTP 403, Forbidden"}]

# ======================================================================================================================
# Rendering
# ======================================================================================================================

def snapshot_with_findings(registries: None) -> dict[str, Any]:
    table = notice_table(base_table())
    table[f"/repos/{A}/dependabot/alerts"] = ok([alert(1, "high"), alert(2, "critical", "jinja2")])
    table[f"/repos/{A}/contents/requirements.in"] = ok(
        "kdf-fmt @ git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@v1.2.0\n",
    )
    return ew.collect(FakeTransport(table), workers = 1)


def test_render_lists_every_section_and_hides_the_finding_keys(registries: None) -> None:
    body, news, state = ew.render(snapshot_with_findings(registries), run_url = "https://run/1")
    assert state == "open"
    assert news == ""
    assert "**2 open Dependabot alerts** (1 critical, 1 high, 0 medium, 0 low)" in body
    assert "| repo-a | 1 | 1 | 0 | 0 |" in body
    assert "- **critical** pip `jinja2` in `requirements.txt`, fixed in 2.5.0, GHSA-2" in body
    assert "| repo-a | `requirements.in` | kdf-fmt | `v1.2.0` | v1.3.0 |  |" in body
    assert "The ubuntu-latest label will migrate to Ubuntu 26." in body
    assert "Seen in repo-a (CI)." in body
    assert "[run](https://run/1)" in body
    keys = ew.previous_keys(body)
    assert ew.remembered(f"alert:{A}:1") in keys and ew.remembered(f"alert:{A}:2") in keys
    assert ew.remembered("pin:repo-a:requirements.in:kdf-fmt:v1.2.0") in keys
    assert len(keys) == 5  # two alerts, one pin, two notices


def test_news_is_only_what_the_previous_body_did_not_carry(registries: None) -> None:
    snapshot = snapshot_with_findings(registries)
    first, _, _ = ew.render(snapshot)
    _, same, _ = ew.render(snapshot, first)
    assert same == ""
    snapshot["repos"][1]["alerts"]["open"].append(ew.collect_alerts(FakeTransport(
        {f"/repos/{A}/dependabot/alerts": ok([alert(7, "medium", "pillow")])}), A)["open"][0])
    _, news, _ = ew.render(snapshot, first)
    assert news.startswith("New since the last run:")
    assert "medium alert on `pillow` (GHSA-7)" in news
    assert "jinja2" not in news


def test_a_clean_snapshot_is_clear_and_an_unreadable_one_is_not(registries: None) -> None:
    table = base_table()
    body, news, state = ew.render(ew.collect(FakeTransport(table), workers = 1), "previous body")
    assert state == "clear"
    assert news == ""
    assert "None open." in body and "Every pin is at its latest release." in body
    table[f"/repos/{B}/dependabot/alerts"] = ew.Response(403, {"message": "Forbidden"})
    _, _, state = ew.render(ew.collect(FakeTransport(table), workers = 1))
    assert state == "open"


def test_render_caps_the_alert_list_and_the_body_size(registries: None) -> None:
    table = base_table()
    table[f"/repos/{A}/dependabot/alerts"] = ok([alert(n, "low", f"pkg{n}") for n in range(1, 41)])
    snapshot = ew.collect(FakeTransport(table), workers = 1)
    body, _, _ = ew.render(snapshot)
    assert "- and 25 more, see the repo's Security tab" in body
    assert len(ew.previous_keys(body)) == 40
    many = [dict(a, url = "u" * 300) for a in ew.collect_alerts(FakeTransport(
        {f"/repos/{A}/dependabot/alerts": ok([alert(n, "low", "x" * 200) for n in range(1, 400)])}), A)["open"]]
    for repo in snapshot["repos"]:
        repo["alerts"]["open"] = many
    big, news, _ = ew.render(snapshot, "an earlier body with no marker")
    assert len(big) <= 65536
    assert len(ew.previous_keys(big)) == 3 * 399  # every finding of the three repos is remembered
    assert news.count("\n- ") <= 101 and news.endswith("more, see the body\n")


def test_a_body_past_the_limit_is_cut_and_keeps_its_marker(registries: None, monkeypatch: pytest.MonkeyPatch) -> None:
    table = base_table()
    table[f"/repos/{A}/dependabot/alerts"] = ok([alert(n, "low", "x" * 200) for n in range(1, 16)])
    snapshot = ew.collect(FakeTransport(table), workers = 1)
    monkeypatch.setattr(ew, "BODY_LIMIT", 2500)
    body, _, _ = ew.render(snapshot)
    assert "_The body was cut at GitHub's size limit._" in body
    assert len(body) <= 2500 + 200
    assert len(ew.previous_keys(body)) == 15


def test_previous_keys_tolerates_a_body_without_or_with_a_broken_marker() -> None:
    assert ew.previous_keys("") == set()
    assert ew.previous_keys("<!-- kdf-watch-keys:!!! -->") == set()
    assert ew.previous_keys(f"<!-- {ew.KEYS_MARKER}abc -->") == set()  # not a whole number of remembered keys
    marker = ew.remembered("a") + ew.remembered("b")
    assert ew.previous_keys(f"text\n<!-- kdf-watch-keys:{marker} -->\n") == {ew.remembered("a"), ew.remembered("b")}


def test_a_pipe_in_a_cell_cannot_break_the_table() -> None:
    assert ew._cell("a|b\nc") == "a\\|b c"

# ======================================================================================================================
# Command line
# ======================================================================================================================

def test_collect_without_a_token_refuses(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GH_TOKEN", raising = False)
    assert ew.main(["collect", "--out", str(tmp_path / "s.json")]) == 2


def test_the_log_carries_counts_and_never_an_alert(
    registries: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    The run's log is the private repo's, still it carries counts alone, never a package, an advisory or a link.
    """
    table = base_table()
    table[f"/repos/{A}/dependabot/alerts"] = ok([alert(1, "critical", "secretpkg")])
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setattr(ew, "HttpTransport", lambda token: FakeTransport(table))
    out = tmp_path / "s.json"
    assert ew.main(["collect", "--out", str(out)]) == 0
    printed = capsys.readouterr()
    assert "1 open alerts" in printed.out
    assert "secretpkg" not in printed.out + printed.err
    assert "GHSA-1" not in printed.out + printed.err
    body, news, state = (tmp_path / n for n in ("body.md", "news.md", "state.txt"))
    assert ew.main(["render", "--snapshot", str(out), "--body", str(body), "--news", str(news),
                    "--state", str(state), "--previous", str(tmp_path / "absent.md")]) == 0
    printed = capsys.readouterr()
    assert "secretpkg" not in printed.out + printed.err
    assert state.read_text(encoding = "utf-8") == "open\n"
    assert "secretpkg" in body.read_text(encoding = "utf-8")

# ======================================================================================================================
# The independent review's findings, 2026-10-04
# ======================================================================================================================

def test_an_unreadable_tag_list_is_a_blind_spot_that_keeps_the_issue_open(registries: None) -> None:
    """
    The App may not cover a source repo. Every pin of it is then unjudged, which must keep the issue open and say so,
    never close it as clear.
    """
    table = base_table()
    table[f"/repos/{OWNER}/kriegerdataforge-fmt/tags"] = ew.Response(403, {"message": "Not accessible by integration"})
    table[f"/repos/{A}/contents/requirements-dev.in"] = ok(
        "kdf-fmt @ git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@v1.3.0\n",
    )
    snapshot = ew.collect(FakeTransport(table), workers = 1)
    assert snapshot["summary"]["errors"] == 1
    body, _, state = ew.render(snapshot)
    assert state == "open"
    assert "the release tags of kriegerdataforge-fmt could not be read, HTTP 403" in body


def test_tags_are_read_past_the_first_page() -> None:
    """
    GitHub lists tags by name, so the newest release can sit on a later page.
    """
    path    = f"/repos/{OWNER}/kriegerdataforge-sdk/tags"
    table   = {
        path: ok([{"name": f"v0.1.{number}", "commit": {"sha": f"{number:040d}"}} for number in range(100)]),
        f"{path}#page=2": tags(("v0.12.2", "d" * 40)),
    }
    release = ew.latest_release(FakeTransport(table), "kriegerdataforge-sdk")
    assert (release.tag, release.sha) == ("v0.12.2", "d" * 40)


def test_a_marker_or_a_mention_inside_a_notice_is_made_inert(registries: None) -> None:
    """
    A run's annotation is written by whatever ran, so one that carries a marker, a mention or a backtick can neither
    hide the body, silence an alert's news nor ping a person.
    """
    table   = base_table()
    hidden  = ew.remembered(f"alert:{A}:1")
    planted = f"deprecated <!-- {ew.KEYS_MARKER}{hidden} --> ping @someone `x`"
    table   = notice_table(table)
    table[f"/repos/{A}/check-runs/100/annotations"] = ok([
        {"path": ".github", "annotation_level": "warning", "message": planted},
    ])
    table[f"/repos/{A}/dependabot/alerts"] = ok([alert(1, "high")])
    snapshot = ew.collect(FakeTransport(table), workers = 1)
    body, _, _ = ew.render(snapshot)
    before_footer = body.split("\n---\n")[0]
    assert "<!--" not in before_footer
    assert "&lt;!-- kdf-watch-keys:" in before_footer
    assert "@​someone" in before_footer and "@someone" not in before_footer
    assert "`x`" not in before_footer
    # a marker that does not close the body is no memory, so the alert is still news against it
    _, news, _ = ew.render(snapshot, f"an edited body <!-- {ew.KEYS_MARKER}{hidden} --> and text after it")
    assert "high alert on `urllib3`" in news


def test_a_link_that_does_not_point_at_github_is_dropped(registries: None) -> None:
    table   = base_table()
    strange = alert(1, "high")
    strange["html_url"] = "https://elsewhere.example/alert"
    table[f"/repos/{A}/dependabot/alerts"] = ok([strange])
    body, _, _ = ew.render(ew.collect(FakeTransport(table), workers = 1))
    assert "elsewhere.example" not in body
    assert "GHSA-1, alert 1" in body
