"""
The local code scan's launcher, installed by the owner as D:/KriegerDataForge-scan/kdf-scan.py and run by every repo's
`make scan` under the scan folder's own Python with -I and -S (D-084).

Before anything, it refuses with exit 2 when its own process is elevated, read from its token's TokenElevation, or
when UAC's values leave the folder's fence open, EnableLUA 0, ConsentPromptBehaviorAdmin 0, or PromptOnSecureDesktop 0
while that prompt would not use the secure desktop, each value's meaning as Microsoft's page on UAC's settings gives
it. The refusal is a tripwire that shows a session started elevated, never a fence, since an elevated session need not
run it.

Then it reads `current` once, checks every file of that bundle against the bundle's manifest, a stray file or a
missing one refused, and runs the wrapper from the very bytes it hashed, so the whole run rests on one bundle however
`current` changes meanwhile. `--check` prints the installed tools, the Python, the rules, the bundle, the launcher and
the folder's permission, and asks GitHub whether the bundle is behind cicd's main. `--pr <link>` is the scan before a
merge and the reviewer's local gate. It asks GitHub for the pull request's head and its base's main, fetches both into
a private ref and checks their ids, compares the pasted last line's commit with the head, reads `not_docs` and the
exclusions at that main, skips the pull request only when the bundle's own ci_paths.py calls it docs only, and scans
the head. Nothing in a writable checkout decides whether or what it scans. Standard library only.
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
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, TextIO

# ======================================================================================================================
# Configuration
# ======================================================================================================================

# the bundle, the file naming the current one, each bundle's manifest, and the files every bundle holds
CURRENT      = "current"
MANIFEST     = "manifest.sha256"
LAUNCHER     = "kdf-scan.py"
BUNDLE_FILES = ("kdf_scan.py", "kdf_scan_launcher.py", "kdf_zizmor.yml", "ci_paths.py")
COMMIT       = re.compile(r"[0-9a-f]{40}")
LISTED       = re.compile(r"(?P<sha>[0-9a-f]{64})  (?P<path>\S(?:.*\S)?)")
# UAC's values under HKLM, each default as Microsoft's page on UAC's settings gives it, read on 2026-10-21 at its
# commit 52ef23b, and the two prompt behaviours that use the secure desktop whatever PromptOnSecureDesktop says
UAC_KEY        = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
UAC_DEFAULTS   = {"EnableLUA": 1, "ConsentPromptBehaviorAdmin": 5, "PromptOnSecureDesktop": 1}
SECURE_PROMPTS = frozenset({1, 2})
# the token's elevation and the security descriptor's parts the launcher reads
TOKEN_QUERY                = 0x0008
TOKEN_ELEVATION            = 20
SE_FILE_OBJECT             = 1
OWNER_SECURITY_INFORMATION = 0x1
DACL_SECURITY_INFORMATION  = 0x4
SE_DACL_PROTECTED          = 0x1000
ACL_SIZE_INFORMATION       = 2
# who may write the folder, what writing is in an entry's mask, the grants of design 5.1, and the entry kinds that
# grant, allowed, allowed object, allowed callback and allowed callback object
ADMINISTRATORS = "S-1-5-32-544"
SYSTEM         = "S-1-5-18"
USERS          = "S-1-5-32-545"
WRITERS        = frozenset({ADMINISTRATORS, SYSTEM})
NAMES          = {ADMINISTRATORS: "Administrators", SYSTEM: "SYSTEM", USERS: "Users", "S-1-1-0": "Everyone"}
WRITE_RIGHTS   = 0x2 | 0x4 | 0x10 | 0x40 | 0x100 | 0x10000 | 0x40000 | 0x80000 | 0x10000000 | 0x40000000
FULL_CONTROL   = 0x1F01FF
READ_EXECUTE   = 0x1200A9
GENERIC_ALL    = 0x10000000
GENERIC_READ   = 0x80000000 | 0x20000000
ALLOW_KINDS    = frozenset({0, 5, 9, 11})
SID_AT_EIGHT   = frozenset({0, 1, 9, 10})
SHOWN_PROBLEMS = 20
# GitHub, asked through gh at a path only an administrator can write, cicd's repo, and the private refs a verify
# fetches into
GH_PATHS = ("C:/Program Files/GitHub CLI/gh.exe",)
CICD     = "Needless2Say/kriegerdataforge-cicd"
PR_LINK  = re.compile(r"https://github\.com/(?P<owner>[A-Za-z0-9-]+)/(?P<repo>[A-Za-z0-9._-]+)/pull/(?P<number>\d+)")
HEAD_REF = "refs/kdf-scan/verify/head"
MAIN_REF = "refs/kdf-scan/verify/main"
PASTED   = re.compile(r"kdf-scan (?P<commit>[0-9a-f]{7,40}) (?:clean-tree|dirty-tree|at-commit) ")
NOT_DOCS = re.compile(r"(?P<indent>\s*)not_docs:\s*(?P<value>.*?)\s*")
REFUSED  = f"kdf-scan {'-' * 12} REFUSED (exit 2)"

# ======================================================================================================================
# The shapes
# ======================================================================================================================

class Refusal(Exception):
    """
    A launch refused before anything scans, exit 2.
    """


@dataclass(frozen = True)
class Ace:
    """
    One entry of a permission, its kind, its inheritance flags, its access mask and whom it names.
    """
    kind:  int
    flags: int
    mask:  int
    sid:   str


@dataclass(frozen = True)
class Bundle:
    """
    The current bundle, its cicd commit, its folder and every file of it as the manifest checked it.
    """
    commit: str
    folder: Path
    files:  dict[str, bytes]


@dataclass(frozen = True)
class Hooks:
    """
    What a test replaces, how the machine is built, gh's command and git's path.
    """
    machine: Callable | None = None
    gh:      tuple[str, ...] | None = None
    git:     str | None = None

# ======================================================================================================================
# The fence's tripwire, an elevated token and UAC's values
# ======================================================================================================================

def fence_problems(elevated: bool, values: Mapping[str, object]) -> list[str]:
    """
    Why the folder's fence is open for this process, an elevated token or a UAC value, a missing value read as its
    default.

    Args:
        elevated: whether this process's token is elevated
        values: UAC's values by name, None for a value that is not set

    Returns:
        list[str]: each reason, empty when the fence holds
    """
    problems = []
    if elevated:
        problems.append("this process is elevated, so the folder's permission does not fence it, and every session "
                        "starts from an ordinary window")
    read = {}
    for name, default in UAC_DEFAULTS.items():
        value = values.get(name)
        value = default if value is None else value
        if isinstance(value, bool) or not isinstance(value, int):
            problems.append(f"UAC's {name} is not a number the launcher can read")
            continue
        read[name] = value
    if read.get("EnableLUA") == 0:
        problems.append(
            "UAC is off, EnableLUA is 0, so every process of an administrator holds the right the fence " "withholds",
        )
    prompt = read.get("ConsentPromptBehaviorAdmin")
    if prompt == 0:
        problems.append("ConsentPromptBehaviorAdmin is 0, so an administrator's command is elevated with no prompt")
    elif read.get("PromptOnSecureDesktop") == 0 and prompt not in SECURE_PROMPTS:
        problems.append(f"PromptOnSecureDesktop is 0 with ConsentPromptBehaviorAdmin {prompt}, so the prompt shows on "
                        f"the desktop, where a program could answer it")
    return problems


def token_elevated() -> bool:
    """
    Whether this process's token is elevated, read through GetTokenInformation with TokenElevation.

    Returns:
        bool: True when it is elevated

    Raises:
        OSError: when the token cannot be read, which the caller counts as elevated
    """
    if sys.platform != "win32":
        raise OSError("the token is read on Windows alone")
    import ctypes
    from ctypes import wintypes
    advapi32                              = ctypes.WinDLL("advapi32", use_last_error = True)
    kernel32                              = ctypes.WinDLL("kernel32", use_last_error = True)
    kernel32.GetCurrentProcess.restype    = wintypes.HANDLE
    kernel32.CloseHandle.argtypes         = (wintypes.HANDLE,)
    advapi32.OpenProcessToken.argtypes    = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    advapi32.OpenProcessToken.restype     = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetTokenInformation.restype  = wintypes.BOOL
    token                                 = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
        raise OSError(ctypes.get_last_error(), "OpenProcessToken failed")
    try:
        elevation, size = wintypes.DWORD(), wintypes.DWORD()
        done = advapi32.GetTokenInformation(
            token,
            TOKEN_ELEVATION,
            ctypes.byref(elevation),
            ctypes.sizeof(elevation),
            ctypes.byref(size),
        )
        if not done:
            raise OSError(ctypes.get_last_error(), "GetTokenInformation failed")
        return bool(elevation.value)
    finally:
        kernel32.CloseHandle(token)


def read_uac() -> dict[str, object]:
    """
    UAC's three values from HKLM, None for one that is not set, and a value of another type kept as its text.

    Returns:
        dict[str, object]: each value by name
    """
    import winreg
    values: dict[str, object] = dict.fromkeys(UAC_DEFAULTS)
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, UAC_KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    except FileNotFoundError:
        return values
    with key:
        for name in UAC_DEFAULTS:
            try:
                value, kind = winreg.QueryValueEx(key, name)
            except FileNotFoundError:
                continue
            values[name] = int(value) if kind == winreg.REG_DWORD else str(value)
    return values

# ======================================================================================================================
# The folder's permission
# ======================================================================================================================

def named(sid: str) -> str:
    """
    A SID by its well known name where it has one.

    Args:
        sid: the SID's text

    Returns:
        str: the name, or the SID
    """
    return NAMES.get(sid, sid)


def acl_findings(label: str, owner: str, protected: bool, aces: list[Ace], root: bool) -> list[str]:
    """
    How one item's permission is weaker than design 5.1's, an owner other than Administrators or SYSTEM, a grant of
    writing to anyone else, and for the folder itself, inheritance or a grant of the design missing.

    Args:
        label: the item, as the line names it
        owner: its owner's SID
        protected: whether its permission refuses inheritance
        aces: its entries
        root: whether it is the folder itself

    Returns:
        list[str]: each weakness, empty when there is none
    """
    problems = []
    if owner not in WRITERS:
        problems.append(f"{label} is owned by {named(owner)}, not Administrators or SYSTEM, and an owner can change "
                        f"its permission")
    for ace in aces:
        if ace.kind in ALLOW_KINDS and ace.mask & WRITE_RIGHTS and ace.sid not in WRITERS:
            problems.append(f"{label} lets {named(ace.sid)} write")
    if not root:
        return problems
    if not protected:
        problems.append(f"{label} takes permissions from its parent, which the install's /inheritance:r refuses")
    allowed = [ace for ace in aces if ace.kind in ALLOW_KINDS]
    for sid in (ADMINISTRATORS, SYSTEM):
        if not any(
            ace.sid == sid and (ace.mask & FULL_CONTROL == FULL_CONTROL or ace.mask & GENERIC_ALL) for ace in allowed
        ):
            problems.append(f"{label} gives {named(sid)} no full control, the install's grant is missing")
    if not any(ace.sid == USERS and (ace.mask & READ_EXECUTE == READ_EXECUTE or ace.mask & GENERIC_READ == GENERIC_READ)
               for ace in allowed):
        problems.append(f"{label} gives Users no read and run, so no session can run the tools")
    return problems


def read_security(path: Path) -> tuple[str, bool, list[Ace]]:
    """
    One item's owner, whether its permission refuses inheritance, and its entries, through GetNamedSecurityInfoW.

    Args:
        path: the file or folder

    Returns:
        tuple[str, bool, list[Ace]]: the owner's SID, the protection and the entries, a null permission read as
            Everyone's full control

    Raises:
        OSError: when the descriptor cannot be read
    """
    import ctypes
    from ctypes import wintypes
    advapi32                                       = ctypes.WinDLL("advapi32", use_last_error = True)
    kernel32                                       = ctypes.WinDLL("kernel32", use_last_error = True)
    pointer                                        = ctypes.POINTER(ctypes.c_void_p)
    advapi32.GetNamedSecurityInfoW.argtypes        = (
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        pointer,
        pointer,
        pointer,
        pointer,
        pointer,
    )
    advapi32.GetNamedSecurityInfoW.restype         = wintypes.DWORD
    advapi32.GetSecurityDescriptorControl.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.WORD),
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetAclInformation.argtypes            = (ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int)
    advapi32.GetAce.argtypes                       = (ctypes.c_void_p, wintypes.DWORD, pointer)
    advapi32.ConvertSidToStringSidW.argtypes       = (ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR))
    kernel32.LocalFree.argtypes                    = (ctypes.c_void_p,)


    def text(sid: int) -> str:
        """
        A SID's text, its buffer freed.

        Args:
            sid: the SID's address

        Returns:
            str: the SID as text

        Raises:
            OSError: when the SID cannot be converted
        """
        found = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(found)):
            raise OSError(ctypes.get_last_error(), "ConvertSidToStringSidW failed")
        try:
            return str(found.value)
        finally:
            kernel32.LocalFree(ctypes.cast(found, ctypes.c_void_p))


    class AclSize(ctypes.Structure):
        """
        ACL_SIZE_INFORMATION, how many entries a permission holds.
        """
        _fields_ = [("count", wintypes.DWORD), ("used", wintypes.DWORD), ("free", wintypes.DWORD)]


    owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    wanted = OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION
    status = advapi32.GetNamedSecurityInfoW(
        str(path),
        SE_FILE_OBJECT,
        wanted,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if status != 0:
        raise OSError(status, f"GetNamedSecurityInfoW failed on {path}")
    try:
        control, revision = wintypes.WORD(), wintypes.DWORD()
        if not advapi32.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)):
            raise OSError(ctypes.get_last_error(), "GetSecurityDescriptorControl failed")
        owner_sid = text(owner.value)
        protected = bool(control.value & SE_DACL_PROTECTED)
        if not dacl.value:
            return owner_sid, protected, [Ace(0, 0, FULL_CONTROL, "S-1-1-0")]
        size = AclSize()
        if not advapi32.GetAclInformation(dacl, ctypes.byref(size), ctypes.sizeof(size), ACL_SIZE_INFORMATION):
            raise OSError(ctypes.get_last_error(), "GetAclInformation failed")
        aces = []
        for index in range(size.count):
            entry = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(entry)):
                raise OSError(ctypes.get_last_error(), "GetAce failed")
            kind  = ctypes.c_ubyte.from_address(entry.value).value
            flags = ctypes.c_ubyte.from_address(entry.value + 1).value
            mask  = wintypes.DWORD.from_address(entry.value + 4).value
            sid   = text(entry.value + 8) if kind in SID_AT_EIGHT else "an object entry"
            aces.append(Ace(kind, flags, mask, sid))
        return owner_sid, protected, aces
    finally:
        kernel32.LocalFree(descriptor)


def acl_problems(root: Path, reader: Callable[[Path], tuple[str, bool, list[Ace]]] = read_security) -> list[str]:
    """
    Every weakness of the folder's permission and of everything under it, a link anywhere refused.

    Args:
        root: the scan folder
        reader: how one item's permission is read

    Returns:
        list[str]: each weakness, at most SHOWN_PROBLEMS and a count of the rest
    """
    try:
        problems = acl_findings(str(root), *reader(root), root = True)
    except OSError as error:
        return [f"{root}'s permission could not be read, {error}"]
    for folder, folders, files in os.walk(root):
        for name in sorted(folders + files):
            path = Path(folder) / name
            try:
                if path.is_symlink():
                    problems.append(f"{path} is a link, which the folder never holds")
                    continue
                problems.extend(acl_findings(str(path), *reader(path), root = False))
            except OSError as error:
                problems.append(f"{path}'s permission could not be read, {error}")
            if len(problems) > SHOWN_PROBLEMS:
                return [*problems[:SHOWN_PROBLEMS], "and more, each one the install's read back would name"]
    return problems


def windows_platform() -> types.SimpleNamespace:
    """
    The launcher's reads of this machine, its token, UAC's values and the folder's permission.

    Returns:
        types.SimpleNamespace: elevated, uac and acl
    """
    return types.SimpleNamespace(elevated = token_elevated, uac = read_uac, acl = acl_problems)

# ======================================================================================================================
# The bundle, read once and checked against its manifest
# ======================================================================================================================

def read_current(root: Path) -> str:
    """
    The current bundle's commit, read once.

    Args:
        root: the scan folder

    Returns:
        str: the commit

    Raises:
        Refusal: when the file is missing or names no commit
    """
    try:
        text = (root / CURRENT).read_text(encoding = "ascii")
    except (OSError, UnicodeDecodeError) as error:
        raise Refusal(f"the scan folder's {CURRENT} file cannot be read, {error}") from error
    if not COMMIT.fullmatch(text.strip()):
        raise Refusal(f"the scan folder's {CURRENT} file names no single cicd commit")
    return text.strip()


def plain(path: str) -> bool:
    """
    Whether a manifest's path stays inside its bundle.

    Args:
        path: the path

    Returns:
        bool: True for a plain relative path
    """
    if not path or path.startswith("/") or "\\" in path or ":" in path:
        return False
    return all(part not in ("", ".", "..") for part in path.split("/"))


def load_bundle(root: Path) -> Bundle:
    """
    The current bundle, every file of it hashed against its manifest, a stray file, a missing one or a path outside
    it refused.

    Args:
        root: the scan folder

    Returns:
        Bundle: the bundle with its checked files

    Raises:
        Refusal: when `current` or the manifest refuses
    """
    commit = read_current(root)
    folder = root / "bundles" / commit
    try:
        lines = (folder / MANIFEST).read_text(encoding = "utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise Refusal(f"the bundle {commit[:12]} has no manifest that can be read") from error
    listed: dict[str, str] = {}
    for line in lines:
        match = LISTED.fullmatch(line)
        if not match or not plain(match["path"]) or match["path"] in listed or match["path"] == MANIFEST:
            raise Refusal(f"the bundle {commit[:12]}'s manifest holds a line it cannot take, {line[:80]!r}")
        listed[match["path"]] = match["sha"]
    present = set()
    for place, _folders, files in os.walk(folder):
        for name in files:
            path = (Path(place) / name).relative_to(folder).as_posix()
            if path != MANIFEST:
                present.add(path)
    if present - set(listed) or set(listed) - present:
        odd = sorted((present - set(listed)) | (set(listed) - present))
        raise Refusal(f"the bundle {commit[:12]} differs from its manifest at {', '.join(odd)}")
    files = {}
    for path, sha in listed.items():
        local = folder / path
        if local.is_symlink():
            raise Refusal(f"the bundle {commit[:12]} holds a link at {path}, which its manifest cannot vouch for")
        data = local.read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            raise Refusal(f"the bundle {commit[:12]}'s {path} differs from its manifest")
        files[path] = data
    missing = [name for name in BUNDLE_FILES if name not in files]
    if missing:
        raise Refusal(f"the bundle {commit[:12]}'s manifest lists no {', '.join(missing)}")
    return Bundle(commit, folder, files)


def load_module(name: str, bundle: Bundle, filename: str) -> types.ModuleType:
    """
    A module of the bundle, compiled from the bytes the manifest checked and never read again from disk.

    Args:
        name: the module's name
        bundle: the bundle
        filename: the file inside it

    Returns:
        types.ModuleType: the module
    """
    module          = types.ModuleType(name)
    module.__file__ = str(bundle.folder / filename)
    sys.modules[name] = module
    exec(compile(bundle.files[filename], module.__file__, "exec"), module.__dict__)  # noqa: S102
    return module

# ======================================================================================================================
# GitHub, through gh
# ======================================================================================================================

def find_gh() -> tuple[str, ...]:
    """
    gh at a path only an administrator can write.

    Returns:
        tuple[str, ...]: its command

    Raises:
        Refusal: when no gh is at a protected path
    """
    for candidate in GH_PATHS:
        if Path(candidate).is_file():
            return (candidate,)
    raise Refusal(f"no gh at a protected path, looked for {', '.join(GH_PATHS)}")


def gh_json(gh_command: tuple[str, ...], endpoint: str) -> object:
    """
    One answer of GitHub's API through gh, on github.com whatever gh's environment names.

    Args:
        gh_command: gh's command
        endpoint: the API path

    Returns:
        object: the answer's JSON

    Raises:
        Refusal: when gh fails or answers with no JSON
    """
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith(("GH_", "GITHUB_"))}
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(name):
            environment[name] = os.environ[name]
    environment.update({"GH_HOST": "github.com", "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"})
    done = subprocess.run(
        [*gh_command, "api", "--hostname", "github.com", endpoint],
        capture_output = True,
        env = environment,
        check = False,
    )
    if done.returncode != 0:
        said = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise Refusal(f"gh could not read {endpoint.split('?')[0]}, {said[-1] if said else 'no answer'}")
    try:
        return json.loads(done.stdout.decode("utf-8"))
    except ValueError as error:
        raise Refusal(f"gh's answer for {endpoint.split('?')[0]} is not JSON") from error


def bundle_against_github(gh_command: tuple[str, ...], sources: tuple[str, ...], commit: str) -> str:
    """
    Whether the bundle holds the last change to each of its files on cicd's main, as GitHub answers.

    Args:
        gh_command: gh's command
        sources: the bundle's files in cicd
        commit: the bundle's commit

    Returns:
        str: empty when it is current, else behind

    Raises:
        Refusal: when GitHub cannot be asked
    """
    lasts = set()
    for source in sources:
        answer = gh_json(gh_command, f"repos/{CICD}/commits?sha=main&path={source}&per_page=1")
        if not isinstance(answer, list):
            raise Refusal("GitHub's answer for cicd's commits is not a list")
        if answer:
            lasts.add(str(answer[0].get("sha", "")))
    for last in sorted(lasts):
        answer = gh_json(gh_command, f"repos/{CICD}/compare/{last}...{commit}")
        if not isinstance(answer, dict) or answer.get("status") not in ("identical", "ahead"):
            return "behind"
    return ""

# ======================================================================================================================
# --check
# ======================================================================================================================

def check(
    wrapper: types.ModuleType,
    machine: object,
    bundle: Bundle,
    root: Path,
    platform: types.SimpleNamespace,
    gh_command: tuple[str, ...] | None,
    out: TextIO,
) -> int:
    """
    The installed machine checked and printed, the bundle, the launcher, the tools, the Python, the rules, the
    folder's permission and the bundle against cicd's main on GitHub.

    Args:
        wrapper: the bundle's wrapper
        machine: the machine
        bundle: the bundle
        root: the scan folder
        platform: the reads of this machine
        gh_command: gh's command, None when gh is not found
        out: where the lines go

    Returns:
        int: 0 when every check passes, 2 when one fails
    """
    failed = 0
    out.write(f"check     bundle {bundle.commit} manifest ok, {len(bundle.files)} files\n")
    launcher = root / LAUNCHER
    if launcher.is_file() and launcher.read_bytes() == bundle.files["kdf_scan_launcher.py"]:
        out.write("check     launcher ok, the current bundle's own\n")
    else:
        out.write(f"check     FAIL, {LAUNCHER} differs from the current bundle's launcher, the owner reinstalls\n")
        failed += 1
    failed += len(wrapper.check(machine, out))
    problems = platform.acl(root)
    for problem in problems:
        out.write(f"check     FAIL, {problem}\n")
    if not problems:
        out.write("check     permission ok, only an elevated process writes the folder\n")
    failed += len(problems)
    if gh_command is None:
        out.write("check     WARN, the bundle against cicd's main is unknown, gh is not at a protected path\n")
        return 2 if failed else 0
    try:
        behind = bundle_against_github(gh_command, wrapper.BUNDLE_SOURCES, bundle.commit)
    except Refusal as refusal:
        out.write(f"check     WARN, the bundle against cicd's main is unknown, {refusal}\n")
        return 2 if failed else 0
    if behind:
        out.write(f"check     FAIL, the bundle is behind cicd's main, the owner reinstalls with {wrapper.INSTALL}\n")
        failed += 1
    else:
        out.write("check     bundle against cicd's main ok\n")
    return 2 if failed else 0

# ======================================================================================================================
# --pr, the scan before a merge
# ======================================================================================================================

def read_not_docs(text: str) -> list[str] | None:
    """
    The `not_docs` patterns of a caller's ci.yml, a quoted value or a folded block, None when it names none or two.

    Args:
        text: the ci.yml's text

    Returns:
        list[str] | None: the patterns, None when there is no single answer
    """
    lines = text.replace("\r\n", "\n").split("\n")
    found = [(index, NOT_DOCS.fullmatch(line)) for index, line in enumerate(lines)]
    found = [(index, match) for index, match in found if match]
    if len(found) != 1:
        return None
    index, match = found[0]
    value = match["value"]
    if value in (">", ">-", "|", "|-", ">+", "|+"):
        block = []
        for line in lines[index + 1:]:
            if line.strip() and len(line) - len(line.lstrip()) <= len(match["indent"]):
                break
            block.append(line.strip())
        return " ".join(block).split()
    if value[:1] in ("'", '"'):
        closing = value.find(value[0], 1)
        return value[1:closing].split() if closing > 0 else None
    return value.split("#", 1)[0].split()


def pasted(body: str, head: str) -> str:
    """
    How the pull request's pasted last line stands against its head.

    Args:
        body: the pull request's body
        head: the head commit

    Returns:
        str: MATCH, DIFFERS with the commit it names, NOT RUN, or MISSING
    """
    lines = [line.strip().strip("`").strip() for line in body.splitlines()]
    lines = [line for line in lines if line.startswith("kdf-scan ")]
    named = [match["commit"] for match in (PASTED.match(line) for line in lines) if match]
    if named:
        return "MATCH" if head.startswith(named[-1]) else f"DIFFERS, it names {named[-1]}"
    return "NOT RUN" if lines else "MISSING"


def verify(
    wrapper: types.ModuleType,
    ci_paths: types.ModuleType,
    machine: object,
    bundle: Bundle,
    link: str,
    repo: Path,
    gh_command: tuple[str, ...],
    out: TextIO,
) -> int:
    """
    The scan before a merge, the head and main from GitHub, the pasted line compared, docs only by the bundle's own
    ci_paths.py, and the head scanned with main's exclusions and limits.

    Args:
        wrapper: the bundle's wrapper
        ci_paths: the bundle's ci_paths.py
        machine: the machine
        bundle: the bundle
        link: the pull request's link
        repo: the clone
        gh_command: gh's command
        out: where the report goes

    Returns:
        int: the scan's exit code, 0 for a docs only pull request, 2 for a refusal
    """
    def refuse(reason: str) -> int:
        """
        Print a refusal and its last line.

        Args:
            reason: why the verify refuses

        Returns:
            int: 2
        """
        out.write(f"kdf-scan  refused, {reason}\n{REFUSED}\n")
        return 2


    match = PR_LINK.fullmatch(link or "")
    if not match:
        return refuse(f"{link!r} is not a pull request's link, https://github.com/<owner>/<repo>/pull/<number>")
    project, number = f"{match['owner']}/{match['repo']}", match["number"]
    try:
        if bundle_against_github(gh_command, wrapper.BUNDLE_SOURCES, bundle.commit):
            return refuse(f"the bundle {bundle.commit[:12]} is behind cicd's main, the owner reinstalls with "
                          f"{wrapper.INSTALL}")
        answer = gh_json(gh_command, f"repos/{project}/pulls/{number}")
        head   = str(answer["head"]["sha"])
        base   = str(answer["base"]["ref"])
        body   = str(answer.get("body") or "")
        main   = str(gh_json(gh_command, f"repos/{project}/commits/main")["sha"])
    except (Refusal, KeyError, TypeError, AttributeError) as error:
        return refuse(f"GitHub could not be asked, {error}")
    if base != "main":
        return refuse(f"the pull request's base is {base}, and the scan before a merge reads main's policy")
    if not COMMIT.fullmatch(head) or not COMMIT.fullmatch(main):
        return refuse("GitHub's answer names no commit for the head or main")
    git     = machine.git
    fetched = wrapper.run_git(
        git,
        repo,
        "fetch",
        "--no-tags",
        "--quiet",
        "--no-write-fetch-head",
        "origin",
        f"+refs/pull/{number}/head:{HEAD_REF}",
        f"+refs/heads/main:{MAIN_REF}",
    )
    if fetched.returncode != 0:
        return refuse(f"the fetch of the head and main failed, {wrapper.tail(fetched.stderr)}")
    if wrapper.resolve(git, repo, HEAD_REF) != head or wrapper.resolve(git, repo, MAIN_REF) != main:
        return refuse("the fetched head or main is not the commit GitHub names, so nothing here vouches for it")
    out.write(f"verify    {link} head {head[:12]} main {main[:12]} pasted {pasted(body, head)}\n")
    merged   = wrapper.run_git(git, repo, "merge-base", main, head).stdout.decode().strip()
    changed  = wrapper.split_z(
        wrapper.run_git(git, repo, "diff", "--name-only", "--no-renames", "-z", merged or main, head).stdout,
    )
    caller   = wrapper.blob_at(git, repo, main, ".github/workflows/ci.yml")
    patterns = read_not_docs(caller.decode("utf-8", "replace")) if caller else None
    if patterns is not None:
        tracked = wrapper.split_z(wrapper.run_git(git, repo, "ls-tree", "-r", "-z", "--name-only", main).stdout)
        try:
            ci_paths.check_not_docs(patterns, tracked)
            docs = ci_paths.docs_only(changed, patterns)
        except ValueError:
            docs = False
        if docs:
            out.write(f"verify    docs only by the bundle's ci_paths.py, {len(changed)} paths, nothing to scan\n")
            out.write(f"kdf-scan {head[:12]} verify bundle {bundle.commit[:12]}: DOCS-ONLY (exit 0)\n")
            return 0
    return wrapper.scan(machine, repo, out = out, at_commit = head, policy_at = main, base = main)

# ======================================================================================================================
# The CLI
# ======================================================================================================================

def fence(platform: types.SimpleNamespace) -> list[str]:
    """
    The fence's tripwire for this process, a token that cannot be read counted as elevated.

    Args:
        platform: the reads of this machine

    Returns:
        list[str]: each reason the launcher refuses, empty when it goes on
    """
    try:
        elevated = bool(platform.elevated())
    except OSError:
        return ["this process's token could not be read, so the launcher counts it as elevated"]
    try:
        values = platform.uac()
    except OSError:
        return ["UAC's values could not be read"]
    return fence_problems(elevated, values)


def main(
    argv: list[str] | None = None,
    root: Path | None = None,
    platform: types.SimpleNamespace | None = None,
    hooks: Hooks | None = None,
) -> int:
    """
    Refuse an open fence before anything, then scan, check or verify on the current bundle.

    Args:
        argv: the arguments, sys.argv when None
        root: the scan folder, this file's own folder when None
        platform: the reads of this machine, Windows' when None
        hooks: what a test replaces

    Returns:
        int: the exit code, 0 to 4
    """
    problems = fence(platform or windows_platform())
    if problems:
        for problem in problems:
            print(f"kdf-scan  refused, {problem}")
        print("kdf-scan  close any elevated window, start every session from an ordinary one, and keep UAC prompting")
        print(REFUSED)
        return 2
    parser = argparse.ArgumentParser(prog = LAUNCHER, description = "The local code scan (cicd D-084).")
    parser.add_argument("--repo", default = ".", help = "the repo or clone, the current folder by default")
    parser.add_argument("--at", help = "scan this commit's tree, with origin/main's exclusions and limits")
    parser.add_argument("--check", action = "store_true", help = "check the installed machine and print it")
    parser.add_argument("--pr", help = "the scan before a merge, at the pull request's head")
    args  = parser.parse_args(argv)
    root  = root or Path(__file__).resolve().parent
    hooks = hooks or Hooks()
    try:
        bundle  = load_bundle(root)
        wrapper = load_module("kdf_scan_installed", bundle, "kdf_scan.py")
    except Refusal as refusal:
        print(f"kdf-scan  refused, {refusal}\nkdf-scan  the owner's install writes the bundle again")
        print(REFUSED)
        return 2
    try:
        git     = hooks.git or wrapper.find_git()
        machine = (hooks.machine(wrapper, root, bundle) if hooks.machine
                   else wrapper.machine(root, bundle.commit, bundle.files, git))
        command = hooks.gh or (find_gh() if args.pr is not None else None)
    except (Refusal, wrapper.Refusal) as refusal:
        print(f"kdf-scan  refused, {refusal}\n{REFUSED}")
        return 2
    repo = Path(args.repo).resolve()
    if args.check:
        if command is None and any(Path(candidate).is_file() for candidate in GH_PATHS):
            command = find_gh()
        return check(wrapper, machine, bundle, root, platform or windows_platform(), command, sys.stdout)
    if args.pr is not None:
        ci_paths = load_module("ci_paths_installed", bundle, "ci_paths.py")
        return verify(wrapper, ci_paths, machine, bundle, args.pr, repo, command, sys.stdout)
    return wrapper.scan(machine, repo, out = sys.stdout, at_commit = args.at)


if __name__ == "__main__":
    sys.exit(main())
