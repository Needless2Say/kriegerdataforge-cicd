"""
``scripts/common/mutation_runner.py``, the shared engine that proves each hand written mutant is killed (D-040).

A runner that miscounts is worse than none, a survived mutant read as killed says a rule is pinned when nothing pins
it. So the reading of pytest's exit is pinned, a green run that ran nothing is not a survivor and a timeout is not a
kill, as is the anchor matched under either line ending and refused when missing or repeated, the table refused when
malformed, and the working tree's changes found in git's own output, a rename's both sides included.

The engine came from the SDK's runner of its review's slice S1, and so did these cases, each pointed at a repository
made for it instead of the SDK. A repo's own tables, and the gate and Makefile that name them, are held by the repo's
own tests. What one repo's unit suite needs, it says in ``mutation_tests/__init__.py``, which is pinned here too.
"""

from __future__ import annotations

# standard imports
import ast
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# third party imports
import pytest
from common import mutation_runner as run

# ======================================================================================================================
# Constants
# ======================================================================================================================

# a file every repo made for a case holds, a valid entry names it
A_FILE: str = "pkg/rule.py"

# the rule that file holds, and its test
RULE: str = 'def allowed(user):\n    return user == "owner"\n'
TEST: str = (
    "import os\n"
    "from pkg.rule import allowed\n"
    "def test_only_the_owner_is_allowed():\n"
    '    assert os.environ.get("KDF_DEMO") == "set by the repo"\n'
    '    assert allowed("owner") and not allowed("guest")\n'
)

# the repo the engine found from its own seat, read when this file is imported, before any case points it elsewhere
SEAT_ROOT: Path = run.REPO_ROOT

# ======================================================================================================================
# Helpers
# ======================================================================================================================

def _forget_tables() -> None:
    """
    Drop every ``mutation_tests`` module a case imported, each case's repo holds its own.
    """
    for name in [name for name in sys.modules if name == "mutation_tests" or name.startswith("mutation_tests.")]:
        del sys.modules[name]


