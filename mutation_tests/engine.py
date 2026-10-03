"""
The engine lane's mutants, one deliberate break per rule of the shared mutation engine, each with the test in
``scripts/tests/`` that must kill it (D-040). The engine runs this table on itself, as a repo's lane runs its own.

The engine came from the SDK's runner, and EN-1 to EN-36 are that runner's own mutants of the SDK's review, slice S1,
in their order, SDK-FO-255 to SDK-FO-263, SDK-FO-275 to SDK-FO-284, SDK-FO-291 to SDK-FO-306 and SDK-FO-90. EN-37 is the
hub's RE-M-84, the rule that no run writes bytecode. EN-38 to EN-44 are the rules D-040 added, what a repo's tables
package says its unit suite needs and the seat the engine finds its repo from. Five are bound to Linux, where the
modes and owners of folders and a symbolic link a test can make exist.

    python scripts/common/mutation_runner.py --lane engine
"""

from __future__ import annotations

# ======================================================================================================================
# Files
# ======================================================================================================================

ENGINE      = "scripts/common/mutation_runner.py"
RUNNER      = "scripts/tests/test_mutation_runner.py"
RUNNER_TREE = "scripts/tests/test_mutation_runner_worktree.py"

TABLE      = f"{RUNNER}::TestTheTableIsValidatedBeforeAnythingRuns"
SRC_FIRST  = f"{RUNNER}::TestASrcLayoutWorktreeIsImportedFirst"
BYTECODE   = f"{RUNNER}::TestNoMutantRunsAnotherOnesBytecode"
SETTINGS   = f"{RUNNER}::TestTheRepoSaysWhatItsUnitSuiteNeeds"
WHOLE_RUN  = f"{RUNNER}::TestALaneRunsInTheRepoTheEngineIsVendoredTo"
SEAT       = f"{RUNNER}::TestTheEngineFindsItsRepo"
OWN_TREE   = f"{RUNNER_TREE}::TestTheRunnerDestroysNothingButItsOwnWorktree"
GIT_ACTS   = f"{RUNNER_TREE}::TestGitActsWhereTheRunnerJudged"
ONE_MOMENT = f"{RUNNER_TREE}::TestNothingChangesBetweenTheJudgementAndTheAct"

# ======================================================================================================================
# Mutants
# ======================================================================================================================

