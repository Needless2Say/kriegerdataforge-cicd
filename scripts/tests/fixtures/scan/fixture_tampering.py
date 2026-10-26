"""
Tampering, design 5.9's fourth part, each refused or changing nothing. An image built on the one under test with an
edited Opengrep or zizmor, each refused by its pin, the image under test scanning clean as the control. A rules' cache
that lacks the pinned commit, refused and naming `make scan-setup`. A stray rule file in the cache and a replacement
ref over a rule, changing nothing, since the rules are read from the pinned commit's raw blobs. SEMGREP_RULES set,
changing nothing. Each runs on a copy of the cache, never the one `make scan-setup` keeps.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from scanfix import Machine, git, installed, make_repo, pin, scan

PRINT_RULE = (
    "rules:\n- id: every-print\n  languages: [python]\n  message: a print\n  severity: ERROR\n"
    "  metadata:\n    category: security\n    confidence: HIGH\n  pattern: print(...)\n"
)
# a Dockerfile building on the image under test with one of its programs changed by a byte, as root, then the scan's
# user again
EDITED = "FROM {image}\nUSER 0:0\nRUN printf '\\0' >> /opt/kdf-scan/bin/{program}\nUSER 65532:65532\n"


@pytest.fixture(scope = "module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_repo(tmp_path_factory.mktemp("tamper") / "repo", {"src/app.py": "print(1)\n"})


@pytest.fixture()
def cache(tmp_path: Path) -> Machine:
    """
    A copy of the rules' cache, so a fixture's change never reaches the one make scan-setup keeps.
    """
    machine = installed()
    copy    = tmp_path / "semgrep-rules.git"
    shutil.copytree(machine.rules, copy)
    return Machine(machine.image, copy)


def test_the_image_scans_clean_before_any_change(repo: Path) -> None:
    assert scan(installed(), repo).result == "CLEAN"


@pytest.mark.parametrize("program", ["opengrep", "zizmor"])
def test_an_image_with_an_edited_program_is_refused(repo: Path, tmp_path: Path, program: str) -> None:
    machine = installed()
    (tmp_path / "Dockerfile").write_text(EDITED.format(image = machine.image, program = program), encoding = "utf-8")
    tag   = f"kdf-scan-tampered-{program}:fixture"
    built = subprocess.run(
        ["docker", "build", "--quiet", "--tag", tag, str(tmp_path)],
        capture_output = True,
        check = False,
    )
    assert built.returncode == 0, built.stderr.decode("utf-8", "replace")
    try:
        result = scan(Machine(tag, machine.rules), repo)
        assert result.result == "REFUSED" and result.last["code"] == "2", result.text
        assert program in result.text
    finally:
        subprocess.run(["docker", "rmi", "--force", tag], capture_output = True, check = False)


def test_a_cache_without_the_pinned_commit_is_refused_and_names_the_setup(repo: Path, tmp_path: Path) -> None:
    empty = tmp_path / "empty.git"
    git(tmp_path, "init", "-q", "--bare", str(empty))
    result = scan(Machine(installed().image, empty), repo)
    assert result.result == "REFUSED" and "make scan-setup" in result.text, result.text


def test_a_stray_rule_file_in_the_cache_changes_nothing(cache: Machine, repo: Path) -> None:
    folder = cache.rules / "python" / "lang" / "security"
    folder.mkdir(parents = True)
    (folder / "every-print.yaml").write_text(PRINT_RULE, encoding = "utf-8")
    assert scan(cache, repo).result == "CLEAN"


def test_a_replacement_ref_over_a_rule_changes_nothing(cache: Machine, repo: Path, tmp_path: Path) -> None:
    listed = git(cache.rules, "ls-tree", "-r", pin("RULES_COMMIT"), "--", "python/lang/security").splitlines()
    blob   = next(line.split()[2] for line in listed if line.split("\t")[-1].endswith(".yaml"))
    source = tmp_path / "print-rule.yaml"
    source.write_text(PRINT_RULE, encoding = "utf-8")
    swap = git(cache.rules, "hash-object", "-w", str(source))
    git(cache.rules, "replace", blob, swap)
    assert scan(cache, repo).result == "CLEAN"


def test_semgrep_rules_in_the_environment_changes_nothing(repo: Path) -> None:
    result = scan(installed(), repo, env = {"SEMGREP_RULES": "/src/src"})
    assert result.result == "CLEAN", result.text
