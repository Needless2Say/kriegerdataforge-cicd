"""
The installed tools run directly, design 5.9's last parts and the side agent's note of 2026-10-21. Opengrep runs as the
wrapper runs it, a temp folder and a profile of its own, its temp watched while it runs, then again with a temp folder
already holding a poisoned file at every path the first run used, and the second run must find what the first found,
while nothing of a scanner's outside the run changes, by size or time. A scan through the installed launcher leaves
the session's profile as it was, where Opengrep unpacked its engine and Python before Round Table 59, the check shown
to fire on a stand in profile given to Opengrep as the wrapper once gave the real one. A folder a tool finds through
Windows rather than its environment, and reads without writing, is beyond a fixture, a process monitor's question.
Each tool runs with every proxy variable pointed at a closed port and finishes. Two parts
need the owner's hand and run only when asked. KDF_SCAN_OFFLINE=1 under the owner's outbound firewall rule on the two
executables, where a registry fetch must fail first as the control. KDF_SCAN_WRITE_PROBE=1, an unelevated try at a file
in the scan folder, which Windows must refuse, removed at once if it does not. The elevated window's refusal of
`--check` is the owner's own, plan owner step 2.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from scanfix import Machine, installed, lines, make_repo, pin, scan

PRINT_RULE = (
    "rules:\n- id: every-print\n  languages: [python]\n  message: a print\n  severity: ERROR\n"
    "  metadata:\n    category: security\n    confidence: HIGH\n  pattern: print(...)\n"
)
WORKFLOW   = lines(
    "name: tiny",
    "on: push",
    "permissions: {}",
    "jobs:",
    "  build:",
    "    runs-on: ubuntu-latest",
    "    steps:",
    "      - run: true",
)
PROXIES    = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
TOOLISH    = re.compile(r"(?i)opengrep|semgrep|_MEI|ocaml")
# bytes no loader, YAML reader or rule parser accepts
POISON = b"\0KDF poisoned, never load this\xff\xfe\0"


def opengrep(machine: Machine) -> Path:
    return machine.root / "opengrep" / pin(machine, "OPENGREP_VERSION") / "opengrep.exe"


def zizmor(machine: Machine) -> Path:
    return machine.root / "zizmor" / pin(machine, "ZIZMOR_VERSION") / "Scripts" / "zizmor.exe"


def environment(temp: Path, **extra: str) -> dict[str, str]:
    """
    The scanners' environment as the wrapper builds it, its own temp folder and profile and nothing of the session's.
    """
    profile = temp.parent / f"{temp.name}-profile"
    (profile / "AppData" / "Local").mkdir(parents = True, exist_ok = True)
    return {
        "SYSTEMROOT": "C:\\Windows",
        "PATH": os.pathsep.join(["C:\\Windows\\System32", "C:\\Windows"]),
        "TEMP": str(temp),
        "TMP": str(temp),
        "USERPROFILE": str(profile),
        "PYTHONUTF8": "1",
        "NO_COLOR": "1",
        **extra,
    }


def tiny(folder: Path) -> tuple[Path, Path]:
    rules  = folder / "rules"
    target = folder / "tree"
    rules.mkdir(parents = True)
    target.mkdir(parents = True)
    (rules / "every-print.yaml").write_text(PRINT_RULE, encoding = "utf-8")
    (target / "app.py").write_text("print(1)\n", encoding = "utf-8")
    return rules, target


def run_opengrep(machine: Machine, folder: Path, temp: Path, **extra: str) -> subprocess.CompletedProcess[bytes]:
    rules, target = tiny(folder)
    command = [
        str(opengrep(machine)),
        "scan",
        "--config",
        str(rules),
        "--taint-intrafile",
        "--disable-nosem",
        "--disable-version-check",
        "--json",
        "--output",
        str(folder / "out.json"),
        "--timeout",
        "5",
        str(target),
    ]
    temp.mkdir(parents = True, exist_ok = True)
    return subprocess.run(
        command,
        env = environment(temp, **extra),
        capture_output = True,
        timeout = 600,
        check = False,
    )


def places(profile: Path | None = None) -> dict[str, Path]:
    """
    Each place outside a run's own temp where a single file executable could unpack to or cache in, the session's, or
    a stand in profile's own places when one is named.
    """
    if profile is not None:
        return {
            "LOCALAPPDATA": profile / "AppData" / "Local",
            "APPDATA": profile / "AppData" / "Roaming",
            "~/.cache": profile / ".cache",
            "~/.semgrep": profile / ".semgrep",
            "~/.opengrep": profile / ".opengrep",
        }
    profile = Path(os.environ.get("USERPROFILE", "."))
    return {
        "TEMP": Path(os.environ.get("TEMP", profile)),
        "LOCALAPPDATA": Path(os.environ.get("LOCALAPPDATA", profile)),
        "APPDATA": Path(os.environ.get("APPDATA", profile)),
        "~/.cache": profile / ".cache",
        "~/.semgrep": profile / ".semgrep",
        "~/.opengrep": profile / ".opengrep",
    }


def files(folder: Path) -> dict[str, int]:
    """
    Every file under a folder with its size, a file that goes while it is read passed over.
    """
    found: dict[str, int] = {}
    for top, _dirs, names in os.walk(folder):
        for name in names:
            path = Path(top) / name
            with contextlib.suppress(OSError):
                found[path.relative_to(folder).as_posix()] = path.stat().st_size
    return found


def outside(profile: Path | None = None) -> dict[str, tuple[int, int]]:
    """
    Every file under each place's entries a scanner could own, a tool's name at the top or anything in its own dot
    folder, with its size and time, so a change inside an old cache shows as plainly as a new one.
    """
    found: dict[str, tuple[int, int]] = {}
    for name, place in places(profile).items():
        entries = sorted(place.iterdir()) if place.is_dir() else []
        for entry in entries:
            if not (name in ("~/.semgrep", "~/.opengrep") or TOOLISH.search(entry.name)):
                continue
            walked = [entry] if entry.is_file() else [
                Path(top) / file for top, _dirs, names in os.walk(entry) for file in names
            ]
            for path in walked:
                with contextlib.suppress(OSError):
                    stat = path.stat()
                    found[f"{name}/{path.relative_to(place).as_posix()}"] = (stat.st_size, stat.st_mtime_ns)
    return found


@contextlib.contextmanager
def watching(folder: Path) -> Iterator[dict[str, int]]:
    """
    Every file seen under a folder while the block runs, read every few milliseconds, since an unpacked file may live
    only while its program does.
    """
    seen: dict[str, int] = {}
    done = threading.Event()


    def poll() -> None:
        while not done.is_set():
            seen.update(files(folder))
            time.sleep(0.02)


    folder.mkdir(parents = True, exist_ok = True)
    thread = threading.Thread(target = poll, daemon = True)
    thread.start()
    try:
        yield seen
    finally:
        done.set()
        thread.join()
        seen.update(files(folder))


def poison(folder: Path, seen: dict[str, int]) -> None:
    """
    A file at each path seen, of at least its size, holding bytes no program, rule or setting could load, so a run
    that read any of them fails or finds otherwise.
    """
    for name, size in seen.items():
        path = folder / name
        path.parent.mkdir(parents = True, exist_ok = True)
        path.write_bytes((POISON * (size // len(POISON) + 1))[:max(size, len(POISON))])


def findings(folder: Path) -> list[tuple[str, str, int]]:
    # a check id begins with its rule folder's path, which differs between two runs, so its last part names the rule
    results = json.loads((folder / "out.json").read_text(encoding = "utf-8"))["results"]
    return sorted(
        (item["check_id"].rsplit(".", 1)[-1], Path(item["path"]).name, item["start"]["line"]) for item in results
    )


def test_opengrep_reuses_nothing_it_unpacked_or_left_in_a_temp_folder(tmp_path: Path) -> None:
    # run as the wrapper runs it, its own temp watched while it runs, then again with a temp folder already holding a
    # poisoned file at every path the first run used, where a cache found by its name would be read
    machine = installed()
    before  = outside()
    with watching(tmp_path / "temp-one") as seen:
        first = run_opengrep(machine, tmp_path / "one", tmp_path / "temp-one")
    assert first.returncode == 0, first.stderr
    print(f"FIXTURE-NOTE opengrep's own temp while it ran: {sorted(seen)[:40]}")
    poison(tmp_path / "temp-two", seen)
    second = run_opengrep(machine, tmp_path / "two", tmp_path / "temp-two")
    assert second.returncode == 0, f"a poisoned temp folder broke Opengrep, so it reads what it finds there, {second}"
    assert findings(tmp_path / "two") == findings(tmp_path / "one") != []
    changed = sorted(set(outside().items()) ^ set(before.items()))
    assert not changed, f"Opengrep changed files outside its run's temp, {changed}"


def test_a_scan_leaves_the_sessions_profile_as_it_was(tmp_path: Path) -> None:
    # the installed launcher scans with a profile of the run's own, so nothing under the session's profile changes,
    # Round Table 59's L8 and L13
    machine = installed()
    repo    = make_repo(tmp_path / "repo", {"src/app.py": "print(1)\n"})
    before  = outside()
    result  = scan(machine, repo)
    assert result.result == "CLEAN", result.text
    changed = sorted(set(outside().items()) ^ set(before.items()))
    assert not changed, f"a scan changed files under the session's profile, {changed[:10]}"
    # the negative control, Opengrep given a stand in for the session's profile as the wrapper once gave the real one,
    # which the same reading finds changed
    stand_in = tmp_path / "session-profile"
    (stand_in / "AppData" / "Local").mkdir(parents = True)
    control = outside(stand_in)
    done    = run_opengrep(machine, tmp_path / "control", tmp_path / "temp-control", USERPROFILE = str(stand_in))
    assert done.returncode == 0, done.stderr
    assert set(outside(stand_in).items()) != set(control.items()), "the reading cannot see Opengrep's unpack"


def test_each_tool_finishes_with_every_proxy_pointed_at_a_closed_port(tmp_path: Path) -> None:
    machine = installed()
    closed  = dict.fromkeys(PROXIES, "http://127.0.0.1:9")
    done    = run_opengrep(machine, tmp_path / "opengrep", tmp_path / "temp-opengrep", **closed)
    assert done.returncode == 0, done.stderr
    assert json.loads((tmp_path / "opengrep" / "out.json").read_text(encoding = "utf-8"))["results"]
    workflows = tmp_path / "workflows" / ".github" / "workflows"
    workflows.mkdir(parents = True)
    (workflows / "tiny.yml").write_text(WORKFLOW, encoding = "utf-8")
    config  = machine.root / "bundles" / machine.bundle / "kdf_zizmor.yml"
    command = [
        str(zizmor(machine)),
        "--offline",
        "--no-ignores",
        "--min-severity",
        "medium",
        "--min-confidence",
        "medium",
        "--format",
        "json",
        "--config",
        str(config),
        ".",
    ]
    (tmp_path / "temp-zizmor").mkdir()
    done = subprocess.run(
        command,
        cwd = tmp_path / "workflows",
        env = environment(tmp_path / "temp-zizmor", **closed),
        capture_output = True,
        timeout = 600,
        check = False,
    )
    assert done.returncode in (0, 10, 11, 12, 13, 14), done.stderr
    json.loads(done.stdout.decode("utf-8") or "[]")


@pytest.mark.skipif(os.environ.get("KDF_SCAN_OFFLINE") != "1", reason = "the owner's firewall rule, KDF_SCAN_OFFLINE=1")
def test_under_the_owners_firewall_rule_a_registry_fetch_fails_as_the_control(tmp_path: Path) -> None:
    machine = installed()
    _rules, target = tiny(tmp_path / "control")
    (tmp_path / "temp").mkdir()
    command = [str(opengrep(machine)), "scan", "--config", "p/python", "--disable-version-check", "--json", str(target)]
    done    = subprocess.run(
        command,
        env = environment(tmp_path / "temp"),
        capture_output = True,
        timeout = 600,
        check = False,
    )
    assert done.returncode != 0, "Opengrep reached the registry, so the firewall rule does not hold"


@pytest.mark.skipif(
    os.environ.get("KDF_SCAN_WRITE_PROBE") != "1",
    reason = "asked of the owner, KDF_SCAN_WRITE_PROBE=1",
)
def test_an_unelevated_process_cannot_write_into_the_scan_folder() -> None:
    machine = installed()
    probe   = machine.root / f"write-probe-{os.getpid()}"
    try:
        with open(probe, "x", encoding = "ascii") as handle:
            handle.write("a probe\n")
    except PermissionError:
        return
    probe.unlink()
    pytest.fail(f"an unelevated process wrote {probe}, so the fence does not hold, the build stops")
