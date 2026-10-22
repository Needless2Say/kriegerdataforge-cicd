"""
Tests for kdf-scan-install.sh, the owner's install of the local code scan (D-084, design 5.3).

Each test runs the script as it ships, with bash -p from the folder it was fetched into, against a scan folder, a cicd
remote and artifacts of the test's own, through --programs, whose folder holds the stand ins. whoami, cygpath, reg,
icacls and aclcheck, the launcher's reader of owners, are stand ins reading their scenario from files beside them.
git, curl, tar and sha256sum are the real programs behind a wrapper that logs each call, since only the real ones show
what configuration they load, and cosign is a stand in served through the pins as the real one is. The fake cicd holds
this script, the real wrapper and launcher, kdf_scan.py's pins pointed at the artifacts by file:// addresses. An input
the real program always acts on, a BASH_ENV, a PATH, a .gitconfig, a .curlrc or GIT_TRACE, is first shown to fire
without the clean room, then shown to reach no run of the install. The tests need bash, git and curl.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path

import pytest
from tests.scan_fakes import COMMON, GIT, PYTHON, commit, git, init_repo, load, platform

ROOT    = Path(__file__).resolve().parents[2]
SCRIPT  = ROOT / "tools" / "claude-code" / "kdf-scan-install.sh"
WINDOWS = sys.platform == "win32"
SCAN    = load("kdf_scan_for_install", COMMON / "kdf_scan.py")
# the bash, curl and git of Git for Windows where they are, else the ones PATH names
BASH_PATHS = ("C:/Program Files/Git/usr/bin/bash.exe", shutil.which("bash"))
CURL_PATHS = ("C:/Program Files/Git/mingw64/bin/curl.exe", shutil.which("curl"))
GIT_PATHS  = ("C:/Program Files/Git/mingw64/bin/git.exe", GIT)
BASH       = next((path for path in BASH_PATHS if path and Path(path).is_file()), None)
CURL       = next((path for path in CURL_PATHS if path and Path(path).is_file()), None)
REAL_GIT   = next((path for path in GIT_PATHS if path and Path(path).is_file()), None)
IDENTITY   = SCAN.OPENGREP_IDENTITY
UV_URL     = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/20260929/"
    "cpython-3.14.7%2B20260929-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
)

# the stand ins, each logging its call and reading its scenario from a file beside it, built from builtins and the
# coreutils by full path, so a hostile PATH reaches none of them, and run with bash -p, so a BASH_ENV reaches none as
# it reaches none of the Windows programs they stand in for
HEADER = r"""#!/usr/bin/bash -p
here="${BASH_SOURCE[0]%/*}"
scenario() { [ -f "$here/scenario/$1" ] && printf '%s' "$(< "$here/scenario/$1")"; }
printf '%s %s\n' "${BASH_SOURCE[0]##*/}" "$*" >> "$here/calls.log"
"""

WHOAMI = HEADER + r"""
case "${1:-}" in
    /groups)
        level="$(scenario level)" || level=12288
        printf '"Mandatory Label\\High Mandatory Level","Label","S-1-16-%s",""\r\n' "$level" ;;
    *)
        account="$(scenario account)" || account='MACHINE\kdf-install'
        printf '%s\r\n' "$account" ;;
