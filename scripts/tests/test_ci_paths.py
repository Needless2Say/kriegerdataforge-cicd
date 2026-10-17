"""
Tests for D-075's one list of what counts as docs, `scripts/common/ci_paths.py`.

The rules run here on plain path lists. The matcher for a repo's `not_docs` is held to the path examples of GitHub's
filter pattern cheat sheet, read 2026-10-16, so a pattern means the same files here and in a push filter. The scan's
answer on a real checkout, its proof of the merge and its output, is tested in `test_workflow_contracts.py`, where the
rendered copy in `secret-scan.yml` runs on fixture repos.
"""

from __future__ import annotations

import pytest
from common import ci_paths

# the "Patterns to match file paths" table of GitHub's cheat sheet, each pattern with the paths it says match and,
# beside them, paths its description leaves out. The rows using ? or ! are refused here, held below
GITHUB_EXAMPLES = [
    ("*", ["README.md", "server.rb"], ["docs/README.md"]),
    ("**", ["all/the/files.md"], []),
    ("*.js", ["app.js", "index.js"], ["js/index.js"]),
    ("**.js", ["index.js", "js/index.js", "src/js/app.js"], ["index.jsx"]),
    ("docs/*", ["docs/README.md", "docs/file.txt"], ["docs/a/b.md", "README.md"]),
    ("docs/**", ["docs/README.md", "docs/mona/octocat.txt"], ["nested/docs/a.md"]),
    ("docs/**/*.md", ["docs/README.md", "docs/mona/hello-world.md", "docs/a/markdown/guide.md"], ["docs/a.txt"]),
    ("**/docs/**", ["docs/hello.md", "dir/docs/my-file.txt", "space/docs/plan/space.doc"], ["documents/a.md"]),
    ("**/README.md", ["README.md", "js/README.md"], ["README.txt"]),
    ("**/*src/**", ["a/src/app.js", "my-src/code/js/app.js"], ["src.js"]),
    ("**/*-post.md", ["my-post.md", "path/their-post.md"], ["post.md"]),
    ("**/migrate-*.sql", ["migrate-10909.sql", "db/migrate-v1.0.sql", "db/sept/migrate-v1.sql"], ["migrate.sql"]),
]

# ======================================================================================================================
# The rules
# ======================================================================================================================

@pytest.mark.parametrize("path", [
    "docs/a.md",
    "docs/img/a.png",
    "docs/file.txt",
    "README.md",
    "AGENTS.md",
    "a/b/NOTES.md",
    "src/p/a.md",
    "docs/.hidden",
    "docs/a b.md",
    "docs/line\nbreak.md",
    "notes with space.md",
])
def test_a_docs_path_is_in_the_docs_group(path):
    assert ci_paths.groups_of(path) == {"docs"}
    assert ci_paths.docs_only([path])


@pytest.mark.parametrize("path", [
    "src/app/docs/page.tsx",
    "nested/docs/file.txt",
    "file.md.py",
    "README.MD",
    "docs.py",
    "docs",
    "docs/probe.py",
    "docs/main.tf",
    "docs/prod.tfstate",
    "docs/vars.tfvars",
    "docs/plan.tfplan",
    "docs/lock.hcl",
    "docs/run.sh",
    "docs/a.ts",
    "docs/a.tsx",
    "docs/a.js",
    "docs/a.jsx",
    "docs/a.mjs",
    "docs/a.cjs",
    "docs/a.pyi",
    "docs/main.go",
    "docs/seed.sql",
    "docs/PROBE.PY",
    "Docs/a.md.txt",
    "DOCS/a.txt",
    "VERSION",
    "Makefile",
    ".github/workflows/ci.yml",
])
def test_a_code_path_is_in_no_group(path):
    assert ci_paths.groups_of(path) == set()
    assert not ci_paths.docs_only([path])


@pytest.mark.parametrize("path", ["", "/README.md", "docs//a.md", "./docs/a.md", "docs/../src/a.md", "docs/./a.txt"])
def test_a_path_that_is_not_plain_is_never_docs(path):
    assert not ci_paths.docs_only([path])


def test_the_one_group_is_the_designs():
    assert list(ci_paths.GROUPS) == ["docs"]
    assert ci_paths.GROUPS["docs"]["folders"] == frozenset({"docs/"})
    assert ci_paths.GROUPS["docs"]["suffixes"] == frozenset({".md"})
    assert ci_paths.GROUPS["docs"]["code"] == frozenset({
        ".py",
        ".pyi",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".tf",
        ".tfvars",
        ".tfstate",
        ".tfplan",
        ".hcl",
        ".sh",
        ".go",
        ".sql",
    })


def test_an_empty_change_is_not_docs_only():
    assert not ci_paths.docs_only([])
    assert ci_paths.classify([]) == set()


def test_one_code_path_among_docs_is_not_docs_only():
    assert not ci_paths.docs_only(["docs/a.md", "README.md", "src/app.py"])
    assert ci_paths.classify(["docs/a.md", "README.md", "src/app.py"]) == set()
    assert ci_paths.classify(["docs/a.md", "README.md"]) == {"docs"}


def test_a_deletion_is_a_changed_path_like_any():
    """
    git lists a deleted file by its path, so a deleted code file makes the change code and a deleted doc stays docs.
    """
    assert ci_paths.docs_only(["docs/old.md"])
    assert not ci_paths.docs_only(["docs/a.md", "src/removed.py"])