@pytest.fixture(autouse = True)
def _a_folder_of_this_case_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Every case runs the engine for a folder of its own, which holds no repo until a case makes one, and the import
    path the engine adds to and the tables it imports are put back after. A folder on the path that holds tables of
    its own, this repo's root when its lane runs these cases, is left off, or a case would read those.
    """
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if not Path(entry or ".", "mutation_tests").is_dir()])
    monkeypatch.setattr(run, "REPO_ROOT", (tmp_path / "no-repo").resolve())
    _forget_tables()
    yield
    _forget_tables()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    A repo made for one case, a rule, its test and an empty tables package, the engine's root pointed at it.
    """
    root = (tmp_path / "the-repo").resolve()
    (root / "pkg").mkdir(parents = True)
    (root / "tests").mkdir()
    (root / "mutation_tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding = "utf-8")
    (root / "pkg" / "rule.py").write_text(RULE, encoding = "utf-8")
    (root / "tests" / "test_rule.py").write_text(TEST, encoding = "utf-8")
    _write_package(root, '"""\nThe tables.\n"""\n')
    monkeypatch.setattr(run, "REPO_ROOT", root)
    return root


def _entry(**changes: object) -> dict[str, object]:
    """
    One valid table entry, with any field replaced.
    """
    entry: dict[str, object] = {
        "id": "T-M-1",
        "rule": "a rule",
        "file": A_FILE,
        "anchor": 'return user == "owner"',
        "replacement": "return True",
        "suite": "unit",
        "tests": ["tests/test_rule.py"],
    }
    entry.update(changes)
    return entry


def _mutant(anchor: str, replacement: str) -> run.Mutant:
    """
    A mutant carrying only what ``apply_mutant`` reads.
    """
    return run.Mutant("T-M-1", "a rule", "file.py", anchor, replacement, "unit", ("tests",))


def _write_package(repo: Path, body: str) -> None:
    """
    The repo's ``mutation_tests/__init__.py``, holding what a case gives it.
    """
    (repo / "mutation_tests" / "__init__.py").write_text(body, encoding = "utf-8")
    importlib.invalidate_caches()


def _write_table(repo: Path, table: list[dict[str, object]]) -> None:
    """
    The repo's lane ``demo``, the table a case gives it.
    """
    (repo / "mutation_tests" / "demo.py").write_text(f"MUTANTS = {table!r}\n", encoding = "utf-8")
    importlib.invalidate_caches()

# ======================================================================================================================
# The Seat
# ======================================================================================================================

class TestTheEngineFindsItsRepo:
    """
    The engine sits two folders down from the repo it runs for, at ``scripts/kdf_scripts/`` in a repo and at
    ``scripts/common/`` here, and reads that repo's tables and runs git there.
    """
    def test_the_repo_is_two_folders_up_from_the_engine(self):
        assert (SEAT_ROOT / "scripts" / "common" / "mutation_runner.py").is_file()

# ======================================================================================================================
# The Table
# ======================================================================================================================

class TestTheTableIsValidatedBeforeAnythingRuns:
    """
    A malformed table is refused whole, before any worktree or pytest run.
    """
    def test_a_valid_entry_becomes_a_mutant(self, repo):
        mutants = run.parse_mutants([_entry(bundle = True)], repo)
        assert mutants == [
            run.Mutant(
                "T-M-1",
                "a rule",
                A_FILE,
                'return user == "owner"',
                "return True",
                "unit",
                ("tests/test_rule.py",),
                True,
                None,
            ),
        ]


    @pytest.mark.parametrize(
        ("entries", "message"),
        [
            ([], "non empty list"),
            ({"id": "x"}, "non empty list"),
            (["not a dict"], "is not a dict"),
            ([{"id": "T-M-1"}], "lacks"),
            ([_entry(extra = 1)], "unknown keys"),
            ([_entry(tests = [])], "needs tests"),
            ([_entry(tests = "tests")], "needs tests"),
            ([_entry(rule = " ")], "needs rule"),
            ([_entry(replacement = 'return user == "owner"')], "differs from its anchor"),
            ([_entry(), _entry()], "appears twice"),
            ([_entry(suite = "e2e")], "names suite"),
            ([_entry(platform = "windows")], "names platform"),
            ([_entry(platform = "")], "names platform"),
            ([_entry(file = "pkg/no_such_module.py")], "is not a file"),
        ],
    )
    def test_a_malformed_table_is_refused(self, repo, entries, message):
        with pytest.raises(run.MutantTableError, match = message):
            run.parse_mutants(entries, repo)


    @pytest.mark.parametrize(
        "named",
        ["the-file-s-own-absolute-path", "../outside.py", "pkg/../../outside.py", "/etc/passwd"],
    )
    def test_a_file_that_is_not_inside_the_repo_is_refused(self, repo, named: str):
        """
        ``file`` is repo relative. An absolute path takes the place of the worktree in ``worktree / file``, so a
        mutant that names the checkout's own copy of a file by its absolute path was written into that live file.
        """
        if named == "the-file-s-own-absolute-path":
            named = str(repo / A_FILE)
        with pytest.raises(run.MutantTableError, match = "is not a path inside the repo"):
            run.parse_mutants([_entry(file = named)], repo)


    def test_a_file_that_is_a_link_out_of_the_repo_is_refused_and_never_written(self, tmp_path: Path):
        """
        A relative path with no parent in it can still leave the repo through a link. The table refuses it, and
        the runner asks again where the write would land before it writes.
        """
        repo, outside = tmp_path / "repo", tmp_path / "outside.py"
        repo.mkdir()
        outside.write_text("VALUE = 1\n", encoding = "utf-8")
        try:
            (repo / "link.py").symlink_to(outside)
        except OSError:
            pytest.skip("this machine cannot make a symbolic link, the CI runner can")
        mutant = run.Mutant("T-M-1", "a rule", "link.py", "VALUE = 1", "VALUE = 2", "unit", ("tests",))

        with pytest.raises(run.MutantTableError, match = "is not a path inside the repo"):
            run.parse_mutants([_entry(file = "link.py")], repo)
        assert run.run_mutant(repo, mutant, 5).result == "error, its file leads out of the worktree"
        assert outside.read_text(encoding = "utf-8") == "VALUE = 1\n"


    @pytest.mark.parametrize("lane", ["../core", "Core", "core-lane", ""])
    def test_a_lane_that_is_not_a_module_name_is_refused(self, repo, lane):
        with pytest.raises(run.MutantTableError, match = "not a module name"):
            run.load_table(lane)


    def test_a_lane_without_a_table_is_refused(self, repo):
        with pytest.raises(run.MutantTableError, match = "there is no mutation_tests/no_such_lane.py"):
            run.load_table("no_such_lane")


    def test_a_lane_s_table_is_read_from_the_repo_the_engine_runs_for(self, repo):
        _write_table(repo, [_entry()])

        assert [mutant.id for mutant in run.load_table("demo")] == ["T-M-1"]

# ======================================================================================================================
# Applying A Mutant
# ======================================================================================================================

class TestTheAnchorMatchesOnceUnderEitherLineEnding:
    """
    An anchor is replaced only when it occurs exactly once, whatever the file's line endings.
    """
    def test_a_single_line_anchor_is_replaced(self):
        mutated, status = run.apply_mutant("a = 1\nb = 2\n", _mutant("b = 2", "b = 3"))
        assert (mutated, status) == ("a = 1\nb = 3\n", "applied")


    def test_a_multi_line_anchor_written_with_lf_matches_a_crlf_file(self):
        mutated, status = run.apply_mutant(
            "if x:\r\n    return 1\r\n",
            _mutant("if x:\n    return 1", "if x:\n    return 2"),
        )
        assert (mutated, status) == ("if x:\r\n    return 2\r\n", "applied")


    def test_a_missing_anchor_is_stale(self):
        assert run.apply_mutant("a = 1\n", _mutant("b = 2", "b = 3")) == (None, "stale")


    def test_a_repeated_anchor_is_ambiguous(self):
        assert run.apply_mutant("b = 2\nb = 2\n", _mutant("b = 2", "b = 3")) == (None, "ambiguous")

# ======================================================================================================================
# Reading pytest
# ======================================================================================================================

class TestOnlyARedRunIsAKill:
    """
    pytest's exit status reads as a kill only when the tests ran and failed.
    """
    @pytest.mark.parametrize(
        ("returncode", "output", "result"),
        [
            (1, "1 failed, 3 passed in 1.0s", "killed"),
            (0, "4 passed in 1.0s", "survived"),
            (0, "4 skipped in 0.1s", "error, no test ran"),
            (5, "no tests ran in 0.1s", "error, no test collected"),
            (2, "1 error in 0.2s", "error, pytest exited 2"),
            (None, "", "timeout"),
        ],
    )
    def test_each_exit_reads_as(self, returncode, output, result):
        assert run.classify(returncode, output) == result

# ======================================================================================================================
# The Working Tree
# ======================================================================================================================

class TestEveryChangedPathIsFound:
    """
    The worktree receives every path git reports as changed, so it matches the working tree.
    """
    def test_modified_added_deleted_and_both_sides_of_a_rename(self):
        porcelain = b" M pkg/rule.py\0?? tests/test_new.py\0 D old.py\0R  new_name.py\0old_name.py\0"
        assert run.changed_paths(porcelain) == [
            "pkg/rule.py",
            "tests/test_new.py",
            "old.py",
            "new_name.py",
            "old_name.py",
        ]


    def test_a_path_with_spaces_is_kept_whole(self):
        assert run.changed_paths(b"?? docs/a file.md\0") == ["docs/a file.md"]


    def test_empty_output_finds_nothing(self):
        assert run.changed_paths(b"") == []

# ======================================================================================================================
# The Environment
# ======================================================================================================================

class TestADatabaseSuiteNeedsItsDatabase:
    """
    A suite that skips without its database is refused before it can read as a survivor.
    """
    @pytest.mark.parametrize(
        ("suite", "variable"),
        [("integration", "KDF_TEST_DATABASE_URL"), ("system", "KDF_SYSTEM_DATABASE_URL")],
    )
    def test_an_unset_database_is_refused(self, monkeypatch, suite, variable):
        monkeypatch.delenv(variable, raising = False)
        with pytest.raises(run.MutantTableError, match = variable):
            run.suite_environment(suite)


    def test_the_unit_suite_gets_a_deterministic_profile(self, repo):
        assert run.suite_environment("unit")["HYPOTHESIS_PROFILE"] == "ci"


class TestTheRepoSaysWhatItsUnitSuiteNeeds:
    """
    The engine knows no repo's settings. The SDK's unit suite needs two values, the hub's a signing keypair as well, a
    backend's its own, each what that repo's ``make ci-unit-tests`` exports. Each repo says so in its tables package,
    and a unit run without them is a red control and no mutant result at all.
    """
    def test_a_repo_whose_package_says_nothing_gives_its_unit_suite_nothing_more(self, repo, monkeypatch):
        monkeypatch.delenv("KDF_DEMO", raising = False)

        assert run.unit_settings({}) == {}
        assert "KDF_DEMO" not in run.suite_environment("unit")


    def test_a_repo_without_a_tables_package_gives_nothing(self, repo):
        (repo / "mutation_tests" / "__init__.py").unlink()
        (repo / "mutation_tests").rmdir()
        importlib.invalidate_caches()

        assert run.unit_settings({}) == {}


    def test_the_repo_s_settings_reach_the_unit_suite_and_no_other(self, repo, monkeypatch):
        _write_package(repo, 'def unit_settings(environment):\n    return {"KDF_DEMO": "set by the repo"}\n')
        monkeypatch.delenv("KDF_DEMO", raising = False)
        monkeypatch.setenv("KDF_TEST_DATABASE_URL", "postgresql+psycopg2://lane/own")

        assert run.suite_environment("unit")["KDF_DEMO"] == "set by the repo"
        assert "KDF_DEMO" not in run.suite_environment("integration")


    def test_the_repo_reads_the_environment_and_changes_nothing_in_it(self, repo):
        """
        The hub makes a keypair only when the process holds none, so the function reads what the suite would get.
        """
        _write_package(repo, "\n".join([
            "def unit_settings(environment):",
            '    seen = environment.get("HYPOTHESIS_PROFILE", "")',
            "    environment.clear()",
            '    return {"KDF_SEEN": seen}',
            "",
        ]))
        env = run.suite_environment("unit")

        assert env["KDF_SEEN"] == "ci"
        assert env["PYTHONDONTWRITEBYTECODE"] == "1", "the function was handed a copy"


    @pytest.mark.parametrize("returned", ['{"KDF_DEMO": 1}', '{1: "x"}', '["KDF_DEMO"]', "None"])
    def test_settings_that_are_not_names_mapped_to_strings_are_refused(self, repo, returned):
        _write_package(repo, f"def unit_settings(environment):\n    return {returned}\n")

        with pytest.raises(run.MutantTableError, match = "must return names mapped to strings"):
            run.suite_environment("unit")


    def test_a_module_the_package_needs_that_is_missing_is_the_repo_s_error(self, repo):
        _write_package(repo, "import kdf_no_such_module_anywhere\n")

        with pytest.raises(ModuleNotFoundError, match = "kdf_no_such_module_anywhere"):
            run.unit_settings({})


    def test_a_run_stops_before_any_worktree_when_the_settings_are_refused(self, repo, tmp_path, capsys):
        _write_package(repo, 'def unit_settings(environment):\n    return {"KDF_DEMO": 1}\n')
        _write_table(repo, [_entry()])
        worktree = tmp_path / "kdf-mutation" / "repo" / "demo"

        assert run.main(["--lane", "demo", "--worktree", str(worktree)]) == 2

        assert "must return names mapped to strings" in capsys.readouterr().out
        assert not worktree.exists()


    def test_the_repo_s_function_reads_the_narrowed_environment(self, repo, monkeypatch):
        """
        The hub's function makes a keypair only when the environment it is handed holds none, so it is handed what the
        suite gets, never this process's whole environment.
        """
        _write_package(repo, "\n".join([
            "def unit_settings(environment):",
            '    return {"KDF_SEEN": environment.get("PYTEST_ADDOPTS", "nothing")}',
            "",
        ]))
        monkeypatch.setenv("PYTEST_ADDOPTS", "-k nothing_matches_this")

        assert run.suite_environment("unit")["KDF_SEEN"] == "nothing"


    @pytest.mark.parametrize(
        "name",
        [
            "PYTHONDONTWRITEBYTECODE",
            "PYTHONUTF8",
            "HYPOTHESIS_PROFILE",
            "KDF_TEST_DATABASE_URL",
            "KDF_SYSTEM_DATABASE_URL",
            "PYTHONPATH",
            "pythonpath",
        ],
    )
    def test_a_name_the_engine_sets_is_refused_from_the_repo(self, repo, name):
        """
        A repo that set one would undo what every run is promised, bytecode written, another database, another import
        path. Windows reads a name in any case, so a name in another case is the same name.
        """
        _write_package(repo, f'def unit_settings(environment):\n    return {{"{name}": "set by the repo"}}\n')

        with pytest.raises(run.MutantTableError, match = f"may not set {name}"):
            run.suite_environment("unit")


    def test_a_bundle_mutant_s_settings_are_judged_before_any_worktree(self, repo, tmp_path, monkeypatch, capsys):
        """
        A bundle mutant's compactor runs with the unit suite's environment whatever the mutant's suite, so a run of a
        system mutant alone still has the repo's unit settings judged before a worktree is made.
        """
        _write_package(repo, 'def unit_settings(environment):\n    return {"PYTHONPATH": "the checkout"}\n')
        _write_table(repo, [_entry(suite = "system", bundle = True)])
        monkeypatch.setenv("KDF_SYSTEM_DATABASE_URL", "postgresql+psycopg2://lane/system")
        worktree = tmp_path / "kdf-mutation" / "repo" / "demo"

        assert run.main(["--lane", "demo", "--worktree", str(worktree)]) == 2

        assert "may not set PYTHONPATH" in capsys.readouterr().out
        assert not worktree.exists()


class TestTheCallersShellSteersNoRun:
    """
    The control and every mutant are handed the platform's names of this process's environment and nothing else
    (D-063). A shell's ``PYTEST_ADDOPTS`` with ``-W error`` or a plugin's timeout made a mutant's run exit 1, a kill no
    test made, ``PYTHONOPTIMIZE`` stripped every assert so a kill became a survivor, and libpq's ``PGHOSTADDR``, a
    dotenv path or a database URL named a database to a suite.
    """
    # what a developer's shell or a runner's job can hold, none of it the platform's own
    STEERING: tuple[str, ...] = (
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTHONHOME",
        "PYTHONOPTIMIZE",
        "PYTHONWARNINGS",
        "PYTHONSTARTUP",
        "COV_CORE_SOURCE",
        "COVERAGE_PROCESS_START",
        "PGHOSTADDR",
        "DB_DATABASE_URL",
        "APP_ENV_FILE",
        "ENVIRONMENT",
        "GIT_CONFIG_COUNT",
        "KDF_ANY_OTHER_NAME",
    )


    @pytest.fixture(autouse = True)
    def _both_databases(self, monkeypatch):
        monkeypatch.setenv("KDF_TEST_DATABASE_URL", "postgresql+psycopg2://lane/integration")
        monkeypatch.setenv("KDF_SYSTEM_DATABASE_URL", "postgresql+psycopg2://lane/system")


    def test_the_platform_s_names_are_held_name_by_name(self):
        """
        The kdf-sdk consumer check's list, copied, so a name added there is added here by hand.
        """
        assert frozenset({
            "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR", "LD_LIBRARY_PATH",
            "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE",
            "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "ALLUSERSPROFILE", "PROGRAMFILES",
            "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "COMMONPROGRAMW6432",
            "USERNAME", "USERDOMAIN", "COMPUTERNAME", "OS", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "CI",
            "GITHUB_ACTIONS",
        }) == run.PLATFORM_VARIABLES
        assert run.RUNNER_SIGNALS == {"CI", "GITHUB_ACTIONS"} <= run.PLATFORM_VARIABLES


    @pytest.mark.parametrize("suite", sorted(run.SUITES))
    def test_a_name_of_the_caller_s_shell_reaches_no_suite(self, repo, monkeypatch, suite):
        for name in self.STEERING:
            monkeypatch.setenv(name, "set by the shell")

        env = run.suite_environment(suite)

        assert sorted(set(self.STEERING) & set(env)) == []


    @pytest.mark.parametrize("suite", sorted(run.SUITES))
    def test_the_platform_s_names_and_a_runner_s_signal_are_handed_on(self, repo, monkeypatch, suite):
        monkeypatch.setenv("TZ", "UTC")
        monkeypatch.setenv("CI", "true")

        env = run.suite_environment(suite)

        assert (env["TZ"], env["CI"], env["PATH"]) == ("UTC", "true", os.environ["PATH"])


    def test_each_suite_is_handed_its_own_database_and_no_other(self, repo):
        databases = set(run._SUITE_DATABASE_VARIABLE.values())

        assert databases & set(run.suite_environment("unit")) == set()
        assert databases & set(run.suite_environment("integration")) == {"KDF_TEST_DATABASE_URL"}
        assert databases & set(run.suite_environment("system")) == {"KDF_SYSTEM_DATABASE_URL"}


    def test_the_compactor_is_handed_the_unit_suite_s_environment(self, repo, tmp_path, monkeypatch):
        """
        A bundle mutant regenerates the bundle before its tests run, and the compactor is a child like any suite. The
        repo's compactor here writes down the names it was handed.
        """
        (repo / "scripts").mkdir()
        (repo / "scripts" / "vercel_compactor.py").write_text(
            "import json, os\nopen('handed.json', 'w', encoding = 'utf-8').write(json.dumps(sorted(os.environ)))\n",
            encoding = "utf-8",
        )
        (repo / "vercel_api" / "app").mkdir(parents = True)
        for name in ("requirements.txt", "pyproject.toml"):
            (repo / "vercel_api" / name).write_text("", encoding = "utf-8")
        worktree = tmp_path / "worktree"
        shutil.copytree(repo, worktree)
        for name in self.STEERING:
            monkeypatch.setenv(name, "set by the shell")
        mutant = run.parse_mutants([_entry(bundle = True)], repo)[0]

        run.run_mutant(worktree, mutant, 120)

        handed = set(json.loads((worktree / "handed.json").read_text(encoding = "utf-8")))
        assert handed & {*self.STEERING, *run._SUITE_DATABASE_VARIABLE.values()} == set()
        assert "PYTHONDONTWRITEBYTECODE" in handed


class TestASrcLayoutWorktreeIsImportedFirst:
    """
    A src layout package is installed editable, so its import finds the repo the environment was installed from,
    wherever a test runs. A mutant is applied in the worktree. Unless the worktree's own ``src`` comes first on the
    import path every mutant's tests run the unmutated package, pass, and the mutant reads as survived, or worse,
    a table of mutants that are never applied reads as a table of rules nothing pins and is rewritten to match.
    """
    @staticmethod
    def _worktree(tmp_path: Path) -> Path:
        package = tmp_path / "src" / "kdf_probe_package"
        package.mkdir(parents = True)
        (package / "__init__.py").write_text('WHERE = "the worktree"\n', encoding = "utf-8")
        return tmp_path


    def test_the_worktree_s_src_is_first_on_the_import_path(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("PYTHONPATH", raising = False)
        env = run.suite_environment("unit", self._worktree(tmp_path))

        assert env.get("PYTHONPATH") == str(tmp_path / "src")


    def test_a_path_the_caller_set_is_never_kept(self, tmp_path: Path, monkeypatch):
        """
        A path of the caller's shell behind the worktree's ``src`` could hold the repo's own package or a module that
        shadows a test's import, so it is dropped with the rest of the shell (D-063), with ``src`` and without it.
        """
        monkeypatch.setenv("PYTHONPATH", "already-there")

        assert run.suite_environment("unit", self._worktree(tmp_path))["PYTHONPATH"] == str(tmp_path / "src")
        assert "PYTHONPATH" not in run.suite_environment("unit")


    def test_a_worktree_without_src_changes_nothing(self, tmp_path: Path, monkeypatch):
        """
        A backend keeps its package at the root, the engine leaves its path alone.
        """
        monkeypatch.delenv("PYTHONPATH", raising = False)

        assert "PYTHONPATH" not in run.suite_environment("unit", tmp_path)
        assert "PYTHONPATH" not in run.suite_environment("unit")


    def test_a_test_in_the_worktree_imports_the_worktree_s_package(self, tmp_path: Path, monkeypatch):
        """
        The rule itself, in a fresh interpreter, the way the runner starts pytest.
        """
        monkeypatch.delenv("PYTHONPATH", raising = False)
        worktree = self._worktree(tmp_path)
        source   = "\n".join([
            "try:",
            "    import kdf_probe_package",
            "    print(kdf_probe_package.WHERE)",
            "except ImportError:",
            "    print('not on the path')",
        ])
        probe    = [sys.executable, "-c", source]


        def where(env: dict[str, str]) -> str:
            # S603: every argument is trusted, this interpreter and a literal defined here
            done = subprocess.run(  # noqa: S603
                probe,
                cwd = str(worktree),
                env = env,
                capture_output = True,
                text = True,
                check = True,
            )
            return done.stdout.strip()


        assert where(run.suite_environment("unit", worktree)) == "the worktree"
        # the control, without the rule the same interpreter does not find the worktree's package
        assert where(run.suite_environment("unit")) == "not on the path"


class TestNoMutantRunsAnotherOnesBytecode:
    """
    CPython trusts a cached .pyc by the source's size and its modification time in whole seconds. Two mutants of one
    file that left it the same size, written within one second, ran the first one's code under the second one's name.
    Measured on the fitness backend's domain lane, a survivor that was killed 8 of 8 times once no bytecode was written
    (cicd D-027). The same second is forced here with the file's mtime, so the cases do not depend on the clock.
    """
    # a time every write below is stamped with, the same second for both
    SECOND: int = 1_700_000_000


    @pytest.fixture(autouse = True)
    def _not_the_callers_setting(self, monkeypatch):
        """
        A lane runs this file with the setting already in its environment, and ``suite_environment`` copies it, so the
        process's copy is dropped and the engine's own code is judged. With it left in, the hub's RE-M-84 survived.
        """
        monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising = False)


    @classmethod
    def _write(cls, path, value: str) -> None:
        path.write_text(f'VALUE = "{value}"\n', encoding = "utf-8")
        os.utime(path, (cls.SECOND, cls.SECOND))


    @staticmethod
    def _value(directory, env: dict[str, str]) -> str:
        done = subprocess.run(  # noqa: S603
            [sys.executable, "-c", "import probe_module; print(probe_module.VALUE)"],
            cwd = str(directory),
            env = env,
            capture_output = True,
            text = True,
            check = True,
        )
        return done.stdout.strip()


    def test_every_suite_writes_no_bytecode(self, monkeypatch):
        monkeypatch.setenv("KDF_TEST_DATABASE_URL", "postgresql+psycopg2://lane/own")
        monkeypatch.setenv("KDF_SYSTEM_DATABASE_URL", "postgresql+psycopg2://lane/own")
        for suite in sorted(run.SUITES):
            assert run.suite_environment(suite)["PYTHONDONTWRITEBYTECODE"] == "1", suite


    def test_a_same_size_edit_in_the_same_second_runs_its_own_source(self, tmp_path):
        env    = run.suite_environment("unit")
        module = tmp_path / "probe_module.py"
        self._write(module, "first")
        assert self._value(tmp_path, env) == "first"
        self._write(module, "other")
        assert self._value(tmp_path, env) == "other"


    def test_with_bytecode_written_the_same_edit_ran_the_first_ones_code(self, tmp_path):
        """
        The flaw itself, so the case above proves the setting and not a CPython that stopped caching this way.
        """
        env    = {
            name: value for name, value in run.suite_environment("unit").items() if name != "PYTHONDONTWRITEBYTECODE"
        }
        module = tmp_path / "probe_module.py"
        self._write(module, "first")
        assert self._value(tmp_path, env) == "first"
        self._write(module, "other")
        assert self._value(tmp_path, env) == "first"


class TestAMutantOfAnotherPlatformIsNotRun:
    """
    A rule that exists on one platform is mutated there alone. Elsewhere the edited line never runs, the mutant
    survives on the runner and fails its lane.
    """
    @staticmethod
    def _elsewhere() -> str:
        return "linux" if sys.platform == "win32" else "win32"


    def test_a_mutant_bound_to_no_platform_runs_everywhere(self, repo):
        assert run.parse_mutants([_entry()], repo)[0].runs_here() is True


    def test_a_mutant_runs_on_its_own_platform_and_no_other(self, repo):
        here      = run.parse_mutants([_entry(platform = sys.platform)], repo)[0]
        elsewhere = run.parse_mutants([_entry(platform = self._elsewhere())], repo)[0]
        assert here.platform == sys.platform and here.runs_here() is True
        assert elsewhere.runs_here() is False


    def test_a_mutant_not_run_is_neither_a_kill_nor_a_survivor(self):
        results = [
            run.Result("T-M-1", "killed", 1.0, "a rule"),
            run.Result("T-M-2", f"{run.NOT_RUN}, win32 only", 0.0, "a rule"),
        ]
        assert run.exit_status(results) == 0
        assert run.summary(results) == f"1 of 1 killed, 1 not run on {sys.platform}"


    @pytest.mark.parametrize("result", ["survived", "timeout", "error, anchor stale", "error, no test ran"])
    def test_a_mutant_that_ran_and_was_not_killed_fails_the_run(self, result):
        results = [
            run.Result("T-M-1", "killed", 1.0, "a rule"),
            run.Result("T-M-2", f"{run.NOT_RUN}, win32 only", 0.0, "a rule"),
            run.Result("T-M-3", result, 1.0, "a rule"),
        ]
        assert run.exit_status(results) == 1

# ======================================================================================================================
# A Whole Run
# ======================================================================================================================

class TestALaneRunsInTheRepoTheEngineIsVendoredTo:
    """
    The engine sits two folders down in every repo, at ``scripts/kdf_scripts/``, and reads that repo's tables, hands
    its unit suite that repo's settings, and judges a mutant by that repo's tests. One whole run on a repo made for
    it, the way ``make test-mutation`` starts it.
    """
    @staticmethod
    def _committed(repo: Path, table: list[dict[str, object]]) -> None:
        """
        The repo's settings and its lane ``demo``, committed, as a checkout with nothing uncommitted.
        """
        _write_package(repo, 'def unit_settings(environment):\n    return {"KDF_DEMO": "set by the repo"}\n')
        _write_table(repo, table)
        identity = ["-c", "user.name=runner", "-c", "user.email=runner@example.invalid"]
        for args in (["init", "--quiet", "--initial-branch", "main", "."], ["add", "--all"], ["commit", "-qm", "a"]):
            subprocess.run(  # noqa: S603, S607
                ["git", *identity, *args],
                cwd = str(repo),
                check = True,
                capture_output = True,
                env = run.git_environment(os.environ),
            )


    def test_a_mutant_the_repo_s_test_notices_is_killed(self, repo, tmp_path, monkeypatch):
        monkeypatch.delenv("KDF_DEMO", raising = False)
        self._committed(repo, [_entry()])
        worktree = tmp_path / "kdf-mutation" / "repo" / "demo"

        assert run.main(["--lane", "demo", "--worktree", str(worktree), "--timeout", "120"]) == 0

        results = json.loads((worktree.parent / "mutation-demo.json").read_text(encoding = "utf-8"))
        assert [(result["id"], result["result"]) for result in results] == [("T-M-1", "killed")]
        assert (repo / A_FILE).read_text(encoding = "utf-8") == RULE, "the checkout's own file is never edited"


    @pytest.mark.parametrize(
        "shell",
        [
            {"PYTEST_ADDOPTS": "-k nothing_matches_this"},
            {"PYTHONSAFEPATH": "1", "PYTHONPATH": "the checkout"},
        ],
        ids = ["a selection", "the checkout's package first"],
    )
    def test_a_shell_that_would_steer_pytest_changes_no_result(self, repo, tmp_path, monkeypatch, shell):
        """
        The rule end to end (D-063). Handed on, the selection left the control running nothing and the run stopped.
        The safe path kept the worktree off the import path, so every test imported the checkout's own unmutated
        package from ``PYTHONPATH``, the control passed and the mutant survived, so a rule a test pins read as unpinned.
        """
        monkeypatch.delenv("KDF_DEMO", raising = False)
        self._committed(repo, [_entry()])
        worktree = tmp_path / "kdf-mutation" / "repo" / "demo"
        for name, value in shell.items():
            monkeypatch.setenv(name, str(repo) if value == "the checkout" else value)

        assert run.main(["--lane", "demo", "--worktree", str(worktree), "--timeout", "120"]) == 0

        results = json.loads((worktree.parent / "mutation-demo.json").read_text(encoding = "utf-8"))
        assert [(result["id"], result["result"]) for result in results] == [("T-M-1", "killed")]


    def test_a_mutant_no_test_notices_survives_and_fails_the_lane(self, repo, tmp_path, monkeypatch):
        monkeypatch.delenv("KDF_DEMO", raising = False)
        self._committed(repo, [_entry(anchor = "def allowed(user):", replacement = "def allowed(user, unused = 0):")])
        worktree = tmp_path / "kdf-mutation" / "repo" / "demo"

        assert run.main(["--lane", "demo", "--worktree", str(worktree), "--timeout", "120"]) == 1

        results = json.loads((worktree.parent / "mutation-demo.json").read_text(encoding = "utf-8"))
        assert [result["result"] for result in results] == ["survived"]

# ======================================================================================================================
# The Engine's Own Table
# ======================================================================================================================

def _defined(node_id: str) -> bool:
    """
    Whether a node id names a file, and inside it a class and a test, that this repo defines.
    """
    path, *parts = node_id.split("::")
    source = SEAT_ROOT / path
    if not source.is_file():
        return False
    scope: list[ast.AST] = list(ast.iter_child_nodes(ast.parse(source.read_text(encoding = "utf-8"))))
    for name in (part.split("[", 1)[0] for part in parts):
        definitions = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        found       = next((node for node in scope if isinstance(node, definitions) and node.name == name), None)
        if found is None:
            return False
        scope = list(ast.iter_child_nodes(found))
    return True


class TestTheEngineSOwnTableAsCommitted:
    """
    The engine's own mutants are a lane like any repo's, ``mutation_tests/engine.py``. A rewritten line or a renamed
    test leaves a mutant that cannot run, which only the lane would report. Both are held here, every pull request, and
    the lane is held to the job that runs it.
    """
    @staticmethod
    def _table(monkeypatch: pytest.MonkeyPatch) -> list[run.Mutant]:
        monkeypatch.setattr(run, "REPO_ROOT", SEAT_ROOT)
        return run.load_table("engine")


    def test_every_anchor_occurs_once_in_the_engine(self, monkeypatch):
        engine    = (SEAT_ROOT / "scripts" / "common" / "mutation_runner.py").read_bytes().decode("utf-8")
        table     = self._table(monkeypatch)
        unapplied = sorted(mutant.id for mutant in table if run.apply_mutant(engine, mutant)[1] != "applied")
        assert unapplied == []


    def test_every_test_a_mutant_names_is_one_this_repo_defines(self, monkeypatch):
        stale = sorted({test for mutant in self._table(monkeypatch) for test in mutant.tests if not _defined(test)})
        assert stale == []


    def test_ci_runs_the_engine_s_lane(self):
        ci = (SEAT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding = "utf-8")
        assert "run: python scripts/common/mutation_runner.py --lane engine --worktree" in ci
        assert '"$RUNNER_TEMP/kdf-mutation/engine"' in ci