esac
"""

CYGPATH = HEADER + r"""
[ "$1" = -w ] && [ "$2" = / ] || exit 1
answer="$(scenario root)" || answer='C:\Program Files\Git\'
printf '%s\n' "$answer"
"""

REG = HEADER + r"""
name="$4"
value="$(scenario "$name")" || {
    printf '\r\nERROR: The system was unable to find the specified registry key or value.\r\n'
    exit 1
}
read -r kind data <<< "$value"
printf '\r\nHKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System\r\n'
printf '    %s    %s    %s\r\n\r\n' "$name" "$kind" "$data"
"""

ICACLS = HEADER + r"""
target="${1//\\//}"
case "$2" in
    /save)
        file="${3//\\//}"
        saves=0
        [ ! -f "$here/state.saves" ] || saves="$(< "$here/state.saves")"
        saves=$((saves + 1))
        printf '%s' "$saves" > "$here/state.saves"
        extra=""
        [ "$(scenario fourth_grant_on_save)" != "$saves" ] || extra='(A;ID;FA;;;S-1-5-21-1-2-3-1001)'
        flags=PAI
        [ -z "$(scenario unprotected)" ] || flags=AI
        parent="${target%/*}"
        out=""
        while IFS= read -r -d '' path; do
            name="${path#"$parent"/}"
            name="${name//\//\\}"
            if [ "$path" = "$target" ]; then
                sddl="D:$flags(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)(A;OICI;0x1200a9;;;BU)"
            elif [ -d "$path" ]; then
                sddl="D:AI(A;OICIID;FA;;;BA)(A;OICIID;FA;;;SY)(A;OICIID;0x1200a9;;;BU)$extra"
            else
                sddl="D:AI(A;ID;FA;;;BA)(A;ID;FA;;;SY)(A;ID;0x1200a9;;;BU)$extra"
            fi
            out+="$name"$'\r\n'"$sddl"$'\r\n'
        done < <(/usr/bin/find "$target" -print0)
        printf '%s' "$out" | /usr/bin/iconv -f UTF-8 -t UTF-16LE > "$file" ;;
    /setowner)
        if [ "$(scenario kill_on_setowner)" = yes ] && [[ "$target" == */bundles/* ]]; then
            kill -9 "$PPID"
        fi ;;
esac
"""

ACLCHECK = HEADER + r"""
reads=0
[ ! -f "$here/state.reads" ] || reads="$(< "$here/state.reads")"
reads=$((reads + 1))
printf '%s' "$reads" > "$here/state.reads"
if [ -n "$(scenario damage_python)" ] && [ "$reads" -gt 1 ]; then
    printf 'damage\n' >> "$2/python/3.14.7/Lib/os.py"
fi
problem="$(scenario acl_problem)" || exit 0
on="$(scenario acl_problem_on)" || on="$reads"
[ "$on" = "$reads" ] || exit 0
printf '%s\n' "$problem"
exit 1
"""

WRAPPER = r"""#!/usr/bin/bash
printf '%s %s\n' "{name}" "$*" >> "{log}"
{before}exec "{real}" "$@"
"""

BLOCK = r"""if [ -f "{scenario}/block" ]; then
    tries=0
    while [ ! -f "{scenario}/release" ] && [ "$tries" -lt 1200 ]; do
        /usr/bin/sleep 0.1
        tries=$((tries + 1))
    done
fi
"""

COSIGN = r"""#!/usr/bin/bash
printf 'cosign %s HOME=%s USERPROFILE=%s TUF_ROOT=%s\n' "$*" "${{HOME:-}}" "${{USERPROFILE:-}}" "${{TUF_ROOT:-}}" \
    >> "{log}"
if [ -f "{scenario}/bad_signature" ]; then
    echo "Error: invalid signature when validating ASN.1 encoded signature" >&2
    exit 1
fi
signed_by="{identity}"
[ ! -f "{scenario}/signed_by" ] || signed_by="$(< "{scenario}/signed_by")"
identity="" issuer=""
while [ $# -gt 0 ]; do
    case "$1" in
        --certificate-identity) identity="$2"; shift 2 ;;
        --certificate-oidc-issuer) issuer="$2"; shift 2 ;;
        *) shift ;;
    esac
done
if [ "$identity" != "$signed_by" ] || [ "$issuer" != "https://token.actions.githubusercontent.com" ]; then
    echo "Error: none of the expected identities matched what was in the certificate" >&2
    exit 1
fi
echo "Verified OK" >&2
"""

HOSTILE = r"""#!/usr/bin/bash
printf '%s\n' "${{BASH_SOURCE[0]##*/}}" >> "{marker}"
exit 1
"""

# the names a script that trusted PATH would run, each planted where a hostile PATH puts it first
PLANTED = (
    "awk",
    "bash",
    "cat",
    "cp",
    "curl",
    "cygpath",
    "date",
    "env",
    "find",
    "gh",
    "git",
    "icacls",
    "iconv",
    "id",
    "mkdir",
    "mktemp",
    "mv",
    "python",
    "python3",
    "reg",
    "rm",
    "sed",
    "sha256sum",
    "sleep",
    "sort",
    "tar",
    "uv",
    "whoami",
    "xargs",
)

pytestmark = pytest.mark.skipif(
    not (BASH and CURL and REAL_GIT and GIT),
    reason = "the install's tests need bash, git and curl",
)


def file_url(path: Path) -> str:
    return "file:///" + path.as_posix().lstrip("/")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def program(path: Path, text: str) -> Path:
    path.parent.mkdir(parents = True, exist_ok = True)
    path.write_text(text, encoding = "utf-8", newline = "\n")
    path.chmod(0o755)
    return path


def set_pin(text: str, name: str, value: str) -> str:
    """
    One pin of kdf_scan.py given a plain value, a parenthesised assignment replaced whole.
    """
    lines, out, index, done = text.split("\n"), [], 0, False
    while index < len(lines):
        line = lines[index]
        if re.match(rf"{name} +=", line):
            assert not done, name
            done = True
            if line.rstrip().endswith("("):
                while lines[index].strip() != ")":
                    index += 1
            out.append(f'{name} = "{value}"')
        else:
            out.append(line)
        index += 1
    assert done, name
    return "\n".join(out)


def base_environment() -> dict[str, str]:
    drop = ("BASH_ENV", "ENV", "CDPATH", "GLOBIGNORE", "SHELLOPTS", "BASHOPTS", "CURL_HOME", "XDG_CONFIG_HOME")
    return {
        key: value for key, value in os.environ.items()
        if key not in drop and not key.startswith(("BASH_FUNC_", "GIT_"))
    }


@dataclass
class Rig:
    """
    A scan folder holding only install/, a fake cicd, artifacts served by file:// and the stand ins' folder.
    """
    base:      Path
    programs:  Path
    root:      Path
    profile:   Path
    temp:      Path
    source:    Path
    artifacts: Path
    commit:    str
    pins:      dict


    def script_for(self, at_commit: str) -> Path:
        folder = self.root / "install" / at_commit
        folder.mkdir(parents = True, exist_ok = True)
        target = folder / "kdf-scan-install.sh"
        if not target.exists():
            target.write_bytes(git_bytes(self.source, f"{at_commit}:tools/claude-code/kdf-scan-install.sh"))
        return target


    def command(self, at_commit: str | None = None, privileged: bool = True) -> list[str]:
        at_commit = at_commit or self.commit
        return [
            BASH,
            *(["-p"] if privileged else []),
            self.script_for(at_commit).as_posix(),
            at_commit,
            "--programs",
            self.programs.as_posix(),
            "--root",
            self.root.as_posix(),
            "--cicd",
            file_url(self.source),
        ]


    def environment(self, **changes: str) -> dict[str, str]:
        environment = base_environment()
        environment.update({
            "USERPROFILE": self.profile.as_posix(),
            "HOME": self.profile.as_posix(),
            "TEMP": self.temp.as_posix(),
            "TMP": self.temp.as_posix(),
        })
        environment.update(changes)
        return environment


    def run(self, at_commit: str | None = None, privileged: bool = True, **changes: str) -> tuple[int, str]:
        done = subprocess.run(
            self.command(at_commit, privileged),
            stdout = subprocess.PIPE,
            stderr = subprocess.STDOUT,
            text = True,
            env = self.environment(**changes),
            timeout = 600,
            check = False,
        )
        return done.returncode, done.stdout


    def scenario(self, name: str, value: str = "yes") -> None:
        (self.programs / "scenario").mkdir(exist_ok = True)
        (self.programs / "scenario" / name).write_text(value, encoding = "utf-8", newline = "\n")


    def clear(self, name: str) -> None:
        (self.programs / "scenario" / name).unlink(missing_ok = True)


    def calls(self, name: str | None = None) -> list[str]:
        log   = self.programs / "calls.log"
        lines = log.read_text(encoding = "utf-8").splitlines() if log.exists() else []
        return [line for line in lines if name is None or line.split(" ", 1)[0] == name]


    def forget_calls(self) -> None:
        """
        The calls logged so far forgotten, and the stand ins' counts of their reads and saves begun again.
        """
        for name in ("calls.log", "state.reads", "state.saves"):
            (self.programs / name).unlink(missing_ok = True)


    def new_commit(self, files: dict[str, str | bytes], message: str = "change") -> str:
        return commit(self.source, files, message)


def git_bytes(repo: Path, spec: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", spec],
        check = True,
        capture_output = True,
    ).stdout


def build_artifacts(folder: Path, programs: Path) -> dict[str, str]:
    """
    The artifacts the pins name, a Python whose python.exe runs this interpreter, cosign, Opengrep with its .cert and
    .sig, zizmor's wheel and the licence page, and the pins that name them.
    """
    folder.mkdir(parents = True)
    real    = PYTHON.as_posix()
    archive = folder / "python.tar.gz"
    members = {
        "python/python.exe": (f'#!/bin/sh\nexec "{real}" "$@"\n'.encode(), 0o755),
        "python/Lib/os.py": (b"# os stand in\n", 0o644),
        "python/DLLs/_ssl.pyd": (b"pyd stand in\n", 0o644),
    }
    with tarfile.open(archive, "w:gz") as tar:
        for name in ("python", "python/Lib", "python/DLLs"):
            info = tarfile.TarInfo(name)
            info.type, info.mode = tarfile.DIRTYPE, 0o755
            tar.addfile(info)
        for name, (data, mode) in members.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))
    data  = archive.read_bytes()
    named = f"cpython-3.14.7{{}}20260929-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
    (folder / "archives" / "20260929").mkdir(parents = True)
    for plus in ("+", "%2B"):
        (folder / "archives" / "20260929" / named.format(plus)).write_bytes(data)
    cosign   = program(
        folder / "cosign.exe",
        COSIGN.format(
            log = (programs / "calls.log").as_posix(),
            scenario = (programs / "scenario").as_posix(),
            identity = IDENTITY,
        ),
    )
    opengrep = folder / "opengrep_windows_x86.exe"
    opengrep.write_bytes(b"MZ opengrep stand in\n")
    (folder / "opengrep_windows_x86.exe.cert").write_bytes(b"LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0t\n")
    (folder / "opengrep_windows_x86.exe.sig").write_bytes(b"MEUCIQD stand in\n")
    zizmor = b"MZ zizmor stand in\n"
    wheel  = folder / "zizmor.whl"
    with zipfile.ZipFile(wheel, "w") as archive_file:
        archive_file.writestr("zizmor-1.30.1.data/scripts/zizmor.exe", zizmor)
        archive_file.writestr("zizmor-1.30.1.dist-info/METADATA", "Name: zizmor\n")
    (folder / "licence.html").write_text("<html>the rules' licence</html>\n", encoding = "utf-8")
    return {
        "PYTHON_ARCHIVE_BASE": file_url(folder / "archives"),
        "PYTHON_ARCHIVE_SHA256": sha(data),
        "COSIGN_URL": file_url(cosign),
        "COSIGN_SHA256": sha(cosign.read_bytes()),
        "OPENGREP_URL": file_url(opengrep),
        "OPENGREP_SHA256": sha(opengrep.read_bytes()),
        "ZIZMOR_WHEEL_URL": file_url(wheel),
        "ZIZMOR_WHEEL_SHA256": sha(wheel.read_bytes()),
        "ZIZMOR_SHA256": sha(zizmor),
        "RULES_LICENSE_URL": file_url(folder / "licence.html"),
    }


def build_rules(base: Path) -> dict[str, str]:
    source       = init_repo(base / "rules-src")
    files        = {
        f"{folder}/kdf-test.yaml": f"rules:\n- id: kdf-test-{index}\n" for index, folder in enumerate(SCAN.RULE_FOLDERS)
    }
    rules_commit = commit(source, {**files, "README.md": "rules\n", "python/notes.txt": "not a rule\n"}, "rules")
    bare         = base / "rules.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(source), str(bare)], check = True, capture_output = True)
    digest = SCAN.rules_digest(SCAN.rule_files(GIT, bare, rules_commit, SCAN.RULE_FOLDERS))
    return {"RULES_REPO": file_url(bare), "RULES_COMMIT": rules_commit, "RULES_DIGEST": digest}


def pinned_source(pins: dict[str, str]) -> str:
    text = (COMMON / "kdf_scan.py").read_text(encoding = "utf-8")
    for name, value in pins.items():
        text = set_pin(text, name, value)
    return text


def cicd_files(scan_text: str) -> dict[str, str | bytes]:
    files: dict[str, str | bytes] = {
        "tools/claude-code/kdf-scan-install.sh": SCRIPT.read_bytes(),
        "scripts/common/kdf_scan.py": scan_text,
    }
    for name in ("kdf_scan_launcher.py", "kdf_zizmor.yml", "ci_paths.py"):
        files[f"scripts/common/{name}"] = (COMMON / name).read_bytes()
    for rule in sorted((COMMON / "scan_rules").glob("*")):
        files[f"scripts/common/scan_rules/{rule.name}"] = rule.read_bytes()
    return files


def make_rig(tmp_path: Path) -> Rig:
    programs = tmp_path / "programs"
    log      = (programs / "calls.log").as_posix()
    scenario = (programs / "scenario").as_posix()
    for name, text in (
        ("whoami", WHOAMI),
        ("cygpath", CYGPATH),
        ("reg", REG),
        ("icacls", ICACLS),
        ("aclcheck", ACLCHECK),
    ):
        program(programs / name, text)
    real = {"git": REAL_GIT, "curl": CURL, "tar": "/usr/bin/tar", "sha256sum": "/usr/bin/sha256sum"}
    for name, path in real.items():
        before = BLOCK.format(scenario = scenario) if name == "curl" else ""
        program(programs / name, WRAPPER.format(name = name, log = log, real = path, before = before))
    if WINDOWS:
        (programs / "git.native").write_text(REAL_GIT, encoding = "utf-8")
    (programs / "scenario").mkdir()
    pins   = build_artifacts(tmp_path / "artifacts", programs) | build_rules(tmp_path)
    source = init_repo(tmp_path / "cicd")
    first  = commit(source, cicd_files(pinned_source(pins)), "cicd")
    root   = tmp_path / "scan-root"
    (root / "install").mkdir(parents = True)
    profile = tmp_path / "profile"
    profile.mkdir()
    temp = tmp_path / "temp"
    temp.mkdir()
    return Rig(tmp_path, programs, root, profile, temp, source, tmp_path / "artifacts", first, pins)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def installed_nothing(root: Path) -> bool:
    entries   = {path.name for path in root.iterdir()}
    staging   = root / "staging"
    leftovers = [path.name for path in staging.iterdir()] if staging.exists() else []
    return entries <= {"install", "staging"} and not leftovers


def snapshot(root: Path) -> dict[str, tuple[int, str]]:
    return {
        path.relative_to(root).as_posix(): (path.stat().st_mtime_ns, sha(path.read_bytes()))
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.relative_to(root).as_posix().startswith(("staging/", "install/"))
    }


def launcher_check(root: Path) -> tuple[int, str]:
    """
    The installed launcher's --check, its machine built from the installed bundle with this interpreter as the Python,
    the folder's permission and the token read by stand ins.
    """
    launcher = load(f"kdf_scan_launcher_check_{abs(hash(root))}", root / "kdf-scan.py")


    def machine(wrapper, folder, bundle):
        built  = wrapper.machine(folder, bundle.commit, bundle.files, GIT, cicd = None)
        python = wrapper.Tool("python", wrapper.PYTHON_VERSION, PYTHON, "", (str(PYTHON),))
        return dataclasses.replace(built, python = python)


    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = launcher.main(["--check"], root = root, platform = platform(), hooks = launcher.Hooks(machine = machine))
    return code, buffer.getvalue()

# ======================================================================================================================
# a first install, its layout and the launcher's check
# ======================================================================================================================

def test_a_first_install_into_a_folder_holding_only_install_passes_the_launchers_check(rig: Rig) -> None:
    code, text = rig.run()
    assert code == 0, text
    shown = lines(text)
    assert "TEST RUN with stand ins from" in shown[0] and rig.commit in shown[0]
    assert "TEST RUN with stand ins from" in shown[-1]
    assert f"cicd {rig.commit[:12]} installed and current" in shown[-1]
    assert "close this elevated window now and start no session from it" in shown[-1]
    root = rig.root
    assert (root / "current").read_text(encoding = "ascii") == f"{rig.commit}\n"
    assert (root / "kdf-scan.py").read_bytes() == (COMMON / "kdf_scan_launcher.py").read_bytes()
    assert (root / "opengrep" / "v1.30.2" / "opengrep.exe").read_bytes() == b"MZ opengrep stand in\n"
    assert (root / "zizmor" / "1.30.1" / "Scripts" / "zizmor.exe").read_bytes() == b"MZ zizmor stand in\n"
    assert (root / "python" / "3.14.7" / "manifest.sha256").is_file()
    assert (root / "rules" / "semgrep-rules.git").is_dir()
    assert list((root / "rules").glob("semgrep-rules-license-*.html"))
    bundle = root / "bundles" / rig.commit
    assert {path.name for path in bundle.iterdir()} >= {
        "kdf_scan.py",
        "kdf_scan_launcher.py",
        "kdf_zizmor.yml",
        "ci_paths.py",
        "scan_rules",
        "manifest.sha256",
    }
    assert not list((root / "staging").iterdir())
    code, checked = launcher_check(root)
    assert code == 0, checked
    assert "check     python 3.14.7 manifest ok" in checked
    assert "check     launcher ok" in checked


def test_cosign_runs_from_staging_with_the_exact_identity_and_a_home_of_the_staging_folders_own(rig: Rig) -> None:
    code, text = rig.run()
    assert code == 0, text
    [call] = rig.calls("cosign")
    assert f"--certificate-identity {IDENTITY} " in call
    assert "--certificate-identity-regexp" not in call
    assert "--certificate-oidc-issuer https://token.actions.githubusercontent.com" in call
    staging = (rig.root / "staging").as_posix()
    for name in ("HOME", "USERPROFILE", "TUF_ROOT"):
        assert re.search(rf"{name}={re.escape(staging)}/run\.[^/ ]+/home", call), (name, call)

# ======================================================================================================================
# what leaves no installed part
# ======================================================================================================================

@pytest.mark.parametrize("damage", [
    "opengrep-hash", "python-hash", "cosign-hash", "wheel-hash", "bad-signature", "another-workflow", "another-ref",
])
def test_a_wrong_hash_a_failed_signature_or_another_signer_leaves_no_installed_part(rig: Rig, damage: str) -> None:
    files = {
        "opengrep-hash": rig.artifacts / "opengrep_windows_x86.exe",
        "cosign-hash": rig.artifacts / "cosign.exe",
        "wheel-hash": rig.artifacts / "zizmor.whl",
    }
    if damage in files:
        with open(files[damage], "ab") as handle:
            handle.write(b"\n# one byte more\n")
    elif damage == "python-hash":
        for archive in (rig.artifacts / "archives" / "20260929").iterdir():
            archive.write_bytes(archive.read_bytes() + b"\0")
    elif damage == "bad-signature":
        rig.scenario("bad_signature")
    elif damage == "another-workflow":
        rig.scenario("signed_by", IDENTITY.replace("rolling-release.yml", "release.yml"))
    else:
        rig.scenario("signed_by", IDENTITY.replace("refs/heads/release-v1.30.2", "refs/heads/main"))
    code, text = rig.run()
    assert code == 2, text
    assert "refused" in text
    assert installed_nothing(rig.root), sorted(path.name for path in rig.root.rglob("*"))
    assert "NOT installed (exit 2)" in lines(text)[-1]
    assert "close this elevated window now" in lines(text)[-1]

# ======================================================================================================================
# the folder's permission, links and other entries
# ======================================================================================================================

def test_a_fourth_grant_before_writing_is_refused_and_nothing_is_written(rig: Rig) -> None:
    rig.scenario("fourth_grant_on_save", "1")
    (rig.root / "install" / "readme.txt").write_text("x\n", encoding = "utf-8")
    code, text = rig.run()
    assert code == 2, text
    assert "not design 5.1's three grants" in text
    assert not (rig.root / "staging").exists()


def test_a_folder_that_takes_its_parents_permission_is_refused(rig: Rig) -> None:
    rig.scenario("unprotected")
    code, text = rig.run()
    assert code == 2, text
    assert not (rig.root / "staging").exists()


@pytest.mark.parametrize("how", ["fourth-grant", "another-owner", "damaged-python"])
def test_current_is_never_replaced_before_the_read_back_and_the_manifests_pass(rig: Rig, how: str) -> None:
    if how == "fourth-grant":
        rig.scenario("fourth_grant_on_save", "2")
    elif how == "another-owner":
        rig.scenario("acl_problem", f"{rig.root.as_posix()}/python is owned by MACHINE\\everyday, not Administrators")
        rig.scenario("acl_problem_on", "2")
    else:
        rig.scenario("damage_python")
    code, text = rig.run()
    assert code == 3, text
    assert "FAILED" in text
    assert not (rig.root / "current").exists()
    assert not (rig.root / "kdf-scan.py").exists()


def test_a_junction_or_link_in_the_folder_is_refused_before_anything_is_written(rig: Rig, tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = rig.root / "install" / "linked"
    if WINDOWS:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory = True)
    code, text = rig.run()
    assert code == 2, text
    assert "a link, a junction or another special file" in text
    assert not (rig.root / "staging").exists()


def test_a_first_folder_holding_anything_else_is_refused(rig: Rig) -> None:
    (rig.root / "notes.txt").write_text("planted\n", encoding = "utf-8")
    code, text = rig.run()
    assert code == 2, text
    assert "holds notes.txt, which no install writes" in text
    assert not (rig.root / "staging").exists()


@pytest.mark.parametrize("page", ["missing", "empty"])
def test_a_licence_page_that_cannot_be_saved_refuses_the_install_and_installs_nothing(rig: Rig, page: str) -> None:
    licence = rig.artifacts / "licence.html"
    if page == "missing":
        licence.unlink()
    else:
        licence.write_bytes(b"")
    code, text = rig.run()
    assert code == 2, text
    assert "the rules' licence page could not be saved" in text
    assert installed_nothing(rig.root), sorted(path.name for path in rig.root.rglob("*"))

# ======================================================================================================================
# a second run, a later commit, a damaged part
# ======================================================================================================================

def test_a_second_run_changes_nothing_and_fetches_only_the_pythons_archive_again(rig: Rig) -> None:
    code, text = rig.run()
    assert code == 0, text
    before = snapshot(rig.root)
    rig.forget_calls()
    code, text = rig.run()
    assert code == 0, text
    assert snapshot(rig.root) == before
    fetched = rig.calls("curl")
    assert len(fetched) == 1 and "/archives/" in fetched[0], fetched
    assert not rig.calls("cosign")
    assert "python 3.14.7 in place kept, whole and the pinned archive's own" in text
    assert "current already names" in text


def test_a_wrong_owner_is_named_before_the_install_changes_any_owner(rig: Rig) -> None:
    code, text = rig.run()
    assert code == 0, text
    before = snapshot(rig.root)
    later  = rig.new_commit({"scripts/common/ci_paths.py": (COMMON / "ci_paths.py").read_text() + "# later\n"})
    rig.scenario("acl_problem", f"{rig.root.as_posix()}/opengrep is owned by MACHINE\\everyday, not Administrators")
    rig.scenario("acl_problem_on", "1")
    rig.forget_calls()
    code, text = rig.run(later)
    assert code == 2, text
    assert "owner FAIL" in text and "owned by MACHINE\\everyday" in text
    assert "read before the install changed any" in text
    assert snapshot(rig.root) == before
    staging    = (rig.root / "staging").as_posix().replace("/", "\\")
    owners_set = [call for call in rig.calls("icacls") if "/setowner" in call]
    assert owners_set and all(call.split(" ", 1)[1].startswith(staging) for call in owners_set), owners_set


def test_the_folders_own_python_never_runs_and_one_unlike_the_archive_is_refused(rig: Rig, tmp_path: Path) -> None:
    code, text = rig.run()
    assert code == 0, text
    marker = tmp_path / "folder-python-ran"
    folder = rig.root / "python" / "3.14.7"
    (folder / "python.exe").write_text(f'#!/bin/sh\nprintf ran > "{marker.as_posix()}"\n', encoding = "utf-8")
    lines_of  = (folder / "manifest.sha256").read_text(encoding = "utf-8").splitlines()
    rewritten = [
        f"{sha((folder / 'python.exe').read_bytes())}  python.exe" if line.endswith("  python.exe") else line
        for line in lines_of
    ]
    (folder / "manifest.sha256").write_text("\n".join(rewritten) + "\n", encoding = "utf-8", newline = "\n")
    code, text = rig.run()
    assert code == 2, text
    assert "python 3.14.7 at" in text and "is not whole against its pin, damage on disk" in text
    assert not marker.exists()


def test_a_later_commit_adds_its_bundle_and_never_touches_an_existing_versions_folder(rig: Rig) -> None:
    code, text = rig.run()
    assert code == 0, text
    before = snapshot(rig.root)
    later  = rig.new_commit({"scripts/common/ci_paths.py": (COMMON / "ci_paths.py").read_text() + "# later\n"})
    code, text = rig.run(later)
    assert code == 0, text
    after = snapshot(rig.root)
    for path, state in before.items():
        if path not in ("current", "kdf-scan.py"):
            assert after[path] == state, path
    assert (rig.root / "current").read_text(encoding = "ascii") == f"{later}\n"
    assert (rig.root / "bundles" / rig.commit / "manifest.sha256").is_file()
    assert (rig.root / "bundles" / later / "manifest.sha256").is_file()


def test_a_damaged_part_refuses_a_later_install_and_stays_as_it_was(rig: Rig) -> None:
    code, text = rig.run()
    assert code == 0, text
    executable = rig.root / "opengrep" / "v1.30.2" / "opengrep.exe"
    executable.write_bytes(executable.read_bytes() + b"damage")
    damaged = executable.read_bytes()
    later   = rig.new_commit({"scripts/common/ci_paths.py": (COMMON / "ci_paths.py").read_text() + "# later\n"})
    code, text = rig.run(later)
    assert code == 2, text
    assert "is not whole against its pin, damage on disk" in text
    assert executable.read_bytes() == damaged
    assert (rig.root / "current").read_text(encoding = "ascii") == f"{rig.commit}\n"

# ======================================================================================================================
# two runs at once, a run killed, a first install cut short
# ======================================================================================================================

def test_two_runs_at_once_never_share_a_staging_folder_and_never_both_move_parts_into_place(rig: Rig) -> None:
    rig.scenario("block")
    first = subprocess.Popen(
        rig.command(),
        stdout = subprocess.PIPE,
        stderr = subprocess.STDOUT,
        text = True,
        env = rig.environment(),
    )
    try:
        lock     = rig.root / "staging" / "lock" / "pid"
        deadline = time.monotonic() + 120
        while not lock.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        assert lock.exists(), "the first run never took the lock"
        runs_before = sorted(path.name for path in (rig.root / "staging").glob("run.*"))
        code, text = rig.run()
        assert code == 2, text
        assert "another install runs" in text
        assert sorted(path.name for path in (rig.root / "staging").glob("run.*")) == runs_before
        assert not (rig.root / "current").exists()
        rig.scenario("release")
        output, _ = first.communicate(timeout = 600)
    finally:
        if first.poll() is None:
            first.kill()
    assert first.returncode == 0, output
    assert (rig.root / "current").read_text(encoding = "ascii") == f"{rig.commit}\n"


def test_an_install_killed_between_the_bundle_and_current_leaves_the_old_bundle_current(rig: Rig) -> None:
    code, text = rig.run()
    assert code == 0, text
    later = rig.new_commit({"scripts/common/ci_paths.py": (COMMON / "ci_paths.py").read_text() + "# later\n"})
    rig.scenario("kill_on_setowner")
    code, text = rig.run(later)
    assert code != 0, text
    assert (rig.root / "current").read_text(encoding = "ascii") == f"{rig.commit}\n"
    assert (rig.root / "bundles" / later).is_dir()
    assert (rig.root / "staging" / "lock").is_dir()
    rig.clear("kill_on_setowner")
    code, text = rig.run(later)
    assert code == 0, text
    assert "lock taken over from process" in text
    assert "staging folder run." in text
    assert (rig.root / "current").read_text(encoding = "ascii") == f"{later}\n"


def test_a_first_install_cut_short_and_run_again_keeps_its_checked_parts_and_removes_a_damaged_one(rig: Rig) -> None:
    rig.scenario("kill_on_setowner")
    code, text = rig.run()
    assert code != 0, text
    assert not (rig.root / "current").exists()
    library = rig.root / "python" / "3.14.7" / "Lib" / "os.py"
    library.write_bytes(library.read_bytes() + b"damage\n")
    rig.clear("kill_on_setowner")
    rig.forget_calls()
    code, text = rig.run()
    assert code == 0, text
    assert "python 3.14.7 at" in text and "was not whole, removed to install again" in text
    assert "opengrep v1.30.2 kept" in text
    assert "zizmor 1.30.1 kept" in text
    fetched = rig.calls("curl")
    assert any("archives" in call for call in fetched), fetched
    assert not any("opengrep_windows_x86" in call for call in fetched), fetched
    assert library.read_bytes() == b"# os stand in\n"

# ======================================================================================================================
# cicd's commit and the pins
# ======================================================================================================================

def test_a_commit_off_main_is_refused_before_any_of_its_files_runs(rig: Rig) -> None:
    git(rig.source, "checkout", "-q", "-b", "feature")
    off_main = rig.new_commit({"scripts/common/ci_paths.py": "raise SystemExit('ran')\n"}, "off main")
    git(rig.source, "checkout", "-q", "main")
    code, text = rig.run(off_main)
    assert code == 2, text
    assert "is not on cicd's main" in text
    assert not rig.calls("curl")
    assert installed_nothing(rig.root)


def test_a_script_other_than_the_commits_own_is_refused(rig: Rig) -> None:
    script = rig.script_for(rig.commit)
    script.write_bytes(script.read_bytes() + b"\n# changed after the fetch\n")
    code, text = rig.run()
    assert code == 2, text
    assert "differs from the commit's own" in text
    assert not rig.calls("curl")


@pytest.mark.parametrize("change", [
    ("PYTHON_BUILD", 'PYTHON_BUILD = "20260929"\nPYTHON_BUILD = "20250101"'),
    ("PYTHON_VERSION", 'PYTHON_VERSION = "3.14"'),
    ("PYTHON_ARCHIVE_SHA256", 'PYTHON_ARCHIVE_SHA256: str = "' + "a" * 64 + '"'),
    ("PYTHON_ARCHIVE_BASE", 'PYTHON_ARCHIVE_BASE = "http://example.com/archives"'),
])
def test_a_python_pin_defined_twice_or_malformed_is_refused_before_any_fetch(
    rig: Rig,
    change: tuple[str, str],
) -> None:
    name, replacement = change
    text    = rig_scan_text(rig)
    text    = re.sub(rf"^{name} +=.*$", lambda _match: replacement, text, count = 1, flags = re.MULTILINE)
    changed = rig.new_commit({"scripts/common/kdf_scan.py": text})
    code, output = rig.run(changed)
    assert code == 2, output
    assert f"defines {name}" in output
    assert not rig.calls("curl")


def test_pins_unlike_the_strict_pattern_are_refused(rig: Rig) -> None:
    text    = rig_scan_text(rig).replace(
        "\n# the security folders of Semgrep's rules",
        '\nglobals()["PYTHON_BUILD"] = "20250101"\n# the security folders of Semgrep\'s rules',
    )
    changed = rig.new_commit({"scripts/common/kdf_scan.py": text})
    code, output = rig.run(changed)
    assert code == 2, output
    assert "--pins names a Python other than the strict pattern read" in output
    assert not rig.calls("cosign")
    assert installed_nothing(rig.root)


def rig_scan_text(rig: Rig) -> str:
    return git_bytes(rig.source, "HEAD:scripts/common/kdf_scan.py").decode("utf-8")


def test_the_archives_address_the_install_builds_is_the_one_uv_0_13_1_names(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    shutil.copy(COMMON / "kdf_scan.py", bundle / "kdf_scan.py")
    snippet = 'source "$1"; BUNDLE="$2"; programs=""; read_python_pins > /dev/null; printf "%s" "$PYTHON_ARCHIVE_URL"'
    command = [BASH, "-c", snippet, "install", SCRIPT.as_posix(), bundle.as_posix()]
    done    = subprocess.run(command, capture_output = True, text = True, check = False)
    assert done.returncode == 0, done.stderr
    assert done.stdout == UV_URL == SCAN.PYTHON_ARCHIVE_URL

# ======================================================================================================================
# the checks before anything
# ======================================================================================================================

def test_another_account_is_refused_before_anything_is_written(rig: Rig) -> None:
    rig.scenario("account", "MACHINE\\everyday")
    code, text = rig.run()
    assert code == 2, text
    assert "runs in the account kdf-install alone" in text
    assert not (rig.root / "staging").exists()


def test_a_window_not_elevated_is_refused(rig: Rig) -> None:
    rig.scenario("level", "8192")
    code, text = rig.run()
    assert code == 2, text
    assert "this window is not elevated" in text


def test_a_bash_whose_root_is_not_gits_is_refused(rig: Rig) -> None:
    rig.scenario("root", "C:\\msys64\\")
    code, text = rig.run()
    assert code == 2, text
    assert "so it is not Git's own bash" in text


@pytest.mark.parametrize("values", [
    {"EnableLUA": "REG_DWORD 0x0"},
    {"ConsentPromptBehaviorAdmin": "REG_DWORD 0x0"},
    {"PromptOnSecureDesktop": "REG_DWORD 0x0"},
    {"PromptOnSecureDesktop": "REG_DWORD 0x0", "ConsentPromptBehaviorAdmin": "REG_DWORD 0x5"},
    {"EnableLUA": "REG_SZ one"},
])
def test_each_open_uac_value_is_refused_before_anything_is_written(rig: Rig, values: dict[str, str]) -> None:
    for name, value in values.items():
        rig.scenario(name, value)
    code, text = rig.run()
    assert code == 2, text
    assert "refused" in text
    assert not (rig.root / "staging").exists()


def test_a_prompt_on_the_desktop_with_a_password_prompt_is_open_to_no_program_and_passes(rig: Rig) -> None:
    rig.scenario("PromptOnSecureDesktop", "REG_DWORD 0x0")
    rig.scenario("ConsentPromptBehaviorAdmin", "REG_DWORD 0x1")
    code, text = rig.run()
    assert code == 0, text
    assert "uac EnableLUA 1 ConsentPromptBehaviorAdmin 1 PromptOnSecureDesktop 0 ok" in text


def test_a_startup_file_in_the_accounts_profile_is_refused(rig: Rig) -> None:
    (rig.profile / ".bashrc").write_text("echo hi\n", encoding = "utf-8")
    code, text = rig.run()
    assert code == 2, text
    assert "a shell startup file" in text and ".bashrc" in text


def test_programs_is_refused_when_the_token_is_elevated(tmp_path: Path) -> None:
    stand_in = program(tmp_path / "whoami.exe", WHOAMI)
    snippet  = 'source "$1"; real_whoami="$2"; programs=x; refuse_if_elevated'
    command  = [BASH, "-c", snippet, "install", SCRIPT.as_posix(), stand_in.as_posix()]
    (tmp_path / "scenario").mkdir()
    for level, expected in (("12288", 2), ("16384", 2), ("8192", 0)):
        (tmp_path / "scenario" / "level").write_text(level, encoding = "utf-8")
        done = subprocess.run(command, capture_output = True, text = True, check = False)
        assert done.returncode == expected, (level, done.stdout, done.stderr)
        if expected:
            assert "--programs runs stand ins and is refused in an elevated window" in done.stdout


def test_root_and_cicd_are_refused_without_programs_and_an_unknown_option_is_refused(tmp_path: Path) -> None:
    for extra in (["--root", tmp_path.as_posix()], ["--cicd", "file:///x"], ["--verbose"]):
        done = subprocess.run(
            [BASH, "-p", SCRIPT.as_posix(), "a" * 40, *extra],
            capture_output = True,
            text = True,
            check = False,
        )
        assert done.returncode == 2, (extra, done.stdout)
        assert "refused" in done.stdout


def test_the_clean_room_refuses_any_variable_env_i_never_passed(rig: Rig) -> None:
    inner = rig.root / "staging" / "run.direct"
    (inner / "home").mkdir(parents = True)
    command = [BASH, "-p", rig.script_for(rig.commit).as_posix(), "--inner", inner.as_posix(), rig.commit]
    command += ["--programs", rig.programs.as_posix(), "--root", rig.root.as_posix(), "--cicd", file_url(rig.source)]
    done = subprocess.run(
        command,
        capture_output = True,
        text = True,
        env = rig.environment(),
        cwd = inner,
        check = False,
    )
    assert done.returncode == 2, done.stdout
    assert "the clean room holds" in done.stdout
    assert not (rig.root / "staging" / "lock").exists()

# ======================================================================================================================
# inputs the real programs always act on, each shown to fire without the clean room, then reaching no run
# ======================================================================================================================

def test_a_hostile_bash_env_runs_without_privileged_mode_and_reaches_no_run_with_it(
    rig: Rig,
    tmp_path: Path,
) -> None:
    marker  = tmp_path / "bash-env-ran"
    hostile = program(tmp_path / "hostile-env.sh", f'printf ran >> "{marker.as_posix()}"\n')
    code, text = rig.run(privileged = False, BASH_ENV = hostile.as_posix())
    assert marker.exists(), "the control, bash without -p, read BASH_ENV"
    assert code == 2 and "bash -p" in text, text
    marker.unlink()
    code, text = rig.run(BASH_ENV = hostile.as_posix())
    assert code == 0, text
    assert not marker.exists()


def test_a_path_naming_hostile_programs_reaches_no_run(rig: Rig, tmp_path: Path) -> None:
    marker  = tmp_path / "planted-ran"
    planted = tmp_path / "planted"
    for name in PLANTED:
        program(planted / name, HOSTILE.format(marker = marker.as_posix()))
    environment  = rig.environment()
    separator    = ";" if WINDOWS else ":"
    hostile_path = str(planted) + separator + environment["PATH"]
    subprocess.run(
        [BASH, "-c", "sha256sum --version"],
        env = {**environment, "PATH": hostile_path},
        capture_output = True,
        check = False,
    )
    assert marker.exists(), "the control, a bare sha256sum, ran the planted program"
    marker.unlink()
    code, text = rig.run(PATH = hostile_path)
    assert code == 0, text
    assert not marker.exists(), marker.read_text(encoding = "utf-8")


def test_a_gitconfig_rewriting_every_fetch_reaches_no_run(rig: Rig, tmp_path: Path) -> None:
    evil        = init_repo(tmp_path / "evil")
    evil_commit = commit(evil, {"README.md": "not cicd\n"}, "evil")
    home        = tmp_path / "evil-home"
    home.mkdir()
    (home / ".gitconfig").write_text(
        f'[url "{file_url(evil)}"]\n\tinsteadOf = {file_url(rig.source)}\n',
        encoding = "utf-8",
    )
    changes = {"HOME": home.as_posix(), "USERPROFILE": home.as_posix()}
    control = subprocess.run(
        [REAL_GIT, "ls-remote", file_url(rig.source)],
        capture_output = True,
        text = True,
        env = rig.environment(**changes),
        check = False,
    )
    assert evil_commit in control.stdout, "the control, git with that HOME, fetched the rewritten address"
    code, text = rig.run(**changes)
    assert code == 0, text


def test_a_curlrc_changing_every_request_reaches_no_run(rig: Rig, tmp_path: Path) -> None:
    marker = tmp_path / "curl-trace"
    home   = tmp_path / "curl-home"
    home.mkdir()
    for name in (".curlrc", "_curlrc"):
        (home / name).write_text(f'trace-ascii = "{marker.as_posix()}"\n', encoding = "utf-8")
    changes = {
        "HOME": home.as_posix(),
        "USERPROFILE": home.as_posix(),
        "CURL_HOME": home.as_posix(),
        "APPDATA": home.as_posix(),
    }
    subprocess.run(
        [CURL, "-sS", "-o", (tmp_path / "out").as_posix(), rig.pins["RULES_LICENSE_URL"]],
        env = rig.environment(**changes),
        capture_output = True,
        check = False,
    )
    assert marker.exists(), "the control, curl with that HOME, read the .curlrc"
    marker.unlink()
    code, text = rig.run(**changes)
    assert code == 0, text
    assert not marker.exists()


def test_a_git_trace_variable_reaches_no_run(rig: Rig, tmp_path: Path) -> None:
    marker = tmp_path / "git-trace"
    subprocess.run(
        [REAL_GIT, "--version"],
        env = rig.environment(GIT_TRACE = marker.as_posix()),
        capture_output = True,
        check = False,
    )
    assert marker.exists(), "the control, git with GIT_TRACE, wrote its trace"
    marker.unlink()
    code, text = rig.run(GIT_TRACE = marker.as_posix())
    assert code == 0, text
    assert not marker.exists()