def test_code_renamed_into_docs_is_read_as_two_paths():
    """
    With renames off, a rename is its deletion and its addition, so code moved under docs/ keeps its source in the
    change and the change is not docs only.
    """
    assert not ci_paths.docs_only(["src/tool.py", "docs/tool.md"])
    assert not ci_paths.docs_only(["src/tool.py", "docs/tool.py"])

# ======================================================================================================================
# not_docs
# ======================================================================================================================

def test_a_not_docs_pattern_takes_a_path_out_of_docs_and_wins_over_the_rule():
    assert ci_paths.docs_only(["README.md"])
    assert not ci_paths.docs_only(["README.md"], ["README.md"])
    assert ci_paths.groups_of("README.md", ci_paths.compile_not_docs(["README.md"])) == set()
    assert not ci_paths.docs_only(["docs/a.md", "README.md"], ["README.md"])
    assert ci_paths.docs_only(["docs/a.md", "a/README.md"], ["README.md"])


def test_a_pattern_star_stays_in_its_folder_and_double_star_crosses():
    assert not ci_paths.docs_only(["src/p/a.md"], ["src/p/*.md"])
    assert ci_paths.docs_only(["src/p/x/a.md"], ["src/p/*.md"])
    assert not ci_paths.docs_only(["src/p/a.md"], ["src/**"])
    assert not ci_paths.docs_only(["src/p/x/a.md"], ["src/**"])


@pytest.mark.parametrize(("pattern", "matches", "misses"), GITHUB_EXAMPLES)
def test_the_matcher_reads_githubs_documented_path_examples(pattern, matches, misses):
    expression = ci_paths.compile_pattern(pattern)
    for path in matches:
        assert expression.fullmatch(path), f"{pattern} should match {path}"
    for path in misses:
        assert not expression.fullmatch(path), f"{pattern} should not match {path}"


def test_a_pattern_matches_a_path_with_a_space_or_a_newline():
    assert ci_paths.compile_pattern("docs/*.md").fullmatch("docs/a b.md")
    assert ci_paths.compile_pattern("docs/**").fullmatch("docs/line\nbreak.md")
    assert not ci_paths.compile_pattern("docs/*").fullmatch("docs/a/b")


def test_a_dot_in_a_pattern_is_a_dot():
    assert not ci_paths.compile_pattern("README.md").fullmatch("READMEXmd")


@pytest.mark.parametrize(("pattern", "reason"), [
    ("", "empty"),
    ("/README.md", "absolute"),
    ("docs/../src/a.md", "an empty, . or .. part"),
    ("..", "an empty, . or .. part"),
    ("./README.md", "an empty, . or .. part"),
    ("docs//a.md", "an empty, . or .. part"),
    ("docs/", "an empty, . or .. part"),
    ("docs\\a.md", "a backslash"),
    ("a b.md", "white space"),
    ("*.jsx?", "one of ? + [ ] !"),
    ("a+.md", "one of ? + [ ] !"),
    ("[CB]at.md", "one of ? + [ ] !"),
    ("!README.md", "one of ? + [ ] !"),
    ("docs/{a,b}.md", "one of ? + [ ] ! { }"),
    ("app/[slug]/x.md", "write * in its place"),
])
def test_a_malformed_not_docs_pattern_refuses(pattern, reason):
    assert reason in ci_paths.malformed(pattern)
    with pytest.raises(ValueError, match = "refused"):
        ci_paths.compile_pattern(pattern)
    with pytest.raises(ValueError):
        ci_paths.docs_only(["docs/a.md"], [pattern])


def test_a_well_formed_pattern_has_no_reason():
    for pattern, _matches, _misses in GITHUB_EXAMPLES:
        assert ci_paths.malformed(pattern) == ""


def test_a_refused_character_written_as_a_star_still_names_its_path():
    """
    A path whose name holds a refused character is named with * in its place, a superset that matches it and passes
    the tracked file check, so no file a repo needs to name is out of reach.
    """
    tracked  = ["app/[slug]/x.md", "src/p/a.jsx", "docs/{draft}.md"]
    compiled = ci_paths.check_not_docs(["app/*/x.md", "src/p/*.jsx", "docs/*draft*.md"], tracked)
    assert [any(expression.fullmatch(path) for expression in compiled) for path in tracked] == [True, True, True]


def test_a_not_docs_pattern_that_matches_no_tracked_file_refuses():
    tracked = ["README.md", "src/kdf/prompts/a.md", "src/kdf/app.py"]
    assert len(ci_paths.check_not_docs(["README.md", "src/kdf/prompts/*.md"], tracked)) == 2
    with pytest.raises(ValueError, match = "matches no tracked file"):
        ci_paths.check_not_docs(["README.md", "READNE.md"], tracked)
    with pytest.raises(ValueError, match = "refused"):
        ci_paths.check_not_docs(["../README.md"], tracked)
    assert ci_paths.check_not_docs([], tracked) == []


def test_the_input_splits_on_any_white_space():
    assert ci_paths.parse_not_docs("") == []
    assert ci_paths.parse_not_docs("README.md  src/p/*.md\nsrc/q/**\n") == ["README.md", "src/p/*.md", "src/q/**"]
