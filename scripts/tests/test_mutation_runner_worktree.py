"""
``scripts/common/mutation_runner.py``, the worktree, the one place a run destroys anything (D-040).

The runner forces a checkout in its worktree and removes every untracked and ignored file there. Named ``--worktree .``
it once did that to the checkout it was started in, the SDK's review found it in every repo's copy of the runner
(SDK-S1-D3-R1-2), and the reads of that slice then found git acting where the runner had not looked, by the caller's
``GIT_`` variables, by a repository that appeared after the judgement, by a link a test put at the mutated path, and by
a link swapped in at the worktree's path or left inside it between a judgement and the act. Every test here runs in a
repository made for it, with the engine's root pointed at that repository, and asserts that the checkout, a second
clone or a file outside the worktree is untouched.
"""

from __future__ import annotations

# standard imports
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

# third party imports
import pytest
from common import mutation_runner as run

# ======================================================================================================================
# The Worktree
# ======================================================================================================================

@pytest.fixture(autouse = True)
def _a_folder_of_this_case_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Every case runs the engine for a folder of its own, which holds no repo until a case makes one, and the import
    path the engine adds to is put back after.
    """
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(run, "REPO_ROOT", (tmp_path / "no-repo").resolve())


class TestTheWorktreeIsTheReposOwn:
    """
    Two repos hold lanes of one name. With the lane alone in the path the second repo's run was handed the first
    one's worktree.
    """
    def test_the_default_path_names_the_repo_and_the_lane(self, tmp_path, monkeypatch, capsys):
        repo = (tmp_path / "a-repo-of-its-own").resolve()
        repo.mkdir()
        _git("init", "--quiet", "--initial-branch", "main", ".", cwd = repo)
        monkeypatch.setattr(run, "REPO_ROOT", repo)

        assert run.main(["--lane", "no_such_lane_here", "--remove"]) == 0
        said = capsys.readouterr().out.replace("\\", "/")
        assert "/kdf-mutation/a-repo-of-its-own/no_such_lane_here" in said


def _git(*args: str, cwd: Path) -> str:
    """
    git in a repo made for one test, as someone no real config names.
    """
    command = ["git", "-c", "user.name=runner", "-c", "user.email=runner@example.invalid", *args]
    # asked of the repo at cwd, whatever GIT_ variable a test set for the runner
    done = subprocess.run(  # noqa: S603
        command, cwd = str(cwd), check = True, capture_output = True, text = True, env = run.git_environment(os.environ)
    )
    return done.stdout.strip()


def _link_dir(target: Path, link: Path) -> None:
    """
    A link to a folder, a junction on Windows, which needs no privilege, a symbolic link elsewhere.
    """
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory = True)


def _unlink_dir_link(link: Path) -> None:
    """
    Remove a link to a folder and nothing behind it.
    """
    if sys.platform == "win32":
        os.rmdir(link)
    else:
        os.unlink(link)


class TestTheRunnerDestroysNothingButItsOwnWorktree:
    """
    The runner forces a checkout in its worktree and removes every untracked and ignored file there. Named
    ``--worktree .`` it did that to the checkout it was started in, a developer's uncommitted edit, their notes,
    their credentials file and their environment, and reported a green run. Every test here runs in a repository
    made for it, with the runner's root pointed at that repository.
    """
    EDIT = "an edit that is not committed\n"


    @classmethod
    def _repo(cls, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """
        A repository with one commit, then an edit, an untracked file and an ignored one, as a checkout at work.
        """
        repo = (tmp_path / "repo").resolve()
        (repo / "docs" / "deeper").mkdir(parents = True)
        (repo / "tracked.txt").write_text("committed\n", encoding = "utf-8")
        (repo / "docs" / "deeper" / "page.md").write_text("a page\n", encoding = "utf-8")
        (repo / ".gitignore").write_text("ignored.txt\n", encoding = "utf-8")
        _git("init", "--quiet", "--initial-branch", "main", ".", cwd = repo)
        _git("add", "--all", cwd = repo)
        _git("commit", "--quiet", "--message", "a state", cwd = repo)
        (repo / "tracked.txt").write_text(cls.EDIT, encoding = "utf-8")
        (repo / "untracked.txt").write_text("notes\n", encoding = "utf-8")
        (repo / "ignored.txt").write_text("a file git ignores\n", encoding = "utf-8")
        monkeypatch.setattr(run, "REPO_ROOT", repo)
        return repo


    @classmethod
    def _untouched(cls, repo: Path) -> bool:
        """
        Whether the checkout still holds its edit, its untracked file, its ignored file and its branch.
        """
        return (
            (repo / "tracked.txt").read_text(encoding = "utf-8") == cls.EDIT
            and (repo / "untracked.txt").is_file()
            and (repo / "ignored.txt").is_file()
            and _git("rev-parse", "--abbrev-ref", "HEAD", cwd = repo) == "main"
        )


    @pytest.mark.parametrize("named", [".", "docs", "docs/deeper"])
    def test_a_worktree_inside_the_checkout_is_refused_and_nothing_is_touched(self, tmp_path, monkeypatch, named):
        repo = self._repo(tmp_path, monkeypatch)
        monkeypatch.chdir(repo)

        with pytest.raises(run.WorktreeError, match = "is inside this checkout"):
            run.prepare_worktree(Path(named))

        assert self._untouched(repo)


    def test_a_folder_that_holds_the_checkout_is_refused(self, tmp_path, monkeypatch):
        repo = self._repo(tmp_path, monkeypatch)

        with pytest.raises(run.WorktreeError, match = "holds this checkout"):
            run.prepare_worktree(repo.parent)

        assert self._untouched(repo)


    def test_a_folder_the_repo_did_not_register_is_refused(self, tmp_path, monkeypatch):
        """
        A folder that exists and is no worktree of this repo is someone's folder. A file counts as well.
        """
        repo  = self._repo(tmp_path, monkeypatch)
        other = tmp_path / "other"
        other.mkdir()
        (other / "mine.txt").write_text("the caller's\n", encoding = "utf-8")

        for named in (other, other / "mine.txt"):
            with pytest.raises(run.WorktreeError, match = "is not a detached worktree this repo registered"):
                run.prepare_worktree(named)

        assert (other / "mine.txt").read_text(encoding = "utf-8") == "the caller's\n"
        assert self._untouched(repo)


    def test_a_developer_s_own_worktree_on_a_branch_is_refused(self, tmp_path, monkeypatch):
        """
        A worktree a developer added is registered too. Theirs is on a branch, a runner's is detached.
        """
        repo   = self._repo(tmp_path, monkeypatch)
        theirs = tmp_path / "feature"
        _git("worktree", "add", "--quiet", "-b", "feature", str(theirs), cwd = repo)
        (theirs / "work.txt").write_text("their work\n", encoding = "utf-8")

        with pytest.raises(run.WorktreeError, match = "is not a detached worktree this repo registered"):
            run.prepare_worktree(theirs)

        assert (theirs / "work.txt").is_file()
        assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd = theirs) == "feature"


    def test_removing_a_worktree_the_runner_did_not_make_is_refused(self, tmp_path, monkeypatch, capsys):
        """
        ``--remove`` forces the removal, which loses a developer's work as a forced checkout does.
        """
        repo   = self._repo(tmp_path, monkeypatch)
        theirs = tmp_path / "feature"
        _git("worktree", "add", "--quiet", "-b", "feature", str(theirs), cwd = repo)
        (theirs / "work.txt").write_text("their work\n", encoding = "utf-8")

        assert run.main(["--lane", "a_lane", "--remove", "--worktree", str(theirs)]) == 2
        assert run.main(["--lane", "a_lane", "--remove", "--worktree", str(repo)]) == 2

        assert "the worktree cannot be removed" in capsys.readouterr().out
        assert (theirs / "work.txt").is_file() and self._untouched(repo)


    def test_the_runner_s_own_worktree_is_made_and_made_clean_again(self, tmp_path, monkeypatch):
        """
        The road a run takes. The worktree is added detached, a later run finds it registered and cleans it, and
        the checkout's own files are copied in and never changed.
        """
        repo     = self._repo(tmp_path, monkeypatch)
        worktree = tmp_path / "kdf-mutation" / "repo" / "a_lane"

        # the first run adds the worktree and marks it, and must then find its own mark, or no lane could ever run
        refused = None
        try:
            synced = run.prepare_worktree(worktree)
        except run.WorktreeError as error:
            refused, synced = str(error), None

        assert refused is None, f"the runner refused the worktree it had just made, {refused}"
        assert synced == 2
        assert (worktree / "tracked.txt").read_text(encoding = "utf-8") == self.EDIT
        assert worktree.resolve() in run.own_worktrees()
        mark = run._git_path("rev-parse", "--absolute-git-dir", cwd = worktree) / run.WORKTREE_MARK
        assert mark.is_file() and mark.read_text(encoding = "utf-8") == str(worktree.resolve())

        (worktree / "left-by-a-mutant.txt").write_text("stale\n", encoding = "utf-8")
        assert run.prepare_worktree(worktree) == 2
        assert not (worktree / "left-by-a-mutant.txt").exists()
        assert self._untouched(repo)

        assert run.main(["--lane", "a_lane", "--remove", "--worktree", str(worktree)]) == 0
        assert not worktree.exists()


    def test_a_second_clone_of_this_repo_is_refused_and_keeps_its_work(self, tmp_path, monkeypatch):
        """
        A clone holds the commit, so a forced checkout in it would run. It is someone's folder all the same.
        """
        repo  = self._repo(tmp_path, monkeypatch)
        clone = tmp_path / "clone"
        _git("clone", "--quiet", str(repo), str(clone), cwd = tmp_path)
        (clone / "tracked.txt").write_text(self.EDIT, encoding = "utf-8")
        (clone / "untracked.txt").write_text("notes\n", encoding = "utf-8")
        (clone / "ignored.txt").write_text("a file git ignores\n", encoding = "utf-8")

        with pytest.raises(run.WorktreeError, match = "is not a detached worktree this repo registered"):
            run.prepare_worktree(clone)

        assert self._untouched(clone)


class TestGitActsWhereTheRunnerJudged:
    """
    The path was judged once by the runner, and git acts where its own reading says. The final read of the slice
    showed the two apart three ways, the caller's ``GIT_DIR`` turned every command on the checkout, a repository that
    appeared after the judgement was forced and cleaned, and the restore of a mutated file wrote through a link a
    test had put there. Each is closed by asking git from inside the path right before the act, by a mark only the
    runner writes, and by a restore that replaces the directory entry.
    """
    EDIT       = TestTheRunnerDestroysNothingButItsOwnWorktree.EDIT
    _repo      = TestTheRunnerDestroysNothingButItsOwnWorktree._repo
    _untouched = TestTheRunnerDestroysNothingButItsOwnWorktree._untouched


    def test_the_caller_s_git_variables_reach_no_git_command(self):
        given = {"GIT_DIR": "elsewhere/.git", "git_work_tree": "elsewhere", "PATH": "/bin", "GITHUB_ACTIONS": "true"}

        assert run.git_environment(given) == {"PATH": "/bin", "GITHUB_ACTIONS": "true"}


    def test_a_hook_s_git_dir_does_not_turn_the_run_on_the_checkout(self, tmp_path, monkeypatch):
        """
        git hands ``GIT_DIR`` and ``GIT_WORK_TREE`` to every hook. A lane run from one must still act in its worktree.
        """
        repo     = self._repo(tmp_path, monkeypatch)
        worktree = tmp_path / "kdf-mutation" / "repo" / "a_lane"
        assert run.prepare_worktree(worktree) == 2
        monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
        monkeypatch.setenv("GIT_WORK_TREE", str(repo))

        assert run.prepare_worktree(worktree) == 2

        assert self._untouched(repo)
        assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd = worktree) == "HEAD"


    def test_a_repository_that_appeared_after_the_judgement_is_refused(self, tmp_path, monkeypatch):
        """
        The first judgement passed a path that did not exist. By the time git acts there a clone stands there.
        """
        repo  = self._repo(tmp_path, monkeypatch)
        clone = tmp_path / "appeared"
        _git("clone", "--quiet", str(repo), str(clone), cwd = tmp_path)
        (clone / "tracked.txt").write_text(self.EDIT, encoding = "utf-8")
        (clone / "untracked.txt").write_text("notes\n", encoding = "utf-8")
        (clone / "ignored.txt").write_text("a file git ignores\n", encoding = "utf-8")
        monkeypatch.setattr(run, "worktree_problem", lambda worktree: None)

        with pytest.raises(run.WorktreeError, match = "belongs to another repository"):
            run.prepare_worktree(clone)

        assert self._untouched(clone)


    def test_a_detached_worktree_made_by_hand_is_refused_and_so_is_its_removal(self, tmp_path, monkeypatch, capsys):
        """
        A developer's ``git worktree add --detach`` is registered and detached, as a runner's is. It has no mark.
        """
        repo   = self._repo(tmp_path, monkeypatch)
        theirs = tmp_path / "scratch"
        _git("worktree", "add", "--quiet", "--detach", str(theirs), cwd = repo)
        (theirs / "work.txt").write_text("their work\n", encoding = "utf-8")
        assert theirs.resolve() in run.own_worktrees()

        with pytest.raises(run.WorktreeError, match = "was not made by this runner"):
            run.prepare_worktree(theirs)
        assert run.main(["--lane", "a_lane", "--remove", "--worktree", str(theirs)]) == 2

        assert "was not made by this runner" in capsys.readouterr().out
        assert (theirs / "work.txt").read_text(encoding = "utf-8") == "their work\n"


    def test_the_restore_replaces_the_entry_and_never_writes_through_a_link(self, tmp_path):
        """
        A test may put anything at the mutated path while it runs. A hard link to a file outside the worktree
        resolves inside it, so a write would land outside. The original replaces the entry instead.
        """
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside.py"
        outside.write_text("OUTSIDE = 99\n", encoding = "utf-8")
        (worktree / "module.py").write_text("VALUE = 1\n", encoding = "utf-8")
        swap = "\n".join([
            "import os",
            "from pathlib import Path",
            "def test_swap():",
            f"    p = Path({str(worktree / 'module.py')!r})",
            "    p.unlink()",
            f"    os.link({str(outside)!r}, p)",
            "",
        ])
        (worktree / "test_swap.py").write_text(swap, encoding = "utf-8")
        mutant = run.Mutant("PROBE", "the restore", "module.py", "VALUE = 1", "VALUE = 2", "unit", ("test_swap.py",))

        result = run.run_mutant(worktree, mutant, 60)

        assert result.result == "survived"
        assert outside.read_text(encoding = "utf-8") == "OUTSIDE = 99\n"
        assert (worktree / "module.py").read_text(encoding = "utf-8") == "VALUE = 1\n"


    def test_a_file_beside_the_worktree_that_is_not_a_results_file_is_never_written_over(self, tmp_path, capsys):
        """
        The results land beside the worktree, the one write outside it. What stands there is read first.
        """
        beside = tmp_path / "mutation-a_lane.json"
        beside.write_text("the caller's notes\n", encoding = "utf-8")

        assert run.main(["--lane", "a_lane", "--worktree", str(tmp_path / "wt")]) == 2

        assert "is not a results file of this runner" in capsys.readouterr().out
        assert beside.read_text(encoding = "utf-8") == "the caller's notes\n"


    @pytest.mark.parametrize(
        ("content", "is_one"),
        [
            pytest.param("[]", True, id = "an-empty-run"),
            pytest.param(
                '[{"id": "X-1", "result": "killed", "seconds": 1.0, "rule": "a rule", "detail": ""}]',
                True,
                id = "a-record",
            ),
            pytest.param('[{"id": "X-1", "result": "killed"}]', False, id = "a-record-with-keys-missing"),
            pytest.param(
                '[{"id": "X-1", "result": "killed", "seconds": 1.0, "rule": "a rule", "detail": "", "extra": 1}]',
                False,
                id = "a-record-with-a-key-more",
            ),
            pytest.param(
                '[{"id": 1, "result": null, "seconds": "x", "rule": [], "detail": {}}]',
                False,
                id = "a-record-of-other-types",
            ),
            pytest.param(
                '[{"id": "X-1", "result": "killed", "seconds": true, "rule": "a rule", "detail": ""}]',
                False,
                id = "seconds-as-a-bool",
            ),
            pytest.param('{"id": "X-1"}', False, id = "not-a-list"),
            pytest.param("notes", False, id = "not-json"),
        ],
    )
    def test_only_the_runner_s_own_shape_is_a_results_file(self, tmp_path, content, is_one):
        path = tmp_path / "mutation-lane.json"
        path.write_text(content, encoding = "utf-8")

        assert run.is_results_file(path) is is_one


class TestNothingChangesBetweenTheJudgementAndTheAct:
    """
    The fourth narrow read of the slice asked what happens in the moment between a judgement and the act it allows.
    A link swapped in at the worktree's path by whoever can write to its parent, a link a test left inside the
    worktree, a hard link at the name the restore wrote first, the results file replaced during the run. The folders
    the worktree stands in are made the runner's own, git is asked again before each act and the worktree is walked
    for a link first, and every write replaces a directory entry made under a name no test knows.
    """
    EDIT       = TestTheRunnerDestroysNothingButItsOwnWorktree.EDIT
    _repo      = TestTheRunnerDestroysNothingButItsOwnWorktree._repo
    _untouched = TestTheRunnerDestroysNothingButItsOwnWorktree._untouched


    @classmethod
    def _lane(cls, repo: Path, monkeypatch: pytest.MonkeyPatch, body: list[str] | None = None) -> None:
        """
        A lane of one mutant on the edit in ``tracked.txt``, and a test in the repo that notices it, or the body given.
        """
        lines = body or [f"    assert Path('tracked.txt').read_text(encoding = 'utf-8') == {cls.EDIT!r}"]
        (repo / "test_tracked.py").write_text(
            "\n".join(["import os", "from pathlib import Path", "def test_tracked():", *lines, ""]),
            encoding = "utf-8",
        )
        mutant = run.Mutant(
            "T-1",
            "the edit stays",
            "tracked.txt",
            cls.EDIT.strip(),
            "a mutated line",
            "unit",
            ("test_tracked.py",),
        )
        monkeypatch.setattr(run, "load_table", lambda lane: [mutant])


    def test_the_folders_the_worktree_stands_in_are_made_the_runner_s_own(self, tmp_path, monkeypatch):
        self._repo(tmp_path, monkeypatch)
        worktree = tmp_path / "kdf-mutation" / "repo" / "a_lane"

        assert run.own_folders(worktree) is None

        assert (tmp_path / "kdf-mutation" / "repo").is_dir()
        if sys.platform != "win32":
            assert stat.S_IMODE(os.lstat(tmp_path / "kdf-mutation").st_mode) == 0o700
            assert stat.S_IMODE(os.lstat(tmp_path / "kdf-mutation" / "repo").st_mode) == 0o700


    def test_a_folder_the_worktree_stands_in_that_is_a_link_is_refused(self, tmp_path, monkeypatch):
        """
        A link above the path sends the add, the forced checkout and the clean wherever it points.
        """
        self._repo(tmp_path, monkeypatch)
        other = tmp_path / "other"
        other.mkdir()
        parent = tmp_path / "parent"
        _link_dir(other, parent)

        problem = run.own_folders(parent / "a_lane")

        assert problem is not None and "is a link" in problem
        assert list(other.iterdir()) == []
        _unlink_dir_link(parent)


    @pytest.mark.skipif(sys.platform == "win32", reason = "a folder's mode and owner are POSIX facts")
    def test_a_folder_other_users_can_write_to_is_refused(self, tmp_path, monkeypatch):
        self._repo(tmp_path, monkeypatch)
        shared = tmp_path / "shared"
        shared.mkdir()
        shared.chmod(0o1777)

        problem = run.own_folders(shared / "a_lane")

        assert problem is not None and "writable by other users" in problem


    @pytest.mark.skipif(sys.platform == "win32", reason = "a folder's mode and owner are POSIX facts")
    def test_a_folder_of_another_user_s_is_refused(self, tmp_path, monkeypatch):
        self._repo(tmp_path, monkeypatch)
        theirs = tmp_path / "theirs"
        theirs.mkdir()
        monkeypatch.setattr(os, "getuid", lambda: os.lstat(theirs).st_uid + 1)

        problem = run.own_folders(theirs / "a_lane")

        assert problem is not None and "is another user's" in problem


    def test_git_is_asked_again_between_the_checkout_and_the_clean(self, tmp_path, monkeypatch):
        """
        The checkout's own hook runs between the two commands, with the runner's rights. What stands at the path is
        asked for again before the clean, here a link to a second clone swapped in after the checkout.
        """
        repo   = self._repo(tmp_path, monkeypatch)
        victim = tmp_path / "victim"
        _git("clone", "--quiet", str(repo), str(victim), cwd = tmp_path)
        (victim / "tracked.txt").write_text(self.EDIT, encoding = "utf-8")
        (victim / "untracked.txt").write_text("notes\n", encoding = "utf-8")
        (victim / "ignored.txt").write_text("a file git ignores\n", encoding = "utf-8")
        worktree = tmp_path / "kdf-mutation" / "repo" / "a_lane"
        assert run.prepare_worktree(worktree) == 2
        real = run._git


        def swapped_after_the_checkout(*args: str, cwd: Path) -> bytes:
            out = real(*args, cwd = cwd)
            if args[0] == "checkout":
                os.rename(worktree, tmp_path / "moved")
                _link_dir(victim, worktree)
            return out


        monkeypatch.setattr(run, "_git", swapped_after_the_checkout)

        with pytest.raises(run.WorktreeError, match = "belongs to another repository"):
            run.prepare_worktree(worktree)

        assert self._untouched(victim)
        _unlink_dir_link(worktree)


    def test_a_link_a_test_left_inside_the_worktree_stops_the_next_run_and_its_removal(
        self,
        tmp_path,
        monkeypatch,
        capsys,
    ):
        """
        git's clean removes what stands behind a link that took a tracked folder's place, and its forced removal of
        the worktree removes everything behind every link in it, measured, both outside the worktree.
        """
        repo   = self._repo(tmp_path, monkeypatch)
        victim = tmp_path / "victim"
        _git("clone", "--quiet", str(repo), str(victim), cwd = tmp_path)
        (victim / "docs" / "deeper" / "notes.md").write_text("their notes\n", encoding = "utf-8")
        worktree = tmp_path / "kdf-mutation" / "repo" / "a_lane"
        assert run.prepare_worktree(worktree) == 2
        shutil.rmtree(worktree / "docs")
        _link_dir(victim / "docs", worktree / "docs")
        _link_dir(victim, worktree / "loose")

        with pytest.raises(run.WorktreeError, match = "is a link inside the worktree"):
            run.prepare_worktree(worktree)
        removal = run.main(["--lane", "a_lane", "--remove", "--worktree", str(worktree)])

        assert removal == 2
        assert "is a link inside the worktree" in capsys.readouterr().out
        assert (victim / "docs" / "deeper" / "notes.md").is_file() and (victim / ".git").is_dir()
        _unlink_dir_link(worktree / "docs")
        _unlink_dir_link(worktree / "loose")
        assert run.main(["--lane", "a_lane", "--remove", "--worktree", str(worktree)]) == 0


    def test_removing_a_worktree_whose_folder_is_gone_names_the_prune(self, tmp_path, monkeypatch, capsys):
        """
        git keeps the record of a worktree whose folder was deleted by hand and refuses to add it again until the
        record is pruned, which is a developer's to do.
        """
        self._repo(tmp_path, monkeypatch)
        worktree = tmp_path / "kdf-mutation" / "repo" / "a_lane"
        assert run.prepare_worktree(worktree) == 2
        shutil.rmtree(worktree)

        assert run.main(["--lane", "a_lane", "--remove", "--worktree", str(worktree)]) == 2

        assert "git worktree prune" in capsys.readouterr().out


    def test_a_removal_git_refuses_is_reported_and_not_a_traceback(self, tmp_path, monkeypatch, capsys):
        """
        git validates the worktree it removes, and a path swapped since the judgement fails that. The run says so.
        """
        repo     = self._repo(tmp_path, monkeypatch)
        worktree = tmp_path / "kdf-mutation" / "repo" / "a_lane"
        assert run.prepare_worktree(worktree) == 2
        real = run.not_this_runners_worktree


        def judged_then_swapped(path: Path) -> str | None:
            answer = real(path)
            if answer is None:
                os.rename(worktree, tmp_path / "moved")
                _link_dir(repo, worktree)
            return answer


        monkeypatch.setattr(run, "not_this_runners_worktree", judged_then_swapped)
        crashed = code = None
        try:
            code = run.main(["--lane", "a_lane", "--remove", "--worktree", str(worktree)])
        except subprocess.CalledProcessError as error:
            crashed = error

        assert crashed is None
        assert code == 2
        assert "could not be removed" in capsys.readouterr().out
        assert self._untouched(repo)
        _unlink_dir_link(worktree)


    def test_an_act_git_refuses_is_reported_and_not_a_traceback(self, tmp_path, monkeypatch):
        self._repo(tmp_path, monkeypatch)
        worktree = tmp_path / "kdf-mutation" / "repo" / "a_lane"
        real     = run._git


        def refusing(*args: str, cwd: Path) -> bytes:
            if args[0] == "clean":
                raise subprocess.CalledProcessError(
                    128,
                    ["git", *args],
                    output = b"",
                    stderr = b"fatal: a synthetic refusal",
                )
            return real(*args, cwd = cwd)


        monkeypatch.setattr(run, "_git", refusing)
        crashed = said = None
        try:
            run.prepare_worktree(worktree)
        except run.WorktreeError as error:
            said = str(error)
        except subprocess.CalledProcessError as error:
            crashed = error

        assert crashed is None
        assert said is not None and "git clean failed in" in said and "a synthetic refusal" in said


    def test_the_restore_refuses_a_folder_that_leads_out_of_the_worktree(self, tmp_path):
        """
        A test replaced the mutated file's folder with a link to a folder outside. The restore would land there.
        """
        worktree = tmp_path / "worktree"
        (worktree / "pkg").mkdir(parents = True)
        (worktree / "pkg" / "module.py").write_text("VALUE = 1\n", encoding = "utf-8")
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "module.py").write_text("OUTSIDE = 99\n", encoding = "utf-8")
        link = (
            f"_winapi.CreateJunction({str(outside)!r}, {str(worktree / 'pkg')!r})" if sys.platform == "win32"
            else f"os.symlink({str(outside)!r}, {str(worktree / 'pkg')!r}, target_is_directory = True)"
        )
        swap = "\n".join([
            "import os",
            "import _winapi" if sys.platform == "win32" else "",
            "def test_swap():",
            f"    os.rename({str(worktree / 'pkg')!r}, {str(worktree / 'moved')!r})",
            f"    {link}",
            "",
        ])
        (worktree / "test_swap.py").write_text(swap, encoding = "utf-8")
        mutant = run.Mutant(
            "PROBE",
            "the restore",
            "pkg/module.py",
            "VALUE = 1",
            "VALUE = 2",
            "unit",
            ("test_swap.py",),
        )

        with pytest.raises(RuntimeError, match = "leads out of"):
            run.run_mutant(worktree, mutant, 60)

        assert (outside / "module.py").read_text(encoding = "utf-8") == "OUTSIDE = 99\n"
        _unlink_dir_link(worktree / "pkg")


    def test_the_restore_writes_under_a_name_no_test_knows(self, tmp_path):
        """
        The restore once wrote ``<file>.kdf-restore`` first. A hard link a test put at that name was written through.
        """
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside.py"
        outside.write_text("OUTSIDE = 99\n", encoding = "utf-8")
        (worktree / "module.py").write_text("VALUE = 1\n", encoding = "utf-8")
        guessed = worktree / "module.py.kdf-restore"
        swap    = "\n".join(["import os", "def test_swap():", f"    os.link({str(outside)!r}, {str(guessed)!r})", ""])
        (worktree / "test_swap.py").write_text(swap, encoding = "utf-8")
        mutant = run.Mutant("PROBE", "the restore", "module.py", "VALUE = 1", "VALUE = 2", "unit", ("test_swap.py",))

        result = run.run_mutant(worktree, mutant, 60)

        assert result.result == "survived"
        assert outside.read_text(encoding = "utf-8") == "OUTSIDE = 99\n"
        assert guessed.is_file() and (worktree / "module.py").read_text(encoding = "utf-8") == "VALUE = 1\n"
        assert [path.name for path in worktree.iterdir() if path.name.startswith(".kdf-restore")] == []


    @pytest.mark.parametrize("placed", ["a-hard-link", "later-notes"])
    def test_the_results_are_written_by_replacing_the_entry_after_a_second_look(
        self,
        tmp_path,
        monkeypatch,
        capsys,
        placed,
    ):
        """
        The results file is the one write outside the worktree, at the end of a run that took a while.
        """
        repo     = self._repo(tmp_path, monkeypatch)
        worktree = tmp_path / "kdf-mutation" / "repo" / "a_lane"
        beside   = worktree.parent / "mutation-a_lane.json"
        beside.parent.mkdir(parents = True)
        outside = tmp_path / "outside.json"
        outside.write_text("[]", encoding = "utf-8")
        if placed == "a-hard-link":
            os.link(outside, beside)
            self._lane(repo, monkeypatch)
        else:
            self._lane(repo, monkeypatch, [f"    Path({str(beside)!r}).write_text('the caller notes')"])

        code = run.main(["--lane", "a_lane", "--worktree", str(worktree), "--timeout", "60"])

        if placed == "a-hard-link":
            assert code == 0
            assert outside.read_text(encoding = "utf-8") == "[]"
            assert json.loads(beside.read_text(encoding = "utf-8"))[0]["result"] == "killed"
        else:
            assert code == 2
            assert "is not a results file of this runner any more" in capsys.readouterr().out
            assert beside.read_text(encoding = "utf-8") == "the caller notes"


    def test_a_restore_that_fails_stops_the_run_with_the_reason(self, tmp_path, monkeypatch, capsys):
        """
        A test left a directory at the mutated file's path. Nothing can be put back there, the run says so and stops.
        """
        repo     = self._repo(tmp_path, monkeypatch)
        worktree = tmp_path / "kdf-mutation" / "repo" / "a_lane"
        self._lane(repo, monkeypatch, [
            f"    if Path('tracked.txt').read_text(encoding = 'utf-8') != {self.EDIT!r}:",
            "        os.unlink('tracked.txt')",
            "        os.mkdir('tracked.txt')",
        ])
        crashed = code = None
        try:
            code = run.main(["--lane", "a_lane", "--worktree", str(worktree), "--timeout", "60"])
        except RuntimeError as error:
            crashed = error

        assert crashed is None
        assert code == 2
        assert "was not restored" in capsys.readouterr().out


    def test_a_worktree_named_relative_is_the_one_under_the_shell_s_folder(self, tmp_path, monkeypatch, capsys):
        """
        The runner judged a relative path against the shell's folder and git, run from the checkout, added it under
        the checkout, so the run died on the other path with a stray worktree inside the checkout. Resolved once in
        ``main``, a whole run from another folder adds, uses and reports one place.
        """
        repo      = self._repo(tmp_path, monkeypatch)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        self._lane(repo, monkeypatch)
        monkeypatch.chdir(elsewhere)
        crashed = code = None
        try:
            code = run.main(["--lane", "a_lane", "--worktree", "rel", "--timeout", "60"])
        except OSError as error:
            crashed = error

        assert crashed is None
        assert code == 0
        assert run.own_worktrees() == [(elsewhere / "rel").resolve()]
        assert not (repo / "rel").exists()
        assert (elsewhere / "mutation-a_lane.json").is_file()
        assert str(elsewhere.resolve() / "rel") in capsys.readouterr().out
