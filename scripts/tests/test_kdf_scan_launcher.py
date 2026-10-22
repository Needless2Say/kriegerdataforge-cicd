"""
Tests for kdf_scan_launcher.py, the local code scan's launcher, installed as D:/KriegerDataForge-scan/kdf-scan.py
(D-084).

Each test installs a bundle as the install would, into a scan folder under the test's temp folder, its files from this
source tree, its manifest and `current`, and runs the launcher's main with stand ins for its Windows checks, an
elevated token, UAC's values and the folder's permission, and with the rig's stand in tools. The launcher's own reads
of a token and a security descriptor run on Windows alone, where the owner's machines and these tests meet them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from tests.scan_fakes import (
    COMMIT,
    COMMON,
    FAKE_GH,
    GIT,
    PYTHON,
    bundle_files,
    install_bundle,
    load,
    make_rig,
    platform,
    program,
)

SCAN     = load("kdf_scan", COMMON / "kdf_scan.py")
LAUNCHER = load("kdf_scan_launcher", COMMON / "kdf_scan_launcher.py")
OTHER    = "d" * 40
# UAC's values that leave the fence open, each alone over Windows' defaults
OPEN_UAC = [
    {"EnableLUA": 0},
    {"ConsentPromptBehaviorAdmin": 0},
    {"PromptOnSecureDesktop": 0},
    {"PromptOnSecureDesktop": 0, "ConsentPromptBehaviorAdmin": 4},
]
# the SIDs and masks of design 5.1's permission, and the folder's three grants
ADMINS    = "S-1-5-32-544"
SYSTEM    = "S-1-5-18"
USERS     = "S-1-5-32-545"
OWNER     = "S-1-5-21-1-2-3-1001"
FULL      = 0x1F01FF
READ_RUN  = 0x1200A9
GOOD_ROOT = [
    LAUNCHER.Ace(0, 3, FULL, ADMINS),
    LAUNCHER.Ace(0, 3, FULL, SYSTEM),
    LAUNCHER.Ace(0, 3, READ_RUN, USERS),
]

pytestmark = pytest.mark.skipif(GIT is None, reason = "the launcher's tests need git")


def hooks(rig, gh: dict | None = None, changes: dict | None = None):
    """
    The launcher's hooks, the rig's machine built from the wrapper the launcher loaded, git, and a stand in gh.
    """
    program(rig.tools / "gh.py", FAKE_GH)
    answers = {"repos/Needless2Say/kriegerdataforge-cicd/commits": [{"sha": COMMIT}]}
    answers["repos/Needless2Say/kriegerdataforge-cicd/compare"] = {"status": "identical"}
    answers.update(gh or {})
    (rig.tools / "gh.json").write_text(json.dumps({"answers": answers}), encoding = "utf-8")


    def machine(wrapper, root, bundle):
        values = {"bundle": bundle.commit, "files": bundle.files, "root": root}
        values.update(changes or {})
        return rig.machine_for(wrapper, **values)


    return LAUNCHER.Hooks(machine = machine, gh = (str(PYTHON), str(rig.tools / "gh.py")), git = GIT)


@pytest.fixture()
def rig(tmp_path: Path):
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n", ".github/workflows/ci.yml": "name: CI\n"})
    install_bundle(rig.base, bundle_files())
    return rig


def launch(rig, *args: str, fence = None, **options) -> int:
    return LAUNCHER.main(
        ["--repo", str(rig.repo), *args],
        root = rig.base,
        platform = fence or platform(),
        hooks = options.pop("hooks", None) or hooks(rig),
    )

# ======================================================================================================================
# the fence, before anything
# ======================================================================================================================

@pytest.mark.parametrize("mode", [[], ["--check"], ["--pr", "https://github.com/Needless2Say/x/pull/1"]])
@pytest.mark.parametrize("fence", [{"elevated": True}, *({"uac": values} for values in OPEN_UAC)])
def test_an_elevated_process_or_an_open_uac_value_refuses_before_anything(
    rig,
    capsys: pytest.CaptureFixture[str],
    mode: list[str],
    fence: dict,
) -> None:
    (rig.base / "current").unlink()
    code = launch(rig, *mode, fence = platform(**fence))
    out  = capsys.readouterr().out
    assert code == 2, out
    assert out.rstrip().splitlines()[-1].endswith("REFUSED (exit 2)")
    assert "current" not in out
    assert rig.calls("opengrep") == [] and rig.calls("zizmor") == []


@pytest.mark.parametrize("values", [
    {},
    {"EnableLUA": 1, "ConsentPromptBehaviorAdmin": 5, "PromptOnSecureDesktop": 1},
    {"ConsentPromptBehaviorAdmin": 1, "PromptOnSecureDesktop": 0},
    {"ConsentPromptBehaviorAdmin": 2, "PromptOnSecureDesktop": 0},
    {"ConsentPromptBehaviorAdmin": 3, "PromptOnSecureDesktop": 1},
])
def test_windows_defaults_and_every_closed_uac_value_pass_the_fence(values: dict) -> None:
    assert LAUNCHER.fence_problems(False, values) == []


def test_each_open_uac_value_and_an_elevated_token_is_named() -> None:
    assert any("elevated" in line for line in LAUNCHER.fence_problems(True, {}))
    assert any("EnableLUA" in line for line in LAUNCHER.fence_problems(False, {"EnableLUA": 0}))
    assert any("ConsentPromptBehaviorAdmin" in line for line in LAUNCHER.fence_problems(False, OPEN_UAC[1]))
    assert any("PromptOnSecureDesktop" in line for line in LAUNCHER.fence_problems(False, OPEN_UAC[2]))


def test_a_token_that_cannot_be_read_counts_as_elevated(rig, capsys: pytest.CaptureFixture[str]) -> None:
    def unreadable() -> bool:
        raise OSError("no token")


    fence          = platform()
    fence.elevated = unreadable
    assert launch(rig, fence = fence) == 2

# ======================================================================================================================
# the bundle and its manifest
# ======================================================================================================================

def test_a_scan_through_the_launcher_runs_the_current_bundle(rig, capsys: pytest.CaptureFixture[str]) -> None:
    code = launch(rig)
    out  = capsys.readouterr().out
    assert code == 0, out
    assert f" bundle {COMMIT[:12]} " in out.splitlines()[-1]


@pytest.mark.parametrize("damage", ["edit", "stray", "missing", "outside"])
def test_a_bundle_unlike_its_manifest_is_refused(rig, capsys: pytest.CaptureFixture[str], damage: str) -> None:
    folder = rig.base / "bundles" / COMMIT
    if damage == "edit":
        (folder / "kdf_zizmor.yml").write_bytes(b"rules: {}\n")
    elif damage == "stray":
        (folder / "scan_rules" / "stray.yaml").write_bytes(b"rules: []\n")
    elif damage == "missing":
        (folder / "ci_paths.py").unlink()
    else:
        manifest = folder / "manifest.sha256"
        manifest.write_text(manifest.read_text() + f"{'0' * 64}  ../escape.py\n")
    code = launch(rig)
    out  = capsys.readouterr().out
    assert code == 2, out
    assert "manifest" in out
    assert rig.calls("opengrep") == []


@pytest.mark.parametrize("content", ["", "not a commit\n", f"{OTHER}\n", f"{COMMIT}\n{OTHER}\n"])
def test_a_current_file_that_names_no_installed_bundle_is_refused(rig, content: str) -> None:
    (rig.base / "current").write_text(content)
    assert launch(rig) == 2


def test_current_is_read_once_though_it_changes_mid_run(rig, capsys: pytest.CaptureFixture[str]) -> None:
    other = bundle_files()
    other["kdf_zizmor.yml"] = other["kdf_zizmor.yml"] + b"# another bundle\n"
    install_bundle(rig.base, other, OTHER, current = False)
    plain = hooks(rig)


    def switching(wrapper, root, bundle):
        (root / "current").write_text(f"{OTHER}\n")
        return plain.machine(wrapper, root, bundle)


    code = launch(rig, hooks = LAUNCHER.Hooks(machine = switching, gh = plain.gh, git = GIT))
    out  = capsys.readouterr().out
    assert code == 0, out
    assert f" bundle {COMMIT[:12]} " in out.splitlines()[-1]


def test_the_wrapper_runs_from_the_bytes_the_manifest_checked(rig) -> None:
    bundle = LAUNCHER.load_bundle(rig.base)
    module = LAUNCHER.load_module("kdf_scan_installed", bundle, "kdf_scan.py")
    assert module.__file__ == str(rig.base / "bundles" / COMMIT / "kdf_scan.py")
    assert module.RULES_COMMIT == SCAN.RULES_COMMIT
    assert "kdf_scan_installed" in sys.modules

# ======================================================================================================================
# --check
# ======================================================================================================================

def test_check_prints_the_bundle_the_launcher_the_pins_and_the_permission(
    rig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = launch(rig, "--check")
    out  = capsys.readouterr().out
    assert code == 0, out
    assert f"bundle {COMMIT} manifest ok" in out
    assert "launcher ok" in out and "permission ok" in out and "against cicd's main ok" in out
    assert "opengrep 1.30.2 sha256 ok" in out and "digest ok" in out


@pytest.mark.parametrize("trouble", ["acl", "launcher", "behind", "pin"])
def test_check_fails_on_each_problem(rig, capsys: pytest.CaptureFixture[str], trouble: str) -> None:
    fence   = platform(acl = ["D:/scan lets Users write"] if trouble == "acl" else [])
    gh      = {"repos/Needless2Say/kriegerdataforge-cicd/compare": {"status": "behind"}} if trouble == "behind" else {}
    changes = {"rules_digest": "0" * 64} if trouble == "pin" else {}
    if trouble == "launcher":
        (rig.base / "kdf-scan.py").write_bytes(b"print('another launcher')\n")
    code = launch(rig, "--check", fence = fence, hooks = hooks(rig, gh, changes))
    out  = capsys.readouterr().out
    assert code == 2, out
    assert "FAIL" in out


def test_check_only_warns_when_github_cannot_be_asked(rig, capsys: pytest.CaptureFixture[str]) -> None:
    gh   = {"repos/Needless2Say/kriegerdataforge-cicd/commits": None}
    code = launch(rig, "--check", hooks = hooks(rig, gh))
    out  = capsys.readouterr().out
    assert code == 0, out
    assert "WARN" in out

# ======================================================================================================================
# the folder's permission
# ======================================================================================================================

def test_the_designs_permission_on_the_folder_passes() -> None:
    assert LAUNCHER.acl_findings("root", ADMINS, True, GOOD_ROOT, root = True) == []
    assert LAUNCHER.acl_findings("file", SYSTEM, False, GOOD_ROOT, root = False) == []


@pytest.mark.parametrize(("owner", "protected", "aces", "root"), [
    (OWNER, True, GOOD_ROOT, True),
    (OWNER, False, GOOD_ROOT, False),
    (ADMINS, False, GOOD_ROOT, True),
    (ADMINS, True, [*GOOD_ROOT, LAUNCHER.Ace(0, 0, 0x2, USERS)], True),
    (ADMINS, True, [*GOOD_ROOT, LAUNCHER.Ace(0, 11, 0x40000000, OWNER)], False),
    (ADMINS, True, [*GOOD_ROOT, LAUNCHER.Ace(0, 0, 0x40000, "S-1-1-0")], False),
    (ADMINS, True, GOOD_ROOT[:2], True),
])
def test_a_weaker_permission_is_named(owner: str, protected: bool, aces: list, root: bool) -> None:
    assert LAUNCHER.acl_findings("x", owner, protected, aces, root = root)


def test_a_deny_entry_is_never_read_as_a_grant() -> None:
    aces = [*GOOD_ROOT, LAUNCHER.Ace(1, 0, FULL, USERS)]
    assert LAUNCHER.acl_findings("root", ADMINS, True, aces, root = True) == []


@pytest.mark.skipif(sys.platform != "win32", reason = "reads a Windows security descriptor")
def test_a_folder_this_user_owns_is_read_and_refused(tmp_path: Path) -> None:
    owner, _protected, aces = LAUNCHER.read_security(tmp_path)
    assert owner.startswith("S-1-5-") and aces
    assert any("owned by" in line for line in LAUNCHER.acl_problems(tmp_path))


@pytest.mark.skipif(sys.platform != "win32", reason = "reads a Windows token and UAC's values")
def test_this_test_process_reads_its_token_and_uac() -> None:
    assert LAUNCHER.token_elevated() in (True, False)
    assert set(LAUNCHER.read_uac()) == {"EnableLUA", "ConsentPromptBehaviorAdmin", "PromptOnSecureDesktop"}
