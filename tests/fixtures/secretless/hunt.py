"""
The secret hunt behind D-035's proof, run in this repo's own CI on every pull request.

A job that names no secret should hold none. This looks for one where a process that becomes root on a hosted runner
would, in the environment of every process and in the memory of the runner's own processes, Runner.Worker and
Runner.Listener, the technique the tj-actions/changed-files compromise of March 2025 used. It looks for the header of
a private key and for any GitHub token whose sha256 equals the one the fetch job published, never for a value it was
given, and it prints counts and booleans only.

  absent   In the install and test job of ci-python-tests.yml. The probe package was installed from the mirror, the
           tag the fixture pins is in the mirror and nothing private is, then the hunt must find no key and no copy of
           the fetch job's token. It must also find the job's own GITHUB_TOKEN in the runner's memory, otherwise it
           read the wrong memory and an empty result proves nothing.
  present  In the positive control, a job that names the App's secrets and mints a token. The hunt must find the key
           and the token there, otherwise the scanner proves nothing.
  scan     The hunt itself, as root, printing one line of JSON counts.

Standard library only, Python 3.12 or later, the runner's /usr/bin/python3 runs the scan.
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
from pathlib import Path

# ======================================================================================================================
# Configuration
# ======================================================================================================================

PEM_UTF8  = b"PRIVATE KEY-----"
PEM_UTF16 = "PRIVATE KEY-----".encode("utf-16-le")

# a token's known prefix and then every character a token may hold, its length not assumed. GitHub's tokens have
# changed length before, and a run measured on 2026-10-02 found no `ghs_` followed by exactly 36 letters and digits
TOKEN_UTF8  = re.compile(rb"(?<![A-Za-z0-9_])(?:gh[pousr]_|github_pat_)[A-Za-z0-9_.\-]{20,400}")
TOKEN_UTF16 = re.compile(
    rb"(?:g\x00h\x00[pousr]\x00_\x00|g\x00i\x00t\x00h\x00u\x00b\x00_\x00p\x00a\x00t\x00_\x00)(?:[A-Za-z0-9_.\-]\x00){20,400}"
)

SHORTEST_TOKEN = 24

CHUNK   = 8 * 1024 * 1024
OVERLAP = 256

PROBE_REPO = "kriegerdataforge-cicd"
PROBE_URL  = f"https://github.com/Needless2Say/{PROBE_REPO}.git"
PINNED_TAG = "v0.2.99"

# ======================================================================================================================
# The scan
# ======================================================================================================================

def scan_bytes(data: bytes, target: str) -> dict[str, int]:
    """
    The counts in one buffer, private key headers, distinct token shaped runs, and runs that hold the target token.

    A run is a token's prefix and every token character after it. The target is matched against each prefix of a run
    from the shortest token on, so a token found beside more token characters, or of a length not known in advance,
    still matches its sha256.
    """
    candidates = {match.group(0) for match in TOKEN_UTF8.finditer(data)}
    candidates |= {match.group(0).decode("utf-16-le").encode("ascii") for match in TOKEN_UTF16.finditer(data)}
    matches = 0
    if target:
        for candidate in candidates:
            if any(hashlib.sha256(candidate[:end]).hexdigest() == target
                   for end in range(SHORTEST_TOKEN, len(candidate) + 1)):
                matches += 1
    return {
        "pem": data.count(PEM_UTF8) + data.count(PEM_UTF16),
        "tokens": len(candidates),
        "matches": matches,
    }


def _merge(total: dict[str, int], part: dict[str, int]) -> None:
    for key, value in part.items():
        total[key] = total.get(key, 0) + value


def _runner_pids() -> list[int]:
    pids: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            name = (entry / "comm").read_text().strip()
        except OSError:
            continue
        if name.startswith("Runner."):
            pids.append(int(entry.name))
    return pids


def _scan_memory(pid: int, target: str) -> dict[str, int]:
    """
    One process's private memory, anonymous mappings and the heap, where a running program keeps what it was given.
    """
    total = {"pem": 0, "tokens": 0, "matches": 0, "bytes": 0}
    regions: list[tuple[int, int]] = []
    for line in Path(f"/proc/{pid}/maps").read_text().splitlines():
        fields = line.split()
        start, end = (int(part, 16) for part in fields[0].split("-"))
        mapped = fields[5] if len(fields) > 5 else ""
        if fields[1].startswith("r") and (not mapped or mapped == "[heap]" or mapped.startswith("[anon")):
            regions.append((start, end))
    with open(f"/proc/{pid}/mem", "rb", buffering = 0) as memory:
        for start, end in regions:
            offset = start
            while offset < end:
                size = min(CHUNK + OVERLAP, end - offset)
                try:
                    memory.seek(offset)
                    data = memory.read(size)
                except OSError:
                    break
                if not data:
                    break
                _merge(total, scan_bytes(data, target))
                total["bytes"] += len(data)
                offset += CHUNK
    return total


def scan(target: str) -> dict[str, int]:
    """
    Every process's environment, then the runner's memory, as counts.
    """
    result = {"environments": 0, "env_pem": 0, "env_matches": 0, "runners": 0, "bytes": 0, "pem": 0, "tokens": 0,
              "matches": 0}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            environment = (entry / "environ").read_bytes()
        except OSError:
            continue
        found = scan_bytes(environment, target)
        result["environments"] += 1
        result["env_pem"] += found["pem"]
        result["env_matches"] += found["matches"]
    for pid in _runner_pids():
        try:
            _merge(result, _scan_memory(pid, target))
        except OSError:
            continue
        result["runners"] += 1
    return result

# ======================================================================================================================
# The two expectations
# ======================================================================================================================

def _run_scan_as_root(target: str) -> dict[str, int]:
    done = subprocess.run(
        ["sudo", "-n", "/usr/bin/python3", "-I", str(Path(__file__).resolve()), "scan", "--token-sha256", target],
        capture_output = True,
        text = True,
        check = False,
    )
    if done.returncode != 0:
        raise SystemExit(f"the scan as root failed: {done.stderr.strip()[-400:]}")
    return json.loads(done.stdout.strip().splitlines()[-1])


def _check(label: str, passed: bool, failures: list[str]) -> None:
    print(f"  {label}: {'yes' if passed else 'NO'}")
    if not passed:
        failures.append(label)


def expect_absent() -> int:
    """
    The install and test job, no secret here, and the mirrors did their work.
    """
    failures: list[str] = []
    target = os.environ.get("KDF_FETCH_TOKEN_SHA256", "")
    _check("the fetch job published its token's sha256", len(target) == 64, failures)
    manifest = json.loads(Path(os.environ.get("KDF_PRIVATE_MIRRORS", ""), "manifest.json").read_text(encoding = "utf-8"))
    repos = {entry["repo"] for entry in manifest}
    _check("the manifest names only the public stand in", repos == {PROBE_REPO}, failures)
    _check("the commented private pin was not fetched", "kriegerdataforge-fmt" not in repos, failures)
    kinds = {(entry["ref"], entry["kind"]) for entry in manifest}
    _check(f"the tag {PINNED_TAG} was fetched as a tag", (PINNED_TAG, "tag") in kinds, failures)
    _check("the extra repo's branch was resolved to a commit", any(kind == "branch" for _ref, kind in kinds), failures)
    listed = subprocess.run(["git", "ls-remote", PROBE_URL, f"refs/tags/{PINNED_TAG}"], capture_output = True,
                            text = True, check = False)
    _check("git reads the pinned tag through the rewrite to the mirror", f"refs/tags/{PINNED_TAG}" in listed.stdout,
           failures)
    from importlib import metadata
    direct = json.loads(metadata.distribution("kdf-secretless-probe").read_text("direct_url.json") or "{}")
    branch = next((entry for entry in manifest if entry["kind"] == "branch"), {})
    _check("the probe was installed from the https URL", direct.get("url") == PROBE_URL, failures)
    _check("the probe is the commit the fetch job resolved",
           direct.get("vcs_info", {}).get("commit_id") == branch.get("sha"), failures)
    found = _run_scan_as_root(target)
    print(f"  counts: {json.dumps(found, sort_keys = True)}")
    _check("the hunt read the runner's memory", found["runners"] >= 1 and found["bytes"] > 0, failures)
    _check("the hunt found this job's own GITHUB_TOKEN there, so it reads the right memory", found["tokens"] >= 1,
           failures)
    _check("no private key header in any environment or in the runner's memory",
           found["pem"] == 0 and found["env_pem"] == 0, failures)
    _check("no copy of the fetch job's token in any environment or in the runner's memory",
           found["matches"] == 0 and found["env_matches"] == 0, failures)
    return 1 if failures else 0


def expect_present(target: str) -> int:
    """
    The positive control, a job that names the secrets, where the hunt must find them.
    """
    failures: list[str] = []
    _check("the control minted a token", len(target) == 64, failures)
    found = _run_scan_as_root(target)
    print(f"  counts: {json.dumps(found, sort_keys = True)}")
    _check("the hunt read the runner's memory", found["runners"] >= 1 and found["bytes"] > 0, failures)
    _check("the hunt found the private key header in the runner's memory", found["pem"] >= 1, failures)
    _check("the hunt found the minted token in the runner's memory", found["matches"] >= 1, failures)
    return 1 if failures else 0

# ======================================================================================================================
# CLI
# ======================================================================================================================

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description = "Hunt for a secret where root could read one.")
    parser.add_argument("mode", choices = ("absent", "present", "scan"))
    parser.add_argument("--token-sha256", default = "", help = "the sha256 of the token to look for")
    args = parser.parse_args(argv)
    if args.mode == "scan":
        print(json.dumps(scan(args.token_sha256)))
        return 0
    if args.mode == "present":
        return expect_present(args.token_sha256)
    return expect_absent()


if __name__ == "__main__":
    sys.exit(main())
