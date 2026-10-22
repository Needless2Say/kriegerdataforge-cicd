"""
Tampering, design 5.9's fourth part, each refused or changing nothing. The installed folder is written by the owner's
elevated install alone, so these fixtures copy it into their temp folder, change the copy, and run the copy's own
launcher under the copy's own Python, which builds its machine from its own folder. An edited executable, an edited
bundle file and a stray one against the manifest, each refused. A stray rule file and a replacement ref over a rule,
changing nothing, since the rules are read from the pinned commit's raw blobs. SEMGREP_RULES set, changing nothing.
current replaced while a scan runs, held by Windows inside its run, the scan ending on the bundle it began with, row L5.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from scanfix import Machine, git, installed, make_repo, pin, scan

PRINT_RULE = (
    "rules:\n- id: every-print\n  languages: [python]\n  message: a print\n  severity: ERROR\n"
    "  metadata:\n    category: security\n    confidence: HIGH\n  pattern: print(...)\n"
)
# the right OpenProcess grants to hold and release a process
SUSPEND_RESUME = 0x0800


@pytest.fixture(scope = "module")
def copy(tmp_path_factory: pytest.TempPathFactory) -> Machine:
    """
    A copy of the installed folder, its tools, Python, rules, bundles, current and launcher, without staging/ or
    install/.
    """
    machine = installed()
    target  = tmp_path_factory.mktemp("machine") / "scan"
    shutil.copytree(machine.root, target, ignore = shutil.ignore_patterns("staging", "install"))
    return Machine(target, target / machine.python.relative_to(machine.root), machine.bundle)


@pytest.fixture(scope = "module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_repo(tmp_path_factory.mktemp("tamper") / "repo", {"src/app.py": "print(1)\n"})


def test_the_copy_scans_clean_before_any_change(copy: Machine, repo: Path) -> None:
    assert scan(copy, repo).result == "CLEAN"


@pytest.mark.parametrize("part", ["opengrep", "zizmor"])
def test_an_edited_executable_is_refused(copy: Machine, repo: Path, part: str) -> None:
    found = sorted((copy.root / part).rglob(f"{part}.exe"))
    assert found, part
    original = found[0].read_bytes()
    try:
        found[0].write_bytes(original + b"\0")
        result = scan(copy, repo)
        assert result.result == "REFUSED" and result.last["code"] == "2", result.text
        assert part in result.text
    finally:
        found[0].write_bytes(original)


def test_an_edited_bundle_file_and_a_stray_one_are_refused_by_the_manifest(copy: Machine, repo: Path) -> None:
    bundle   = copy.root / "bundles" / copy.bundle
    config   = bundle / "kdf_zizmor.yml"
    original = config.read_bytes()
    try:
        config.write_bytes(original + b"# changed\n")
        result = scan(copy, repo)
        assert result.result == "REFUSED" and "differs from its manifest" in result.text, result.text
    finally:
        config.write_bytes(original)
    stray = bundle / "scan_rules" / "stray.yaml"
    try:
        stray.write_text(PRINT_RULE, encoding = "utf-8")
        result = scan(copy, repo)
        assert result.result == "REFUSED" and "differs from its manifest" in result.text, result.text
    finally:
        stray.unlink()


def test_a_stray_rule_file_in_the_rules_clone_changes_nothing(copy: Machine, repo: Path) -> None:
    folder = copy.root / "rules" / "semgrep-rules.git" / "python" / "lang" / "security"
    folder.mkdir(parents = True, exist_ok = True)
    try:
        (folder / "every-print.yaml").write_text(PRINT_RULE, encoding = "utf-8")
        assert scan(copy, repo).result == "CLEAN"
    finally:
        shutil.rmtree(copy.root / "rules" / "semgrep-rules.git" / "python")


def test_a_replacement_ref_over_a_rule_changes_nothing(copy: Machine, repo: Path) -> None:
    rules  = copy.root / "rules" / "semgrep-rules.git"
    listed = git(rules, "ls-tree", "-r", pin(copy, "RULES_COMMIT"), "--", "python/lang/security").splitlines()
    blob   = next(line.split()[2] for line in listed if line.split("\t")[-1].endswith(".yaml"))
    source = copy.root.parent / "print-rule.yaml"
    source.write_text(PRINT_RULE, encoding = "utf-8")
    swap = git(rules, "hash-object", "-w", str(source))
    git(rules, "replace", blob, swap)
    try:
        assert scan(copy, repo).result == "CLEAN"
    finally:
        git(rules, "replace", "-d", blob)


def test_semgrep_rules_in_the_environment_changes_nothing(repo: Path, tmp_path: Path) -> None:
    rule = tmp_path / "every-print.yaml"
    rule.write_text(PRINT_RULE, encoding = "utf-8")
    result = scan(installed(), repo, env = {**os.environ, "SEMGREP_RULES": str(rule)})
    assert result.result == "CLEAN", result.text


@contextlib.contextmanager
def held(pid: int) -> Iterator[None]:
    """
    The process stopped by Windows until the block ends, so it cannot pass the point where it was held. Its children
    run on, and their answers wait for it.
    """
    kernel                          = ctypes.WinDLL("kernel32", use_last_error = True)
    ntdll                           = ctypes.WinDLL("ntdll")
    kernel.OpenProcess.restype      = ctypes.c_void_p
    kernel.OpenProcess.argtypes     = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel.CloseHandle.argtypes     = (ctypes.c_void_p,)
    ntdll.NtSuspendProcess.argtypes = (ctypes.c_void_p,)
    ntdll.NtResumeProcess.argtypes  = (ctypes.c_void_p,)
    handle                          = kernel.OpenProcess(SUSPEND_RESUME, False, pid)
    assert handle, f"the scan's process could not be opened, error {ctypes.get_last_error()}"
    try:
        assert ntdll.NtSuspendProcess(handle) == 0, "the scan's process could not be held"
        try:
            yield
        finally:
            ntdll.NtResumeProcess(handle)
    finally:
        kernel.CloseHandle(handle)


def scanning(temp: Path, running: subprocess.Popen[bytes]) -> Path:
    """
    The wrapper's run folder once its tools' temp folder is there, made after the launcher read current and checked the
    bundle, and the wrapper checked the pins and the rules, just before Opengrep starts.
    """
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline and running.poll() is None:
        for work in temp.glob("kdf-scan-*"):
            if (work / "temp").is_dir():
                return work
        time.sleep(0.01)
    pytest.fail("the scan ended or stalled before its tools started, so no replacement could fall inside it")


def test_current_replaced_while_a_scan_runs_leaves_the_scan_on_its_own_bundle(
    copy: Machine,
    repo: Path,
    tmp_path: Path,
) -> None:
    # the scan is held inside its run, Opengrep started and its answer unread, while current changes, so a launcher
    # that read current again later would name the replacement, timing no part of it
    current  = copy.root / "current"
    original = current.read_text(encoding = "ascii")
    temp     = tmp_path / "temp"
    temp.mkdir()
    command = [str(copy.python), "-I", "-S", "-B", str(copy.launcher), "--repo", str(repo)]
    running = subprocess.Popen(
        command,
        cwd = repo,
        env = {**os.environ, "TMPDIR": str(temp), "TEMP": str(temp), "TMP": str(temp)},
        stdout = subprocess.PIPE,
        stderr = subprocess.STDOUT,
    )
    try:
        work = scanning(temp, running)
        with held(running.pid):
            inside = running.poll() is None and (work / "temp").is_dir() and not (work / "opengrep.json").exists()
            assert inside, "the scan read Opengrep's answer before it was held, so the replacement fell outside it"
            current.write_text("e" * 40 + "\n", encoding = "ascii")
        output, _ = running.communicate(timeout = 900)
    finally:
        current.write_text(original, encoding = "ascii")
        if running.poll() is None:
            running.kill()
    last = output.decode("utf-8", "replace").rstrip("\n").splitlines()[-1]
    assert f"bundle {copy.bundle[:12]}" in last and last.endswith("CLEAN (exit 0)"), last
