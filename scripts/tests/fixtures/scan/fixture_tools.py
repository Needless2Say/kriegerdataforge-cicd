"""
The installed tools run directly, design 5.9's last parts and the side agent's note of 2026-10-21. Opengrep runs twice,
each with a temp folder of its own, and the fixture records where it unpacks and whether the second run reuses anything
outside its own temp folder, which stops the build if it does. Each tool runs with every proxy variable pointed at a
closed port and finishes. Two parts need the owner's hand and run only when asked. KDF_SCAN_OFFLINE=1 under the
owner's outbound firewall rule on the two executables, where a registry fetch must fail first as the control.
KDF_SCAN_WRITE_PROBE=1, an unelevated try at a file in the scan folder, which Windows must refuse, removed at once if it
does not. The elevated window's refusal of `--check` is the owner's own, plan owner step 2.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
from scanfix import Machine, installed, lines, pin

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


def opengrep(machine: Machine) -> Path:
    return machine.root / "opengrep" / pin(machine, "OPENGREP_VERSION") / "opengrep.exe"


def zizmor(machine: Machine) -> Path:
    return machine.root / "zizmor" / pin(machine, "ZIZMOR_VERSION") / "Scripts" / "zizmor.exe"


def environment(temp: Path, **extra: str) -> dict[str, str]:
    """
    The scanners' environment as the wrapper builds it, its own temp folder and nothing else of the session's.
    """
    system = os.environ.get("SYSTEMROOT", "C:\\Windows")
    return {
        "SYSTEMROOT": system,
        "PATH": os.pathsep.join([str(Path(system) / "System32"), system]),
        "TEMP": str(temp),
        "TMP": str(temp),
        "USERPROFILE": os.environ.get("USERPROFILE", str(temp)),
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


def watched() -> dict[str, set[str]]:
    """
    The top level of each place a single file executable could unpack to or cache in, outside a run's own temp.
    """
    profile = Path(os.environ.get("USERPROFILE", "."))
    places  = {
        "TEMP": Path(os.environ.get("TEMP", profile)),
        "LOCALAPPDATA": Path(os.environ.get("LOCALAPPDATA", profile)),
        "APPDATA": Path(os.environ.get("APPDATA", profile)),
        "~/.cache": profile / ".cache",
        "~/.semgrep": profile / ".semgrep",
        "~/.opengrep": profile / ".opengrep",
    }
    return {
        name: {entry.name for entry in place.iterdir()} if place.is_dir() else set() for name, place in places.items()
    }


def listing(folder: Path) -> list[str]:
    return sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*")) if folder.is_dir() else []


def test_opengrep_twice_unpacks_into_its_own_temp_and_reuses_nothing_outside_it(tmp_path: Path) -> None:
    machine = installed()
    before  = watched()
    first   = run_opengrep(machine, tmp_path / "one", tmp_path / "temp-one")
    middle  = watched()
    second  = run_opengrep(machine, tmp_path / "two", tmp_path / "temp-two")
    after   = watched()
    assert first.returncode == 0 and second.returncode == 0, (first.stderr, second.stderr)
    for name in before:
        print(f"FIXTURE-NOTE opengrep first run added to {name}: {sorted(middle[name] - before[name])}")
        print(f"FIXTURE-NOTE opengrep second run added to {name}: {sorted(after[name] - middle[name])}")
    print(f"FIXTURE-NOTE opengrep first run's own temp: {listing(tmp_path / 'temp-one')[:20]}")
    print(f"FIXTURE-NOTE opengrep second run's own temp: {listing(tmp_path / 'temp-two')[:20]}")
    print(f"FIXTURE-NOTE ~/.semgrep after: {sorted(after['~/.semgrep'])}")
    outside = {
        name: sorted(entry for entry in after[name] - before[name] if TOOLISH.search(entry))
        for name in before if name != "~/.semgrep"
    }
    assert not any(outside.values()), f"Opengrep left files outside its run's temp, {outside}"


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
