"""
Unit tests for scripts/common/repo_sync.py — the generic SyncItem fan-out loops
used by distribute_scripts.py. All network I/O is mocked. (distribute_kit.py keeps
its own loops; those are covered by test_distribute_kit.py, which must keep passing
unchanged — it is the regression alarm for the engine extraction.)
"""

from __future__ import annotations

from unittest.mock import patch

import common.repo_sync as rs

REPOS = [
    {"repo": "Needless2Say/repo-a", "branch": "main"},
    {"repo": "Needless2Say/repo-b", "branch": "main"},
]


def _file_item(dest: str, content: str) -> rs.SyncItem:
    return rs.SyncItem(dest = dest, desired = lambda _remote, c = content: c)


def _patch_item(dest: str) -> rs.SyncItem:
    # Mirrors the real patcher's contract: idempotent, PatchError when unpatchable.
    def patch_fn(remote: str | None) -> str:
        if remote is not None and "patched" in remote:
            return remote
        if remote is None or "anchor" not in remote:
            raise rs.PatchError(f"{dest}: anchor missing")
        return remote.replace("anchor", "patched")


    return rs.SyncItem(dest = dest, desired = patch_fn)


# ── compute_item_drift ───────────────────────────────────────────────────────
def test_drift_detects_diff_and_missing():
    items = [_file_item("a.md", "same"), _file_item("b.md", "new"), _file_item("c.md", "x")]


    def fake_remote(_token, _repo, _branch, path):
        return {"a.md": ("same", "sha"), "b.md": ("old", "sha")}.get(path, (None, None))


    with patch.object(rs, "_get_remote_file", side_effect = fake_remote):
        drift = rs.compute_item_drift("tok", "o/r", "main", items)
    assert [i.dest for i in drift] == ["b.md", "c.md"]


def test_drift_normalizes_line_endings():
    with patch.object(rs, "_get_remote_file", return_value = ("x\r\ny\r\n", "sha")):
        assert rs.compute_item_drift("tok", "o/r", "main", [_file_item("a.md", "x\ny\n")]) == []


def test_drift_patch_item_computed_from_remote():
    with patch.object(rs, "_get_remote_file", return_value = ("has anchor here", "sha")):
        drift = rs.compute_item_drift("tok", "o/r", "main", [_patch_item("Makefile")])
    assert [i.dest for i in drift] == ["Makefile"]
    with patch.object(rs, "_get_remote_file", return_value = ("has patched here", "sha")):
        assert rs.compute_item_drift("tok", "o/r", "main", [_patch_item("Makefile")]) == []


def test_drift_delete_item_drifts_iff_exists():
    stale = rs.SyncItem(dest = "old.py", desired = None)
    with patch.object(rs, "_get_remote_file", return_value = ("still here", "sha")):
        assert [i.dest for i in rs.compute_item_drift("tok", "o/r", "main", [stale])] == ["old.py"]
    with patch.object(rs, "_get_remote_file", return_value = (None, None)):
        assert rs.compute_item_drift("tok", "o/r", "main", [stale]) == []


# ── callable per-repo items ──────────────────────────────────────────────────
def test_callable_items_resolved_per_repo():
    built: list[str] = []


    def items_for(entry):
        built.append(entry["repo"])
        return [_file_item(f"{entry['repo'].split('/')[-1]}.md", "x")]


    with patch.object(rs, "_get_remote_file", return_value = ("x", "sha")):
        rc = rs.run_check("tok", REPOS, items_for, "banner")
    assert rc == 0
    assert built == ["Needless2Say/repo-a", "Needless2Say/repo-b"]


# ── run_check ────────────────────────────────────────────────────────────────
def test_run_check_in_sync_returns_0():
    with patch.object(rs, "compute_item_drift", return_value = []):
        assert rs.run_check("tok", REPOS, [_file_item("a.md", "x")], "banner") == 0


def test_run_check_drift_returns_1():
    with patch.object(rs, "compute_item_drift", side_effect = [[_file_item("a.md", "x")], []]):
        assert rs.run_check("tok", REPOS, [_file_item("a.md", "x")], "banner") == 1


def test_run_check_patch_error_flags_repo_but_continues(capsys):
    checked: list[str] = []


    def fake_drift(_token, repo, _branch, _items):
        checked.append(repo)
        if repo.endswith("repo-a"):
            raise rs.PatchError("no anchor")
        return []


    with patch.object(rs, "compute_item_drift", side_effect = fake_drift):
        rc = rs.run_check("tok", REPOS, [_patch_item("Makefile")], "banner")
    assert rc == 1
    assert checked == ["Needless2Say/repo-a", "Needless2Say/repo-b"]   # fan-out continued
    assert "NEEDS MANUAL ATTENTION" in capsys.readouterr().out


