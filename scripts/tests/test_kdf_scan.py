"""
Tests for kdf_scan.py, the local code scan's wrapper (D-085).

Each test builds a rig, a machine folder of stand ins for Opengrep and zizmor, a rules clone at a commit and a repo
whose origin/main is its first commit, all with real git under the test's temp folder, then runs the wrapper's scan
and reads its report and last line. The stand ins in scan_fakes.py read the rules the wrapper materialised and the
files it copied, so a finding comes from a VULN(<rule id>) in a scanned file and its check id from the rules run.
The tests need git, which GitHub's runners and the owner's machines have.
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
from pathlib import Path

import distribute_scripts as ds
import pytest
from tests.scan_fakes import (
    COMMON,
    GIT,
    PYTHON,
    ROOT,
    commit,
    fake_python,
    git,
    init_repo,
    load,
    make_rig,
    makefile,
    rule_text,
    sha256,
    write,
)

SCAN = load("kdf_scan", COMMON / "kdf_scan.py")
LAST = re.compile(
    r"kdf-scan (?P<commit>[0-9a-f]{12}) (?P<state>clean-tree|dirty-tree|at-commit) bundle (?P<bundle>\S+) "
    r"opengrep 1\.30\.2 rules (?P<rules>[0-9a-f]{8}) zizmor 1\.30\.1 limits (?P<limits>\d+)(?: marks (?P<marks>\S+))?"
    r": (?P<result>.+) \(exit (?P<code>\d)\)"
)
# a well formed marker accepting an eval-detected finding on its line, and the two kinds' good forms with no opener
ACCEPT  = "  # nosemgrep: eval-detected the input is a module constant"
GOOD_OG = "nosemgrep: rule-x the input is constant"
GOOD_ZZ = "zizmor: ignore[template-injection] a caller sets this"
# the address uv 0.13.1's download metadata names for CPython 3.14.7 on Windows, read on 2026-10-21
UV_PYTHON_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/20260929/"
    "cpython-3.14.7%2B20260929-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
)

pytestmark = pytest.mark.skipif(GIT is None, reason = "the scan's tests need git")


def run(rig, **options) -> tuple[int, str]:
    machine = options.pop("machine", None) or rig.machine()
    buffer  = io.StringIO()
    code    = SCAN.scan(machine, rig.repo, out = buffer, **options)
    return code, buffer.getvalue()


def last(text: str) -> re.Match[str]:
    line  = text.rstrip("\n").splitlines()[-1]
    match = LAST.fullmatch(line)
    assert match, line
    return match

# ======================================================================================================================
# the last line and a clean scan
# ======================================================================================================================

def test_a_clean_repo_ends_clean_its_last_line_naming_the_commit_the_bundle_and_the_pins(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n", ".github/workflows/ci.yml": "name: CI\n"})
    code, text = run(rig)
    assert code == 0, text
    match = last(text)
    assert match["commit"] == git(rig.repo, "rev-parse", "HEAD")[:12]
    assert match["state"] == "clean-tree"
    assert match["bundle"] == "b" * 12
    assert match["rules"] == rig.commit[:8]
    assert match["limits"] == "0" and match["marks"] is None
    assert match["result"] == "CLEAN" and match["code"] == "0"
    assert "1 of 1 inventory files read" in text and "1 workflow files" in text


def test_uncommitted_work_is_scanned_and_the_tree_named_dirty(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    write(rig.repo, {"src/new.py": "eval(x)  # VULN(eval-detected)\n"})
    code, text = run(rig)
    assert code == 1, text
    assert last(text)["state"] == "dirty-tree"
    assert re.search(r"FAIL\s+src/new\.py:1\s+eval-detected", text)

# ======================================================================================================================
# the pins
# ======================================================================================================================

@pytest.mark.parametrize("pin", ["opengrep", "zizmor", "python-path", "digest", "commit"])
def test_each_pin_mismatch_refuses_with_exit_2_before_any_tool_runs(tmp_path: Path, pin: str) -> None:
    rig     = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    machine = rig.machine()
    if pin in ("opengrep", "zizmor"):
        tool    = getattr(machine, pin)
        machine = rig.machine(**{pin: SCAN.Tool(tool.name, tool.version, tool.path, "0" * 64, tool.command)})
    elif pin == "python-path":
        other = tmp_path / "python.exe"
        other.write_bytes(PYTHON.read_bytes()[:64])
        machine = rig.machine(python = SCAN.Tool("python", "3.14.7", other, sha256(other), (str(other),)))
    elif pin == "digest":
        machine = rig.machine(rules_digest = "0" * 64)
    else:
        machine = rig.machine(rules_commit = "1" * 40)
    code, text = run(rig, machine = machine)
    assert code == 2, text
    assert text.rstrip().splitlines()[-1].endswith("REFUSED (exit 2)")
    assert "kdf-scan-install.sh" in text
    assert rig.calls("opengrep") == [] and rig.calls("zizmor") == []


def test_the_rules_are_the_pinned_commits_raw_blobs_whatever_the_clone_holds(tmp_path: Path) -> None:
    rig    = make_rig(tmp_path, SCAN, {"src/app.py": "low(x)  # VULN(low-python)\nstray(x)  # VULN(stray-rule)\n"})
    source = tmp_path / "rules-src"
    commit(source, {".gitattributes": "python/** export-ignore\n"}, "attributes")
    clone = tmp_path / "rules-clone"
    subprocess.run(["git", "clone", "-q", str(source), str(clone)], check = True, capture_output = True)
    pinned  = git(clone, "rev-parse", "HEAD")
    folders = rig.machine().rule_folders
    digest  = SCAN.rules_digest(SCAN.rule_files(GIT, clone, pinned, folders))
    target  = "python/lang/security/audit/low-python.yaml"
    git(clone, "update-index", "--assume-unchanged", target)
    write(clone, {
        target: rule_text("low-python", "security", "HIGH"),
        "python/lang/security/audit/stray.yaml": rule_text("stray-rule", "security", "HIGH"),
    })
    assert SCAN.rules_digest(SCAN.rule_files(GIT, clone, pinned, folders)) == digest
    code, text = run(rig, machine = rig.machine(rules = clone, rules_commit = pinned, rules_digest = digest))
    assert code == 0, text


def test_a_rules_folder_missing_from_the_pinned_commit_is_refused(tmp_path: Path) -> None:
    rig     = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    folders = (*rig.machine().rule_folders, "python/flask/security")
    with pytest.raises(SCAN.Refusal):
        SCAN.rule_files(GIT, rig.rules, rig.commit, folders)

# ======================================================================================================================
# the scanners' environment and the repo left untouched
# ======================================================================================================================

def test_the_scanners_get_named_variables_alone_and_a_fresh_temp_folder_each_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n", ".github/workflows/ci.yml": "name: CI\n"})
    for name in ("GH_PACKAGES_PAT", "SEMGREP_RULES", "HTTPS_PROXY", "https_proxy", "GITHUB_TOKEN"):
        monkeypatch.setenv(name, "planted")
    assert run(rig)[0] == 0
    assert run(rig)[0] == 0
    calls = rig.calls("opengrep") + rig.calls("zizmor")
    assert len(calls) == 4
    temps = set()
    for call in calls:
        # the stand ins are Python, which on Linux sets LC_CTYPE in its own environment when the locale is C (PEP 538),
        # so that one name, at the value Python coerces to, is the stand in's own and never the wrapper's
        names = {name for name, value in call["env"].items() if not (name == "LC_CTYPE" and "UTF-8" in value.upper())}
        assert names <= {*SCAN.TOOL_ENVIRONMENT, "SYSTEMROOT", "PATH"}, call["env"].keys()
        assert "planted" not in call["env"].values()
        assert call["env"]["TEMP"] == call["env"]["TMP"]
        assert not Path(call["env"]["TEMP"]).exists()
        temps.add(call["env"]["TEMP"])
    assert len({call["env"]["TEMP"] for call in rig.calls("opengrep")}) == 2
    assert len(temps) >= 2


def test_the_scan_writes_nothing_into_the_repo(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "eval(x)  # VULN(eval-detected)\n", ".gitignore": "build/\n"})
    write(rig.repo, {"build/out.py": "x = 1\n", "notes.txt": "untracked\n"})
    before = git(rig.repo, "status", "--porcelain", "--ignored")
    run(rig)
    run(rig, at_commit = "HEAD")
    assert git(rig.repo, "status", "--porcelain", "--ignored") == before


def test_a_semgrepignore_in_the_repo_is_refused(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n", "src/.semgrepignore": "*.py\n"})
    code, text = run(rig)
    assert code == 2 and ".semgrepignore" in text

# ======================================================================================================================
# coverage
# ======================================================================================================================

def test_a_file_opengrep_did_not_read_makes_the_scan_incomplete(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n", "src/odd.py": "x = 1  # OPENGREP-SKIPS-ME\n"})
    code, text = run(rig)
    assert code == 4, text
    assert "src/odd.py" in text and last(text)["result"].startswith("INCOMPLETE")


def test_a_workflow_zizmor_did_not_collect_makes_the_scan_incomplete(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {".github/workflows/ci.yml": "name: CI\n# ZIZMOR-SKIPS-ME\n"})
    code, text = run(rig)
    assert code == 4, text
    assert ".github/workflows/ci.yml" in text


@pytest.mark.parametrize("content", [
    "x = 1  # PARSE-ERROR\n",
    "x = 1  # RULE-TIMEOUT\n",
    "x = 1\n" + "#" * 1_000_001 + "\n",
], ids = ["parse-error", "timeout", "size-skip"])
def test_a_parse_error_a_timeout_and_a_size_skip_each_end_incomplete(tmp_path: Path, content: str) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": content})
    code, text = run(rig)
    assert code == 4, text
    assert last(text)["result"].startswith("INCOMPLETE")


def test_an_error_opengrep_names_no_file_for_makes_the_scan_incomplete(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    rig.set_scenario(opengrep_pathless_error = True)
    assert run(rig)[0] == 4


def test_a_recorded_limit_passes_on_its_blob_and_fails_after_one_byte_changes(tmp_path: Path) -> None:
    content = "const view = import('x').thing  // PARSE-ERROR\n"
    digest  = SCAN.content_sha256(content.encode("utf-8"))
    limit   = f"SCAN_LIMIT += src/view.ts@{digest}  # Opengrep reads its import type partly"
    rig     = make_rig(tmp_path, SCAN, {"src/view.ts": content, "Makefile": makefile(limit)})
    code, text = run(rig)
    assert code == 0, text
    assert last(text)["limits"] == "1"
    write(rig.repo, {"src/view.ts": content.replace("thing", "thinG")})
    code, text = run(rig)
    assert code == 4, text


def test_a_recorded_limit_with_crlf_line_endings_matches_its_lf_blob(tmp_path: Path) -> None:
    content = "const view = import('x').thing  // PARSE-ERROR\n"
    digest  = SCAN.content_sha256(content.encode("utf-8"))
    limit   = f"SCAN_LIMIT += src/view.ts@{digest}  # Opengrep reads its import type partly"
    rig     = make_rig(tmp_path, SCAN, {"src/view.ts": content, "Makefile": makefile(limit)})
    (rig.repo / "src" / "view.ts").write_bytes(content.replace("\n", "\r\n").encode("utf-8"))
    assert run(rig)[0] == 0


def test_a_limit_with_nothing_to_pass_is_a_bad_line(tmp_path: Path) -> None:
    content = "x = 1\n"
    limit   = f"SCAN_LIMIT += src/app.py@{SCAN.content_sha256(content.encode())}  # it once failed to parse here"
    rig     = make_rig(tmp_path, SCAN, {"src/app.py": content, "Makefile": makefile(limit)})
    code, text = run(rig)
    assert code == 1, text
    assert re.search(r"BAD\s+src/app\.py", text)


@pytest.mark.parametrize("line", [
    "SCAN_EXCLUDE += vercel_api",
    "SCAN_EXCLUDE += vercel_api  # two words",
    "SCAN_EXCLUDE += ../outside  # a folder outside the repo",
    "SCAN_LIMIT += src/a.py@1234  # not a digest at all",
])
def test_a_malformed_policy_line_is_refused_before_scanning(tmp_path: Path, line: str) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n", "Makefile": makefile(line)})
    code, text = run(rig)
    assert code == 2, text
    assert rig.calls("opengrep") == []


def test_two_managed_blocks_are_refused(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n", "Makefile": makefile() + makefile()})
    assert run(rig)[0] == 2

# ======================================================================================================================
# the workflow policy
# ======================================================================================================================

def test_a_call_of_cicd_at_a_feature_branch_fails_where_main_passes(tmp_path: Path) -> None:
    calls = "Needless2Say/kriegerdataforge-cicd/.github/workflows/ci-python-lint.yml"
    rig   = make_rig(tmp_path, SCAN, {".github/workflows/ci.yml": f"jobs:\n  lint:\n    uses: {calls}@main\n"})
    code, text = run(rig)
    assert code == 0, text
    commit(rig.repo, {".github/workflows/ci.yml": f"jobs:\n  lint:\n    uses: {calls}@feature\n"})
    code, text = run(rig)
    assert code == 1, text
    assert re.search(r"FAIL\s+\.github/workflows/ci\.yml:3\s+unpinned-uses", text)


def test_a_third_party_action_by_tag_fails_and_by_hash_passes(tmp_path: Path) -> None:
    step = "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@{ref}\n"
    rig  = make_rig(tmp_path, SCAN, {".github/workflows/ci.yml": step.format(ref = "v4")})
    assert run(rig)[0] == 1
    commit(rig.repo, {".github/workflows/ci.yml": step.format(ref = "a" * 40)})
    assert run(rig)[0] == 0


def test_zizmor_runs_offline_with_no_ignores_and_the_bundles_configuration(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {".github/workflows/ci.yml": "name: CI\n"})
    run(rig)
    args = rig.calls("zizmor")[0]["args"]
    assert "--offline" in args and "--no-ignores" in args
    assert args[args.index("--min-severity") + 1] == "medium"
    assert args[args.index("--min-confidence") + 1] == "medium"
    assert args[args.index("--format") + 1] == "json"
    config = args[args.index("--config") + 1]
    assert Path(config).name == "kdf_zizmor.yml"


def test_opengrep_runs_with_nosem_disabled_and_every_rule_folder(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    run(rig)
    args = rig.calls("opengrep")[0]["args"]
    assert "--disable-nosem" in args and "--taint-intrafile" in args and "--disable-version-check" in args
    configs = [args[index + 1] for index, arg in enumerate(args) if arg == "--config"]
    assert configs == [*(f"rules/{folder}" for folder in rig.machine().rule_folders), "rules/kdf"]

# ======================================================================================================================
# suppressions
# ======================================================================================================================

def test_a_well_formed_marker_accepts_its_finding_and_prints_its_reason(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": f"eval(x)  # VULN(eval-detected){ACCEPT}\n"})
    code, text = run(rig)
    assert code == 0, text
    assert re.search(r"ACCEPTED\s+src/app\.py:1\s+eval-detected\s+the input is a module constant", text)


def test_a_marker_alone_on_the_line_above_accepts_the_finding_below(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": f"{ACCEPT.strip()}\neval(x)  # VULN(eval-detected)\n"})
    assert run(rig)[0] == 0


@pytest.mark.parametrize("marker", [
    "# nosemgrep",
    "# nosemgrep: eval-detected",
    "# nosemgrep: eval-detected, low-python the input is a constant",
    "# nosemgrep: eval-detected the input, a constant",
    "# nosemgrep: eval-detected too short",
    "# nosem: eval-detected the input is a constant",
    "# noopengrep: eval-detected the input is a constant",
])
def test_each_bad_suppression_fails_the_scan(tmp_path: Path, marker: str) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": f"eval(x)  # VULN(eval-detected)  {marker}\n"})
    code, text = run(rig)
    assert code == 1, text
    assert re.search(r"BAD\s+src/app\.py:1", text)


def test_a_stale_marker_fails_the_scan(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": f"x = 1{ACCEPT}\n"})
    code, text = run(rig)
    assert code == 1 and "stale" in text, text


def test_a_marker_in_an_excluded_file_fails_the_scan(tmp_path: Path) -> None:
    excluded = "SCAN_EXCLUDE += generated  # generated code that no hand edits"
    rig      = make_rig(tmp_path, SCAN, {"generated/api.py": f"x = 1{ACCEPT}\n", "Makefile": makefile(excluded)})
    code, text = run(rig)
    assert code == 1, text
    assert re.search(r"BAD\s+generated/api\.py:1", text)


def test_an_ambiguous_rule_id_is_refused(tmp_path: Path) -> None:
    marker = "  # nosemgrep: shared-name the name is fixed in this module"
    rig    = make_rig(tmp_path, SCAN, {"src/app.py": f"go(x)  # VULN(shared-name){marker}\n"})
    code, text = run(rig)
    assert code == 1 and "ambiguous" in text, text


def test_two_rules_matching_one_line_are_kept_apart(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": f"eval(x)  # VULN(eval-detected) VULN(second-rule){ACCEPT}\n"})
    code, text = run(rig)
    assert code == 1, text
    assert re.search(r"ACCEPTED\s+src/app\.py:1\s+eval-detected", text)
    assert re.search(r"FAIL\s+src/app\.py:1\s+second-rule", text)


def test_a_marker_inside_a_multi_line_match_is_stale_and_one_above_it_accepts(tmp_path: Path) -> None:
    lines = ["a = 1", "eval(x)  # VULN(eval-detected,3)", f"b = 2{ACCEPT}", "c = 3"]
    rig   = make_rig(tmp_path, SCAN, {"src/app.py": "\n".join(lines) + "\n"})
    code, text = run(rig)
    assert code == 1 and "stale" in text and re.search(r"FAIL\s+src/app\.py:2", text), text
    lines = ["a = 1", ACCEPT.strip(), "eval(x)  # VULN(eval-detected,3)", "b = 2", "c = 3"]
    commit(rig.repo, {"src/app.py": "\n".join(lines) + "\n"})
    assert run(rig)[0] == 0


def test_a_zizmor_marker_on_the_run_line_accepts_a_finding_inside_the_block(tmp_path: Path) -> None:
    workflow = (
        "jobs:\n  a:\n    steps:\n      - name: Install\n"
        "        run: |  # zizmor: ignore[template-injection] a caller of ours sets this input\n"
        "          echo hello  ZFIND(template-injection,run)\n"
    )
    rig      = make_rig(tmp_path, SCAN, {".github/workflows/ci.yml": workflow})
    code, text = run(rig)
    assert code == 0, text
    assert re.search(r"ACCEPTED\s+\.github/workflows/ci\.yml:6\s+template-injection", text)


@pytest.mark.parametrize("marker", [
    "# zizmor: ignore[template-injection]",
    "# zizmor: ignore[template-injection,excessive-permissions] a caller of ours sets this",
    "# zizmor: ignore[template-injection] two words",
])
def test_each_bad_zizmor_marker_fails_the_scan(tmp_path: Path, marker: str) -> None:
    workflow = f"jobs:\n  a:\n    steps:\n      - run: echo  ZFIND(template-injection)  {marker}\n"
    rig      = make_rig(tmp_path, SCAN, {".github/workflows/ci.yml": workflow})
    code, text = run(rig)
    assert code == 1 and "BAD" in text, text


def test_without_no_ignores_every_zizmor_marker_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(SCAN, "ZIZMOR_NO_IGNORES", False)
    marker   = "# zizmor: ignore[template-injection] a caller of ours sets this input"
    workflow = f"jobs:\n  a:\n    steps:\n      - run: echo  ZFIND(template-injection)  {marker}\n"
    rig      = make_rig(tmp_path, SCAN, {".github/workflows/ci.yml": workflow})
    code, text = run(rig)
    assert code == 1 and "BAD" in text, text
    assert "--no-ignores" not in rig.calls("zizmor")[0]["args"]


@pytest.mark.parametrize(("path", "text", "found"), [
    ("a.py", f'x = "# {GOOD_OG}"\n', []),
    ("a.py", f'x = f"{{a}} # {GOOD_OG}"\n', []),
    ("a.py", f"'''\n# {GOOD_OG}\n'''\n", []),
    ("a.py", f'x = "# nosemgrep: a b c d"  # {GOOD_OG}\n', [1]),
    ("a.py", f"\ufeff# {GOOD_OG}\nx = 1\n", [1]),
    ("a.js", f'const s = "// {GOOD_OG}";\n', []),
    ("a.ts", f"const s = `\n// {GOOD_OG}\n`;\n", []),
    ("a.ts", f"const s = `a ${{ x /* {GOOD_OG} */ }} b`;\n", [1]),
    ("a.js", f"const r = /[ //{GOOD_OG}]/;\n", []),
    ("a.js", f"const a = b / c; // {GOOD_OG}\n", [1]),
    ("a.ts", f"if (a < b) {{ f<T>(x); }} // {GOOD_OG}\n", [1]),
    ("a.tsx", f"const e = (\n  <p>\n    // {GOOD_OG}\n  </p>\n);\n", []),
    ("a.tsx", f"const e = (\n  <p>\n    {{/* {GOOD_OG} */}}\n    <b>don't</b>\n  </p>\n);\n", [3]),
    ("a.jsx", f"const e = <a href=\"http://x.y/'z\" {{...p}}>x</a>; // {GOOD_OG}\n", [1]),
    ("a.mjs", f"#!/usr/bin/env node\nreturn /'/.test(s); // {GOOD_OG}\n", [2]),
    ("a.yml", f"jobs:\n  a:\n    steps:\n      - run: |\n          # {GOOD_ZZ}\n          echo\n", []),
    ("a.yml", f"steps:\n  - |\n    # {GOOD_ZZ}\n", []),
    ("a.yml", f"      - run: |  # {GOOD_ZZ}\n          echo\n", [1]),
    ("a.yml", f"a:\n  run: |\n    echo\n\n  # {GOOD_ZZ}\n  b: 1\n", [5]),
    ("a.yml", f"a: &anchor |\n  # {GOOD_ZZ}\n", []),
    ("a.yml", f'name: "a # {GOOD_ZZ}"\n', []),
    ("a.yml", f"name: 'it''s # {GOOD_ZZ}'\n", []),
    ("a.yml", f"name: it's here  # {GOOD_ZZ}\n", [1]),
    ("a.yml", f"a: first\n  'second  # {GOOD_ZZ}\nb: \"c # {GOOD_ZZ}\"\n", [2]),
    ("a.yml", f"a: [b,\n  'c # {GOOD_ZZ}']\n", []),
    ("a.yml", f"a: b#{GOOD_ZZ}\n", []),
    ("README.md", f"# {GOOD_OG}\n", [1]),
])
def test_a_marker_counts_only_inside_a_comment_its_reader_finds(path: str, text: str, found: list[int]) -> None:
    markers = SCAN.find_markers(path, text.encode("utf-8"))
    assert [marker.line for marker in markers] == found, [vars(marker) for marker in markers]
    assert not any(SCAN.UNREADABLE in marker.bad for marker in markers)


@pytest.mark.parametrize(("path", "text"), [
    ("a.py", f"x = (\n    1  # {GOOD_OG}\n"),
    ("a.py", f"x = 1\r# {GOOD_OG}\n"),
    ("a.ts", f"const s = `abc // {GOOD_OG}\n"),
    ("a.js", f"/* {GOOD_OG}\n"),
    ("a.tsx", f"const f = <T,>(x: T) => x; // {GOOD_OG}\n"),
    ("a.js", f"}} // {GOOD_OG}\n"),
    ("a.yml", f'a: "b\n# {GOOD_ZZ}\n'),
    ("a.yml", f"a: [b,\n# {GOOD_ZZ}\n"),
])
def test_a_file_whose_comments_cannot_be_read_whole_has_every_marker_refused(path: str, text: str) -> None:
    markers = SCAN.find_markers(path, text.encode("utf-8"))
    assert markers and all(SCAN.UNREADABLE in marker.bad for marker in markers), [vars(m) for m in markers]


def test_marker_text_in_a_string_accepts_nothing(tmp_path: Path) -> None:
    # the probe Codex ran on 2026-10-22, an assignment's string appended to the finding's line
    line = 'eval(x); note = "# nosemgrep: eval-detected the input is a module constant"  # VULN(eval-detected)\n'
    rig  = make_rig(tmp_path, SCAN, {"src/app.py": line})
    code, text = run(rig)
    assert code == 1 and "ACCEPTED" not in text, text
    assert re.search(r"FAIL\s+src/app\.py:1\s+eval-detected", text), text


def test_a_zizmor_marker_in_a_run_blocks_script_accepts_nothing(tmp_path: Path) -> None:
    workflow = (
        "jobs:\n  a:\n    steps:\n      - name: Install\n        run: |\n"
        "          # zizmor: ignore[template-injection] a caller of ours sets this input\n"
        "          echo hello  ZFIND(template-injection)\n"
    )
    rig      = make_rig(tmp_path, SCAN, {".github/workflows/ci.yml": workflow})
    code, text = run(rig)
    assert code == 1 and "ACCEPTED" not in text, text

# ======================================================================================================================
# the rule policy
# ======================================================================================================================

@pytest.mark.parametrize(("files", "expected"), [
    ({"src/app.py": "low(x)  # VULN(low-python)\n"}, 0),
    ({"src/app.ts": "low(x)  // VULN(low-typescript)\n"}, 1),
    ({"scripts/walk.js": "fs.readFile(p)  // VULN(detect-non-literal-fs-filename)\n"}, 0),
    ({"src/walk.js": "fs.readFile(p)  // VULN(detect-non-literal-fs-filename)\n"}, 1),
    ({"tools/x/join.js": "path.join(a, b)  // VULN(path-join-resolve-traversal)\n"}, 0),
    ({"src/join.ts": "path.join(a, b)  // VULN(path-join-resolve-traversal)\n"}, 1),
    ({"src/log.py": "log.info(user)  # VULN(python-logger-credential-disclosure)\n"}, 0),
    ({"src/style.py": "x = y  # VULN(style-only)\n"}, 0),
    ({"src/kdf.py": "secret_value(x)  # VULN(kdf-test-rule)\n"}, 1),
])
def test_the_rule_policy_keeps_and_drops_by_metadata_id_and_path(
    tmp_path: Path,
    files: dict[str, str],
    expected: int,
) -> None:
    rig = make_rig(tmp_path, SCAN, files)
    code, text = run(rig)
    assert code == expected, text


def test_tests_and_declared_exclusions_never_reach_the_inventory(tmp_path: Path) -> None:
    excluded = "SCAN_EXCLUDE += vercel_api  # generated by make vercel-compact and never edited"
    rig      = make_rig(tmp_path, SCAN, {
        "Makefile": makefile(excluded),
        "vercel_api/app.py": "eval(x)  # VULN(eval-detected)\n",
        "unit_tests/test_app.py": "eval(x)  # VULN(eval-detected)\n",
        "src/__tests__/app.test.ts": "eval(x)  // VULN(low-typescript)\n",
        "e2e/ci_stack.py": "print(1)\n",
        "src/app.py": "print(1)\n",
    })
    code, text = run(rig)
    assert code == 0, text
    assert "2 of 2 inventory files read" in text
    assert re.search(r"EXCLUDED\s+vercel_api\s+generated by make vercel-compact", text)

# ======================================================================================================================
# the branch report
# ======================================================================================================================

def test_every_accepted_finding_is_printed_the_branchs_new_and_changed_ones_marked(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {
        "src/old.py": f"eval(a)  # VULN(eval-detected){ACCEPT}\n",
        "src/kept.py": f"eval(b)  # VULN(eval-detected){ACCEPT}\n",
    })
    commit(rig.repo, {
        "src/new.py": f"eval(c)  # VULN(eval-detected){ACCEPT}\n",
        "src/kept.py": f"eval(b + 1)  # VULN(eval-detected){ACCEPT}\n",
    })
    code, text = run(rig)
    assert code == 0, text
    lines = {line.split()[1]: line for line in text.splitlines() if line.startswith("ACCEPTED")}
    assert set(lines) == {"src/old.py:1", "src/kept.py:1", "src/new.py:1"}
    assert lines["src/old.py:1"].endswith("constant")
    assert lines["src/new.py:1"].endswith("(new)")
    assert lines["src/kept.py:1"].endswith("(new)") or lines["src/kept.py:1"].endswith("(changed)")


def test_a_finding_in_a_file_the_branch_did_not_touch_is_named_older_than_the_branch(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/old.py": "eval(a)  # VULN(eval-detected)\n"})
    commit(rig.repo, {"src/other.py": "print(2)\n"})
    code, text = run(rig)
    assert code == 1, text
    assert re.search(r"FAIL\s+src/old\.py:1\s+eval-detected.*\(older than the branch\)", text)


def test_a_missing_origin_main_makes_the_comparison_and_the_scan_incomplete(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    git(rig.repo, "update-ref", "-d", "refs/remotes/origin/main")
    code, text = run(rig)
    assert code == 4 and "origin/main" in text, text


def test_a_change_to_the_scan_target_is_marked(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    commit(rig.repo, {"Makefile": makefile().replace("kdf-scan.py", "kdf-scan.py --quiet")})
    code, text = run(rig)
    assert "target-changed" in (last(text)["marks"] or ""), text

# ======================================================================================================================
# a scan at a commit
# ======================================================================================================================

def test_a_scan_at_a_commit_reads_its_tree_and_never_the_working_trees_edits(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    write(
        rig.repo,
        {"src/app.py": "eval(x)  # VULN(eval-detected)\n", "src/new.py": "eval(y)  # VULN(eval-detected)\n"},
    )
    code, text = run(rig, at_commit = "HEAD")
    assert code == 0, text
    assert last(text)["state"] == "at-commit"
    assert run(rig)[0] == 1


def test_an_exclusion_the_branch_adds_is_ignored_at_a_commit_and_marked(tmp_path: Path) -> None:
    excluded = "SCAN_EXCLUDE += generated  # generated code that no hand edits"
    rig      = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    commit(rig.repo, {"Makefile": makefile(excluded), "generated/api.py": "eval(x)  # VULN(eval-detected)\n"})
    code, text = run(rig, at_commit = "HEAD")
    assert code == 1, text
    assert "policy-added" in last(text)["marks"]
    code, text = run(rig)
    assert code == 0, text
    assert "policy-added" in last(text)["marks"]


def test_a_symlink_or_a_gitlink_at_a_commit_is_incomplete(tmp_path: Path) -> None:
    rig  = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    blob = subprocess.run(
        ["git", "-C", str(rig.repo), "hash-object", "-w", "--stdin"],
        input = b"src/app.py",
        capture_output = True,
        check = True,
    ).stdout.decode().strip()
    git(rig.repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},src/link.py")
    git(rig.repo, "update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},vendor/lib")
    git(rig.repo, "commit", "-q", "-m", "links")
    code, text = run(rig, at_commit = "HEAD")
    assert code == 4, text
    assert "src/link.py" in text and "vendor/lib" in text


def test_a_replacement_ref_never_changes_what_a_commit_scan_reads(tmp_path: Path) -> None:
    rig     = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    bad     = commit(rig.repo, {"src/app.py": "eval(x)  # VULN(eval-detected)\n"})
    clean   = git(rig.repo, "rev-parse", "HEAD~1")
    blob    = git(rig.repo, "rev-parse", f"{bad}:src/app.py")
    clean_b = git(rig.repo, "rev-parse", f"{clean}:src/app.py")
    git(rig.repo, "replace", blob, clean_b)
    git(rig.repo, "replace", bad, clean)
    code, text = run(rig, at_commit = bad)
    assert code == 1, text


def test_a_missing_object_in_a_partial_clone_is_incomplete_and_never_fetched(tmp_path: Path) -> None:
    rig  = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    head = commit(rig.repo, {"src/big.py": "eval(x)  # VULN(eval-detected)\n"})
    git(rig.repo, "config", "uploadpack.allowFilter", "true")
    partial = tmp_path / "partial"
    subprocess.run(
        ["git", "clone", "-q", "--filter=blob:none", "--no-checkout", rig.repo.as_uri(), str(partial)],
        check = True,
        capture_output = True,
    )
    git(partial, "update-ref", "refs/remotes/origin/main", git(rig.repo, "rev-parse", "HEAD~1"))
    blob = git(partial, "rev-parse", f"{head}:src/big.py")
    assert f"?{blob}" in git(partial, "rev-list", "--objects", "--missing=print", head).split()
    rig.repo = partial
    code, text = run(rig, at_commit = head)
    assert code == 4, text
    assert "src/big.py could not be read" in text
    assert f"?{blob}" in git(partial, "rev-list", "--objects", "--missing=print", head).split()

# ======================================================================================================================
# a bundle behind cicd's main
# ======================================================================================================================

def test_a_bundle_older_than_the_last_change_to_its_files_warns_and_names_the_install(tmp_path: Path) -> None:
    rig   = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    cicd  = init_repo(tmp_path / "cicd")
    older = commit(cicd, {"scripts/common/kdf_scan.py": "one\n"})
    newer = commit(cicd, {"scripts/common/scan_rules/x.yaml": "two\n"})
    commit(cicd, {"README.md": "docs only\n"})
    git(cicd, "update-ref", "refs/remotes/origin/main", "HEAD")
    code, text = run(rig, machine = rig.machine(cicd = cicd, bundle = older))
    assert code == 0, text
    assert "kdf-scan-install.sh" in text and "bundle-behind" in last(text)["marks"]
    code, text = run(rig, machine = rig.machine(cicd = cicd, bundle = newer))
    assert last(text)["marks"] is None, text

# ======================================================================================================================
# the tools failing
# ======================================================================================================================

@pytest.mark.parametrize("scenario", [
    {"opengrep_exit": 2},
    {"opengrep_no_json": True},
    {"opengrep_outside": True},
    {"zizmor_exit_error": True},
])
def test_a_tool_that_fails_or_answers_outside_its_tree_ends_exit_3(tmp_path: Path, scenario: dict) -> None:
    rig = make_rig(tmp_path, SCAN, {
        "src/app.py": "eval(x)  # VULN(eval-detected)\n",
        ".github/workflows/ci.yml": "name: CI\n",
    })
    rig.set_scenario(**scenario)
    code, text = run(rig)
    assert code == 3, text
    assert "(exit 3)" in text.splitlines()[-1]


def test_opengreps_error_written_to_its_json_alone_is_named_in_the_failure(tmp_path: Path) -> None:
    # a rule file Opengrep refuses ends in exit 7, its reason in the JSON alone and nothing on either stream
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    rig.set_scenario(opengrep_json_error = "Invalid YAML file rules/kdf/x.yaml:\n mapping values are not allowed here")
    code, text = run(rig)
    assert code == 3, text
    assert "Opengrep exited 7, Invalid YAML file rules/kdf/x.yaml: mapping values are not allowed here" in text


def test_workflows_zizmor_could_load_none_of_make_the_scan_incomplete_not_failed(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n", ".github/workflows/ci.yml": "name: CI\n"})
    rig.set_scenario(zizmor_no_inputs = True)
    code, text = run(rig)
    assert code == 4, text
    assert last(text)["result"].startswith("INCOMPLETE"), text

# ======================================================================================================================
# the pins printed for the install, and kdf_zizmor.yml
# ======================================================================================================================

def test_the_pins_print_as_plain_assignments_the_install_reads(capsys: pytest.CaptureFixture[str]) -> None:
    assert SCAN.main(["--pins"]) == 0
    printed = dict(line.split("=", 1) for line in capsys.readouterr().out.splitlines())
    assert printed["OPENGREP_VERSION"] == SCAN.OPENGREP_VERSION
    assert printed["OPENGREP_IDENTITY"].startswith("https://github.com/opengrep/opengrep/.github/workflows/")
    assert printed["RULES_COMMIT"] == SCAN.RULES_COMMIT
    for name, value in printed.items():
        assert re.fullmatch(r"[A-Z0-9_]+", name) and re.fullmatch(r"[A-Za-z0-9_.:/@%+=-]+", value), (name, value)
    assert "PYTHON_SHA256" not in printed
    assert {"ZIZMOR_WHEEL_URL", "COSIGN_VERSION", "COSIGN_URL", "COSIGN_SHA256"} <= set(printed)
    assert {"OPENGREP_URL", "PYTHON_ARCHIVE_BASE"} <= set(printed)


def test_the_pythons_four_pins_stay_one_plain_assignment_each_for_the_installs_pattern() -> None:
    source = (COMMON / "kdf_scan.py").read_text(encoding = "utf-8")
    for name in ("PYTHON_VERSION", "PYTHON_BUILD", "PYTHON_ARCHIVE_SHA256", "PYTHON_ARCHIVE_BASE"):
        found = re.findall(rf"^{name} += \"([^\"\n]+)\"$", source, re.MULTILINE)
        assert found == [getattr(SCAN, name)], name
        assert len(re.findall(rf"^{name}\b", source, re.MULTILINE)) == 1, name


def test_the_pythons_archive_address_is_the_one_uv_0_13_1_names() -> None:
    assert SCAN.PYTHON_ARCHIVE_URL == UV_PYTHON_URL
    assert SCAN.PYTHON_ARCHIVE_URL.startswith(f"{SCAN.PYTHON_ARCHIVE_BASE}/{SCAN.PYTHON_BUILD}/")


def test_opengreps_address_is_its_release_asset_whose_cert_and_sig_sit_beside_it() -> None:
    assert SCAN.OPENGREP_URL == (
        "https://github.com/opengrep/opengrep/releases/download/v1.30.2/opengrep_windows_x86.exe"
    )


def test_the_rules_digest_reads_the_clone_with_the_git_it_is_given(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rig      = make_rig(tmp_path, SCAN)
    command  = ["--rules-digest", str(rig.rules), "--git", GIT]
    original = SCAN.RULES_COMMIT, SCAN.RULE_FOLDERS
    SCAN.RULES_COMMIT, SCAN.RULE_FOLDERS = rig.commit, ("python/lang/security", "javascript/lang/security")
    try:
        assert SCAN.main(command) == 0
        expected = SCAN.rules_digest(SCAN.rule_files(GIT, rig.rules, rig.commit, SCAN.RULE_FOLDERS))
        assert capsys.readouterr().out.strip() == expected
        assert SCAN.main(["--rules-digest", str(rig.rules), "--git", str(tmp_path / "no-git.exe")]) == 2
        assert "kdf-scan  refused" in capsys.readouterr().out
    finally:
        SCAN.RULES_COMMIT, SCAN.RULE_FOLDERS = original


def test_the_pythons_manifest_holds_every_file_and_no_other(tmp_path: Path) -> None:
    folder = fake_python(tmp_path)
    assert SCAN.python_manifest(folder) == []
    (folder / "Lib" / "extra.py").write_bytes(b"x\n")
    (folder / "DLLs" / "_ssl.pyd").unlink()
    (folder / "Lib" / "os.py").write_bytes(b"# changed\n")
    problems = SCAN.python_manifest(folder)
    assert any("Lib/extra.py is not in the manifest" in line for line in problems)
    assert any("DLLs/_ssl.pyd is missing" in line for line in problems)
    assert any("Lib/os.py differs" in line for line in problems)
    (folder / "manifest.sha256").unlink()
    assert SCAN.python_manifest(folder)


def _yaml_keys(text: str) -> list[tuple[int, str, str]]:
    found = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition(":")
        found.append((len(line) - len(line.lstrip(" ")), key.strip().strip('"'), value.split("#")[0].strip()))
    return found


def test_kdf_zizmor_yml_names_only_known_keys_each_disabled_audit_with_its_reason() -> None:
    text  = (COMMON / "kdf_zizmor.yml").read_text(encoding = "utf-8")
    keys  = _yaml_keys(text)
    known = {
        0: {"rules"},
        2: {"unpinned-uses", "secrets-inherit", "dependabot-cooldown"},
        4: {"config", "disable"},
        6: {"policies"},
        8: {"*"},
    }
    for indent, key, _value in keys:
        assert key in known.get(indent, set()), (indent, key)
    assert ("8", "*", "hash-pin") in {(str(indent), key, value) for indent, key, value in keys}
    for audit in ("secrets-inherit", "dependabot-cooldown"):
        block = text[text.index(f"  {audit}:"):]
        assert block.splitlines()[1].strip() == "disable: true"
        before = text[:text.index(f"  {audit}:")].rstrip().splitlines()[-1]
        assert before.strip().startswith("#"), audit
    assert "pending a later change" in text


def test_kdfs_rule_patterns_holding_a_colon_and_a_space_are_quoted_so_yaml_reads_them() -> None:
    # unquoted, "$KEY: $VALUE" in a pattern reads as a mapping, and Opengrep refuses the whole file, exit 7
    for rule in sorted((COMMON / "scan_rules").glob("*.yaml")):
        for number, line in enumerate(rule.read_text(encoding = "utf-8").splitlines(), 1):
            key, _sep, value = line.strip().removeprefix("- ").partition(": ")
            if key.startswith("pattern") and value and value[0] not in "'\"|>":
                assert ": " not in value, (rule.name, number)

# ======================================================================================================================
# cicd's own targets and the fixtures, which run against the installed tools and never in make ci
# ======================================================================================================================

def test_cicds_own_makefile_holds_the_one_managed_block_the_sync_writes() -> None:
    text = (ROOT / "Makefile").read_text(encoding = "utf-8")
    assert text.count(SCAN.BLOCK_OPEN) == 1
    assert ds.patch_scan_block(text) == text


def test_scan_dev_runs_the_wrappers_source_under_the_scan_folders_own_python() -> None:
    text   = (ROOT / "Makefile").read_text(encoding = "utf-8")
    recipe = text[text.index("\nscan-dev:"):].split("\n")[2]
    assert recipe == f"\t@{ds.SCAN_PYTHON} -I -S -B scripts/common/kdf_scan.py --repo ."
    ci_line = next(line for line in text.splitlines() if line.startswith("ci: "))
    assert "scan" not in ci_line


def test_the_fixtures_are_never_collected_by_the_unit_lane_and_each_imports() -> None:
    folder = ROOT / "scripts" / "tests" / "fixtures" / "scan"
    names  = sorted(path.name for path in folder.glob("*.py"))
    assert "conftest.py" not in names and not [name for name in names if name.startswith("test_")]
    assert {
        "scanfix.py",
        "fixture_rules.py",
        "fixture_markers.py",
        "fixture_coverage.py",
        "fixture_tampering.py",
        "fixture_repo.py",
        "fixture_tools.py",
    } <= set(names)
    sys.path.insert(0, str(folder))
    try:
        for name in names:
            load(f"scan_fixture_{name.removesuffix('.py')}", folder / name)
    finally:
        sys.path.remove(str(folder))