MUTANTS: list[dict[str, object]] = [
    {
        "id": "EN-1",
        "rule": "the runner never takes a path inside its own checkout for its worktree, it forces a checkout there",
        "file": ENGINE,
        "anchor": "    if target == REPO_ROOT or REPO_ROOT in target.parents:",
        "replacement": "    if False:",
        "suite": "unit",
        "tests": [f"{OWN_TREE}::test_a_worktree_inside_the_checkout_is_refused_and_nothing_is_touched"],
    },
    {
        "id": "EN-2",
        "rule": "a folder that holds the checkout is never the runner's worktree",
        "file": ENGINE,
        "anchor": "    if target in REPO_ROOT.parents:",
        "replacement": "    if False:",
        "suite": "unit",
        "tests": [f"{OWN_TREE}::test_a_folder_that_holds_the_checkout_is_refused"],
    },
    {
        "id": "EN-3",
        "rule": "a path that exists is the runner's worktree only when this repo registered it",
        "file": ENGINE,
        "anchor": "    if target.exists() and target not in own_worktrees():",
        "replacement": "    if False:",
        "suite": "unit",
        "tests": [
            f"{OWN_TREE}::test_a_second_clone_of_this_repo_is_refused_and_keeps_its_work",
            f"{OWN_TREE}::test_a_folder_the_repo_did_not_register_is_refused",
        ],
    },
    {
        "id": "EN-4",
        "rule": "a developer's own worktree, on a branch, is not the runner's, the runner's is detached",
        "file": ENGINE,
        "anchor": '        if block[0].startswith(b"worktree ") and b"detached" in block',
        "replacement": '        if block[0].startswith(b"worktree ")',
        "suite": "unit",
        "tests": [f"{OWN_TREE}::test_a_developer_s_own_worktree_on_a_branch_is_refused"],
    },
    {
        "id": "EN-5",
        "rule": "the worktree is judged inside the function that forces the checkout, whoever calls it",
        "file": ENGINE,
        "anchor": (
            "    problem = worktree_problem(worktree)\n"
            "    if problem is not None:\n"
            "        raise WorktreeError(problem)"
        ),
        "replacement": "    problem = worktree_problem(worktree)\n    if False:\n        raise WorktreeError(problem)",
        "suite": "unit",
        "tests": [f"{OWN_TREE}::test_a_developer_s_own_worktree_on_a_branch_is_refused"],
    },
    {
        "id": "EN-6",
        "rule": "a forced removal is judged the same way, it loses a developer's work as a forced checkout does",
        "file": ENGINE,
        "anchor": '        if problem is not None:\n            print(f"the worktree cannot be removed, {problem}")',
        "replacement": '        if False:\n            print(f"the worktree cannot be removed, {problem}")',
        "suite": "unit",
        "tests": [f"{OWN_TREE}::test_removing_a_worktree_the_runner_did_not_make_is_refused"],
    },
    {
        "id": "EN-7",
        "rule": "a mutant's file is repo relative, an absolute path would be written into the live file",
        "file": ENGINE,
        "anchor": '        if named.is_absolute() or named.drive or ".." in named.parts:',
        "replacement": "        if False:",
        "suite": "unit",
        "tests": [f"{TABLE}::test_a_file_that_is_not_inside_the_repo_is_refused"],
    },
    {
        "id": "EN-8",
        "rule": "a mutant's file that is a link out of the repo is refused by the table",
        "file": ENGINE,
        "anchor": "        if repo_root.resolve() not in (repo_root / named).resolve().parents:",
        "replacement": "        if False:",
        "suite": "unit",
        "tests": [f"{TABLE}::test_a_file_that_is_a_link_out_of_the_repo_is_refused_and_never_written"],
        "platform": "linux",
    },
    {
        "id": "EN-9",
        "rule": "the runner asks where a mutant's write would land, a link out of the worktree is never written",
        "file": ENGINE,
        "anchor": "    if worktree.resolve() not in path.resolve().parents:",
        "replacement": "    if False:",
        "suite": "unit",
        "tests": [f"{TABLE}::test_a_file_that_is_a_link_out_of_the_repo_is_refused_and_never_written"],
        "platform": "linux",
    },
    {
        "id": "EN-10",
        "rule": "the runner's git commands read no GIT_ variable of the caller's shell, a hook hands GIT_DIR to a run",
        "file": ENGINE,
        "anchor": '    return {name: value for name, value in environ.items() if not name.upper().startswith("GIT_")}',
        "replacement": "    return dict(environ)",
        "suite": "unit",
        "tests": [
            f"{GIT_ACTS}::test_the_caller_s_git_variables_reach_no_git_command",
            f"{GIT_ACTS}::test_a_hook_s_git_dir_does_not_turn_the_run_on_the_checkout",
        ],
    },
    {
        "id": "EN-11",
        "rule": "git is asked where it is about to act, right before the forced checkout, not only at the judgement",
        "file": ENGINE,
        "anchor": (
            "    problem = not_this_runners_worktree(worktree)\n"
            "    if problem is not None:\n"
            "        raise WorktreeError(problem)"
        ),
        "replacement": (
            "    problem = not_this_runners_worktree(worktree)\n"
            "    if False:\n"
            "        raise WorktreeError(problem)"
        ),
        "suite": "unit",
        "tests": [f"{GIT_ACTS}::test_a_repository_that_appeared_after_the_judgement_is_refused"],
    },
    {
        "id": "EN-12",
        "rule": "a worktree of another repository is refused where git acts, whatever the judgement passed",
        "file": ENGINE,
        "anchor": '    if common != _git_path("rev-parse", "--git-common-dir", cwd = REPO_ROOT):',
        "replacement": "    if False:",
        "suite": "unit",
        "tests": [f"{GIT_ACTS}::test_a_repository_that_appeared_after_the_judgement_is_refused"],
    },
    {
        "id": "EN-13",
        "rule": "only a worktree carrying the runner's own mark is forced, cleaned or removed",
        "file": ENGINE,
        "anchor": '    if not mark.is_file() or mark.read_text(encoding = "utf-8").strip() != str(target):',
        "replacement": "    if False:",
        "suite": "unit",
        "tests": [f"{GIT_ACTS}::test_a_detached_worktree_made_by_hand_is_refused_and_so_is_its_removal"],
    },
    {
        "id": "EN-14",
        "rule": "a removal asks git where it acts as a run does",
        "file": ENGINE,
        "anchor": (
            "        if problem is None and worktree.exists():\n"
            "            problem = not_this_runners_worktree(worktree)"
        ),
        "replacement": "        if False:\n            problem = not_this_runners_worktree(worktree)",
        "suite": "unit",
        "tests": [f"{GIT_ACTS}::test_a_detached_worktree_made_by_hand_is_refused_and_so_is_its_removal"],
    },
    {
        "id": "EN-15",
        "rule": "the worktree's path is resolved once, the judgement and every git command name one place",
        "file": ENGINE,
        "anchor": (
            '    worktree = (args.worktree or Path(tempfile.gettempdir()) / "kdf-mutation" / REPO_ROOT.name '
            "/ args.lane).resolve()"
        ),
        "replacement": (
            '    worktree = args.worktree or Path(tempfile.gettempdir()) / "kdf-mutation" / REPO_ROOT.name / args.lane'
        ),
        "suite": "unit",
        "tests": [f"{ONE_MOMENT}::test_a_worktree_named_relative_is_the_one_under_the_shell_s_folder"],
    },
    {
        "id": "EN-16",
        "rule": "the restore replaces the directory entry, it never writes through what a test put at the path",
        "file": ENGINE,
        "anchor": "        os.replace(made, path)",
        "replacement": "        shutil.copyfile(made, path)\n        os.unlink(made)",
        "suite": "unit",
        "tests": [f"{GIT_ACTS}::test_the_restore_replaces_the_entry_and_never_writes_through_a_link"],
    },
    {
        "id": "EN-17",
        "rule": "a file beside the worktree is written over only when it is a results file of the runner's own",
        "file": ENGINE,
        "anchor": (
            "    if report.exists() and not is_results_file(report):\n"
            '        print(f"{report} is not a results file of this runner, move it or name another worktree")'
        ),
        "replacement": (
            "    if False:\n"
            '        print(f"{report} is not a results file of this runner, move it or name another worktree")'
        ),
        "suite": "unit",
        "tests": [f"{GIT_ACTS}::test_a_file_beside_the_worktree_that_is_not_a_results_file_is_never_written_over"],
    },
    {
        "id": "EN-18",
        "rule": "a results file is a list of records with a result's keys and no other shape",
        "file": ENGINE,
        "anchor": "    if not isinstance(record, dict) or set(record) != set(_RESULT_TYPES):",
        "replacement": "    if not isinstance(record, dict) or not set(record) >= set(_RESULT_TYPES):",
        "suite": "unit",
        "tests": [f"{GIT_ACTS}::test_only_the_runner_s_own_shape_is_a_results_file"],
    },
    {
        "id": "EN-19",
        "rule": "the mark is written when the worktree is added, a later run finds its own worktree by it",
        "file": ENGINE,
        "anchor": '        (git_dir / WORKTREE_MARK).write_text(str(worktree.resolve()), encoding = "utf-8")',
        "replacement": "        pass",
        "suite": "unit",
        "tests": [f"{OWN_TREE}::test_the_runner_s_own_worktree_is_made_and_made_clean_again"],
    },
    {
        "id": "EN-20",
        "rule": "a folder the worktree stands in that is a link is refused, a link there sends every act elsewhere",
        "file": ENGINE,
        "anchor": "        if stat.S_ISLNK(found.st_mode) or folder.is_junction():",
        "replacement": "        if False:",
        "suite": "unit",
        "tests": [f"{ONE_MOMENT}::test_a_folder_the_worktree_stands_in_that_is_a_link_is_refused"],
    },
    {
        "id": "EN-21",
        "rule": "a folder the worktree stands in that other users can write to is refused, they could swap a link in",
        "file": ENGINE,
        "anchor": '        if sys.platform != "win32" and found.st_mode & 0o022:',
        "replacement": "        if False:",
        "suite": "unit",
        "tests": [f"{ONE_MOMENT}::test_a_folder_other_users_can_write_to_is_refused"],
        "platform": "linux",
    },
    {
        "id": "EN-22",
        "rule": "git is asked where it acts before each command that destroys, a hook runs between the two",
        "file": ENGINE,
        "anchor": '    _act(worktree, "clean", "-fdx", "--quiet")',
        "replacement": '    _git("clean", "-fdx", "--quiet", cwd = worktree)',
        "suite": "unit",
        "tests": [f"{ONE_MOMENT}::test_git_is_asked_again_between_the_checkout_and_the_clean"],
    },
    {
        "id": "EN-23",
        "rule": "a link inside the worktree stops the run before git acts through it",
        "file": ENGINE,
        "anchor": (
            "    problem = link_problem(worktree)\n"
            "    if problem is not None:\n"
            "        raise WorktreeError(problem)"
        ),
        "replacement": "    problem = link_problem(worktree)\n    if False:\n        raise WorktreeError(problem)",
        "suite": "unit",
        "tests": [f"{ONE_MOMENT}::test_a_link_a_test_left_inside_the_worktree_stops_the_next_run_and_its_removal"],
    },
    {
        "id": "EN-24",
        "rule": "a link inside the worktree stops its removal, git's forced removal deletes everything behind a link",
        "file": ENGINE,
        "anchor": "        if problem is None and worktree.exists():\n            problem = link_problem(worktree)",
        "replacement": "        if False:\n            problem = link_problem(worktree)",
        "suite": "unit",
        "tests": [f"{ONE_MOMENT}::test_a_link_a_test_left_inside_the_worktree_stops_the_next_run_and_its_removal"],
    },
    {
        "id": "EN-25",
        "rule": "removing a worktree whose folder is gone names the prune git needs, instead of reporting a removal",
        "file": ENGINE,
        "anchor": "        if problem is None and not worktree.exists() and worktree in own_worktrees():",
        "replacement": "        if False:",
        "suite": "unit",
        "tests": [f"{ONE_MOMENT}::test_removing_a_worktree_whose_folder_is_gone_names_the_prune"],
    },
    {
        "id": "EN-26",
        "rule": "the restore asks that the mutated file's folder still stands inside the worktree",
        "file": ENGINE,
        "anchor": "    if top != folder and top not in folder.parents:",
        "replacement": "    if False:",
        "suite": "unit",
        "tests": [f"{ONE_MOMENT}::test_the_restore_refuses_a_folder_that_leads_out_of_the_worktree"],
    },
    {
        "id": "EN-27",
        "rule": "the restore writes under a name no test knows, a link at a guessable name was written through",
        "file": ENGINE,
        "anchor": '    handle, made = tempfile.mkstemp(dir = path.parent, prefix = ".kdf-restore-")',
        "replacement": (
            '    made   = f"{path}.kdf-restore"\n'
            '    handle = os.open(made, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0))'
        ),
        "suite": "unit",
        "tests": [f"{ONE_MOMENT}::test_the_restore_writes_under_a_name_no_test_knows"],
    },
    {
        "id": "EN-28",
        "rule": "the results file replaces the directory entry, a link at its path is never written through",
        "file": ENGINE,
        "anchor": "        os.replace(made, report)",
        "replacement": "        shutil.copyfile(made, report)\n        os.unlink(made)",
        "suite": "unit",
        "tests": [f"{ONE_MOMENT}::test_the_results_are_written_by_replacing_the_entry_after_a_second_look"],
    },
    {
        "id": "EN-29",
        "rule": "what stands at the results path is asked again right before it is replaced, the run took a while",
        "file": ENGINE,
        "anchor": "        if report.exists() and not is_results_file(report):\n            os.unlink(made)",
        "replacement": "        if False:\n            os.unlink(made)",
        "suite": "unit",
        "tests": [f"{ONE_MOMENT}::test_the_results_are_written_by_replacing_the_entry_after_a_second_look"],
    },
    {
        "id": "EN-30",
        "rule": "a results file's records hold values of a result's types, a record of the keys alone is not one",
        "file": ENGINE,
        "anchor": (
            "        isinstance(record[key], kind) and not isinstance(record[key], bool) for key, kind in "
            "_RESULT_TYPES.items()"
        ),
        "replacement": "        True for key, kind in _RESULT_TYPES.items()",
        "suite": "unit",
        "tests": [f"{GIT_ACTS}::test_only_the_runner_s_own_shape_is_a_results_file"],
    },
    {
        "id": "EN-31",
        "rule": "a removal git refuses is reported with git's words and exit 2, never as a traceback",
        "file": ENGINE,
        "anchor": (
            "            except subprocess.CalledProcessError as error:\n"
            '                print(f"the worktree could not be removed, {_said(error)}")\n'
            "                return 2"
        ),
        "replacement": (
            "            except ValueError as error:\n"
            '                print(f"the worktree could not be removed, {error}")\n'
            "                return 2"
        ),
        "suite": "unit",
        "tests": [f"{ONE_MOMENT}::test_a_removal_git_refuses_is_reported_and_not_a_traceback"],
    },
    {
        "id": "EN-32",
        "rule": "a forced checkout or a clean git refuses is reported with git's words, never as a traceback",
        "file": ENGINE,
        "anchor": (
            "    except subprocess.CalledProcessError as error:\n"
            '        raise WorktreeError(f"git {args[0]} failed in {worktree}, {_said(error)}") from error'
        ),
        "replacement": (
            "    except ValueError as error:\n"
            '        raise WorktreeError(f"git {args[0]} failed in {worktree}, {error}") from error'
        ),
        "suite": "unit",
        "tests": [f"{ONE_MOMENT}::test_an_act_git_refuses_is_reported_and_not_a_traceback"],
    },
    {
        "id": "EN-33",
        "rule": "a file that could not be restored stops the run with the reason and exit 2, never as a traceback",
        "file": ENGINE,
        "anchor": (
            "            except RuntimeError as error:\n"
            '                print(f"the run stopped, {error}")\n'
            "                return 2"
        ),
        "replacement": (
            "            except ValueError as error:\n"
            '                print(f"the run stopped, {error}")\n'
            "                return 2"
        ),
        "suite": "unit",
        "tests": [f"{ONE_MOMENT}::test_a_restore_that_fails_stops_the_run_with_the_reason"],
    },
    {
        "id": "EN-34",
        "rule": "the folders the runner makes for its worktree are its own, mode 0o700, the temp folder is shared",
        "file": ENGINE,
        "anchor": "            folder.mkdir(mode = 0o700)",
        "replacement": "            folder.mkdir()",
        "suite": "unit",
        "tests": [f"{ONE_MOMENT}::test_the_folders_the_worktree_stands_in_are_made_the_runner_s_own"],
        "platform": "linux",
    },
    {
        "id": "EN-35",
        "rule": "a folder the worktree stands in that is another user's is refused, they could swap a link in",
        "file": ENGINE,
        "anchor": '        if sys.platform != "win32" and found.st_uid != os.getuid():',
        "replacement": "        if False:",
        "suite": "unit",
        "tests": [f"{ONE_MOMENT}::test_a_folder_of_another_user_s_is_refused"],
        "platform": "linux",
    },
    {
        "id": "EN-36",
        "rule": "a mutant's tests import the worktree's package, not the installed repo's",
        "file": ENGINE,
        "anchor": '    if worktree is not None and (worktree / "src").is_dir():',
        "replacement": "    if False:",
        "suite": "unit",
        "tests": [SRC_FIRST],
    },
    {
        "id": "EN-37",
        "rule": "a mutant runs its own source, no run writes the bytecode a later mutant of the same size would load",
        "file": ENGINE,
        "anchor": '"HYPOTHESIS_PROFILE": "ci", "PYTHONDONTWRITEBYTECODE": "1"}',
        "replacement": '"HYPOTHESIS_PROFILE": "ci"}',
        "suite": "unit",
        "tests": [BYTECODE],
    },
    {
        "id": "EN-38",
        "rule": "a repo's unit settings are names mapped to strings, anything else is refused before a run",
        "file": ENGINE,
        "anchor": "    if not isinstance(settings, Mapping) or not all(\n",
        "replacement": "    if not isinstance(settings, Mapping) and not all(\n",
        "suite": "unit",
        "tests": [f"{SETTINGS}::test_settings_that_are_not_names_mapped_to_strings_are_refused"],
    },
    {
        "id": "EN-39",
        "rule": "a module the repo's tables package imports that is missing is the repo's error, never no settings",
        "file": ENGINE,
        "anchor": "        if error.name != TABLES_PACKAGE:\n            raise\n",
        "replacement": "        if error.name is None:\n            raise\n",
        "suite": "unit",
        "tests": [f"{SETTINGS}::test_a_module_the_package_needs_that_is_missing_is_the_repo_s_error"],
    },
    {
        "id": "EN-40",
        "rule": "the repo's function is handed a copy of the environment and changes nothing the suite gets",
        "file": ENGINE,
        "anchor": "    settings = hook(dict(environment))\n",
        "replacement": "    settings = hook(environment)\n",
        "suite": "unit",
        "tests": [f"{SETTINGS}::test_the_repo_reads_the_environment_and_changes_nothing_in_it"],
    },
    {
        "id": "EN-41",
        "rule": "the unit suite is given what the repo's tables package says it needs",
        "file": ENGINE,
        "anchor": "        env.update(unit_settings(env))\n",
        "replacement": "        unit_settings(env)\n",
        "suite": "unit",
        "tests": [
            f"{SETTINGS}::test_the_repo_s_settings_reach_the_unit_suite_and_no_other",
            f"{WHOLE_RUN}::test_a_mutant_the_repo_s_test_notices_is_killed",
        ],
    },
    {
        "id": "EN-42",
        "rule": "a repo without a tables package gives its unit suite nothing, it is not an error",
        "file": ENGINE,
        "anchor": "        return {}\n    hook = getattr(package, UNIT_SETTINGS_HOOK, None)\n",
        "replacement": "        raise\n    hook = getattr(package, UNIT_SETTINGS_HOOK, None)\n",
        "suite": "unit",
        "tests": [f"{SETTINGS}::test_a_repo_without_a_tables_package_gives_nothing"],
    },
    {
        "id": "EN-43",
        "rule": "a tables package that says nothing gives the unit suite nothing more",
        "file": ENGINE,
        "anchor": "    if hook is None:\n        return {}\n",
        "replacement": '    if hook is None:\n        return {"KDF_DEMO": "a setting nobody asked for"}\n',
        "suite": "unit",
        "tests": [f"{SETTINGS}::test_a_repo_whose_package_says_nothing_gives_its_unit_suite_nothing_more"],
    },
    {
        "id": "EN-44",
        "rule": "the engine finds its repo two folders up from either seat, scripts/kdf_scripts/ and scripts/common/",
        "file": ENGINE,
        "anchor": "REPO_ROOT: Path = Path(__file__).resolve().parents[2]",
        "replacement": "REPO_ROOT: Path = Path(__file__).resolve().parents[1]",
        "suite": "unit",
        "tests": [SEAT],
    },
]