# ── run_distribute ───────────────────────────────────────────────────────────
def _distribute(items, **patches):
    defaults = {
        "_get_branch_sha": {"return_value": "basesha"},
        "_create_branch": {},
        "_put_file": {},
        "_create_pr": {"return_value": "https://pr"},
    }
    defaults.update(patches)
    ctxs  = {name: patch.object(rs, name, **kwargs) for name, kwargs in defaults.items()}
    mocks = {}
    for name, ctx in ctxs.items():
        mocks[name] = ctx.start()
    try:
        rc = rs.run_distribute(
            "tok",
            REPOS,
            items,
            sync_branch = "chore/scripts-sync-1.0.0",
            pr_title = "title",
            pr_body_fn = lambda drift: "body",
            commit_msg_fn = lambda item: f"sync {item.dest}",
        )
    finally:
        for ctx in ctxs.values():
            ctx.stop()
    return rc, mocks


def test_distribute_opens_pr_for_drifted_repo():
    item = _file_item("a.md", "new")
    with patch.object(rs, "_get_remote_file", return_value = ("old", "sha")):
        rc, mocks = _distribute([item])
    assert rc == 0
    assert mocks["_create_pr"].call_count == 2          # both repos drifted
    assert mocks["_put_file"].call_count == 2
    # content pushed is the DESIRED content, recomputed on the sync branch
    assert mocks["_put_file"].call_args[0][4] == "new"


def test_distribute_skips_in_sync_repo():
    item = _file_item("a.md", "same")
    with patch.object(rs, "_get_remote_file", return_value = ("same", "sha")):
        rc, mocks = _distribute([item])
    assert rc == 0
    mocks["_create_pr"].assert_not_called()


def test_distribute_skips_put_when_sync_branch_current():
    """
    Re-run against an existing sync branch that already carries the fix: drift is
    computed vs main (drifted), but the sync-branch copy is already desired -> no
    duplicate commit, PR creation still attempted (422-reuse handled upstream).
    """
    item  = _file_item("a.md", "new")
    calls = {"n": 0}


    def fake_remote(_token, _repo, branch, _path):
        calls["n"] += 1
        return ("old", "sha") if branch == "main" else ("new", "sha")


    with patch.object(rs, "_get_remote_file", side_effect = fake_remote):
        rc, mocks = _distribute([item])
    assert rc == 0
    mocks["_put_file"].assert_not_called()


def test_distribute_patch_error_does_not_abort_fanout(capsys):
    """
    repo-a's Makefile has no anchor (PatchError); repo-b must still get its PR.
    """
    item = _patch_item("Makefile")


    def fake_remote(_token, repo, _branch, _path):
        return ("no marker here", "sha") if repo.endswith("repo-a") else ("has anchor here", "sha")


    with patch.object(rs, "_get_remote_file", side_effect = fake_remote):
        rc, mocks = _distribute([item])
    assert rc == 1                                       # repo-a needs a human
    assert mocks["_create_pr"].call_count == 1           # repo-b still synced
    assert "NEEDS MANUAL ATTENTION" in capsys.readouterr().out


def test_distribute_deletes_stale_file_on_sync_branch():
    stale = rs.SyncItem(dest = "old.py", desired = None)
    with patch.object(rs, "_get_remote_file", return_value = ("still here", "blobsha")):
        rc, mocks = _distribute([stale], _delete_file = {})
    assert rc == 0
    assert mocks["_delete_file"].call_count == 2          # both repos carried the stale file
    args = mocks["_delete_file"].call_args[0]
    assert args[3] == "old.py"                            # path
    assert args[4] == "blobsha"                           # sha required by the Contents API
    mocks["_put_file"].assert_not_called()


def test_distribute_delete_skips_when_already_gone_on_sync_branch():
    """
    Drift computed vs main (file exists there), but the sync branch already deleted
    it on a previous run -> no duplicate delete call, PR still opened.
    """
    stale = rs.SyncItem(dest = "old.py", desired = None)


    def fake_remote(_token, _repo, branch, _path):
        return ("still here", "sha") if branch == "main" else (None, None)


    with (
        patch.object(rs, "_get_remote_file", side_effect = fake_remote),
        patch.object(rs, "_delete_file") as delete_file,
    ):
        rc, mocks = _distribute([stale])
    assert rc == 0
    delete_file.assert_not_called()
    assert mocks["_create_pr"].call_count == 2


def test_distribute_api_failure_reported():
    item = _file_item("a.md", "new")
    with (
        patch.object(rs, "_get_remote_file", return_value = ("old", "sha")),
    ):
        rc, _mocks = _distribute([item], _get_branch_sha = {"side_effect": RuntimeError("api down")})
    assert rc == 1
