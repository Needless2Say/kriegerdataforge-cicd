"""
Unit tests for scripts/deploy_stamp.py, against a fake Vercel API, with no network.
"""

from __future__ import annotations

import datetime as dt

import deploy_stamp as ds
import pytest

COMMIT = "0123456789abcdef0123456789abcdef01234567"
OTHER  = "fedcba9876543210fedcba9876543210fedcba98"


def _meta(**overrides: str) -> dict:
    meta = {
        "kdf_version": "1.4.0",
        "kdf_commit": COMMIT,
        "kdf_run_id": "45092719625",
        "kdf_run_attempt": "1",
        "kdf_started_at": "2026-11-23T01:07:30.123Z",
    }
    meta.update(overrides)
    return {key: value for key, value in meta.items() if value is not None}


def _at(text: str) -> dt.datetime:
    parsed = ds.parse_time(text)
    assert parsed is not None
    return parsed


class FakeVercel:
    """
    The project answer alone, its production target carrying the given meta, and the calls it was asked for.
    """
    def __init__(self, meta: dict | None, status: int = 200, target: bool = True) -> None:
        self.meta   = meta
        self.status = status
        self.target = target
        self.paths: list[str] = []


    def call(self, path: str) -> tuple[int, object]:
        self.paths.append(path)
        if self.status != 200:
            return self.status, {"error": {"code": "forbidden"}}
        production = {"id": "dpl_live", "meta": self.meta} if self.target else None
        return 200, {"id": "prj_1", "targets": {"production": production} if production else {}}


# ── the stamp ──────────────────────────────────────────────────────────────────
class TestReadStamp:
    """
    A deployment's stamp, read whole or not at all.
    """
    def test_a_whole_stamp_is_read(self):
        stamp = ds.read_stamp(_meta())
        assert stamp == ds.Stamp("1.4.0", COMMIT, "45092719625", "1", _at("2026-11-23T01:07:30.123Z"))


    @pytest.mark.parametrize("overrides", [
        {"kdf_version": None},
        {"kdf_version": ""},
        {"kdf_commit": "abc123"},
        {"kdf_commit": COMMIT.upper()},
        {"kdf_run_id": "x1"},
        {"kdf_run_attempt": "0"},
        {"kdf_run_attempt": None},
        {"kdf_started_at": "2026-11-23 01:07:30"},
        {"kdf_started_at": None},
    ], ids = [
        "no-version", "empty-version", "short-commit", "upper-case-commit", "run-id-not-a-number", "attempt-zero",
        "no-attempt", "a-time-not-the-stamps-shape", "no-start",
    ])
    def test_a_partial_or_malformed_stamp_is_no_stamp(self, overrides):
        assert ds.read_stamp(_meta(**overrides)) is None


    @pytest.mark.parametrize("meta", [None, {}, "kdf_version=1.4.0", ["kdf_version"]])
    def test_no_meta_is_no_stamp(self, meta):
        assert ds.read_stamp(meta) is None


    def test_the_time_keeps_its_milliseconds(self):
        assert _at("2026-11-23T01:07:30.123Z") < _at("2026-11-23T01:07:30.124Z")


# ── the bot's redeploy ─────────────────────────────────────────────────────────
class TestJudgeBot:
    """
    A bot's redeploy, the live version and commit alone.
    """
    def test_the_live_version_and_commit_are_admitted(self):
        ok, _ = ds.judge_bot(ds.read_stamp(_meta()), "1.4.0", COMMIT)
        assert ok is True


    @pytest.mark.parametrize("version, commit", [("1.3.0", COMMIT), ("1.4.0", OTHER), ("1.5.0", OTHER)])
    def test_any_version_or_commit_but_the_live_one_is_refused(self, version, commit):
        ok, reason = ds.judge_bot(ds.read_stamp(_meta()), version, commit)
        assert ok is False
        assert "live" in reason


    def test_a_live_deployment_with_no_stamp_refuses_the_bot(self):
        ok, reason = ds.judge_bot(None, "1.4.0", COMMIT)
        assert ok is False
        assert "no stamp" in reason


# ── freshness ──────────────────────────────────────────────────────────────────
class TestJudgeFresh:
    """
    The freshness rule, the owner's and a bot's alike.
    """
    @pytest.mark.parametrize("path", ["human", "bot"])
    def test_a_candidate_started_after_the_live_one_is_promoted(self, path):
        ok, _ = ds.judge_fresh(_at("2026-11-23T01:08:00.000Z"), ds.read_stamp(_meta()), path, live = True)
        assert ok is True


    @pytest.mark.parametrize("path", ["human", "bot"])
    def test_a_candidate_started_before_the_live_one_is_refused_for_the_owner_and_the_bot(self, path):
        ok, reason = ds.judge_fresh(_at("2026-11-23T01:07:30.122Z"), ds.read_stamp(_meta()), path, live = True)
        assert ok is False
        assert "before" in reason


    def test_a_legacy_live_deployment_lets_the_owner_promote_and_says_so(self):
        ok, reason = ds.judge_fresh(_at("2026-11-23T01:08:00.000Z"), None, "human", live = True)
        assert ok is True
        assert "no stamp" in reason


    def test_a_legacy_live_deployment_refuses_the_bot(self):
        ok, reason = ds.judge_fresh(_at("2026-11-23T01:08:00.000Z"), None, "bot", live = True)
        assert ok is False
        assert "no stamp" in reason


    def test_the_first_deployment_of_a_project_lets_the_owner_promote(self):
        ok, reason = ds.judge_fresh(_at("2026-11-23T01:08:00.000Z"), None, "human", live = False)
        assert ok is True
        assert "no live deployment" in reason


    def test_a_project_with_no_live_deployment_refuses_the_bot(self):
        ok, _ = ds.judge_fresh(_at("2026-11-23T01:08:00.000Z"), None, "bot", live = False)
        assert ok is False


# ── the command line, against the fake API ─────────────────────────────────────
@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("VERCEL_TOKEN", "a-scratch-token-value")
    monkeypatch.setenv("VERCEL_ORG_ID", "team_scratch")
    monkeypatch.setenv("VERCEL_PROJECT_ID", "prj_1")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    return summary


class TestMain:
    """
    The command line against the fake API, failing closed and never printing the token.
    """
    def test_the_bot_check_passes_for_the_live_release(self, env, capsys):
        api = FakeVercel(_meta())
        assert ds.main(["bot", "--version", "1.4.0", "--commit", COMMIT], api = api) == 0
        assert api.paths == ["/v9/projects/prj_1"]
        assert "a-scratch-token-value" not in capsys.readouterr().out + env.read_text(encoding = "utf-8")


    def test_the_bot_check_refuses_another_commit(self, env, capsys):
        assert ds.main(["bot", "--version", "1.4.0", "--commit", OTHER], api = FakeVercel(_meta())) == 1
        assert "::error::" in capsys.readouterr().out


    def test_the_bot_check_refuses_a_project_with_no_live_deployment(self, env):
        assert ds.main(["bot", "--version", "1.4.0", "--commit", COMMIT], api = FakeVercel(None, target = False)) == 1


    @pytest.mark.parametrize("command", [
        ["bot", "--version", "1.4.0", "--commit", COMMIT],
        ["fresh", "--started", "2026-11-23T01:08:00.000Z", "--path", "human"],
    ])
    def test_a_project_the_api_does_not_answer_fails_closed(self, env, command):
        assert ds.main(command, api = FakeVercel(_meta(), status = 403)) == 1


    def test_the_freshness_check_refuses_an_older_candidate(self, env):
        argv = ["fresh", "--started", "2026-11-23T01:07:00.000Z", "--path", "human"]
        assert ds.main(argv, api = FakeVercel(_meta())) == 1


    def test_the_freshness_check_writes_the_legacy_line_into_the_summary(self, env):
        argv = ["fresh", "--started", "2026-11-23T01:08:00.000Z", "--path", "human"]
        assert ds.main(argv, api = FakeVercel({"some": "meta"})) == 0
        assert "no stamp" in env.read_text(encoding = "utf-8")


    def test_a_start_not_in_the_stamps_shape_fails_closed(self, env):
        argv = ["fresh", "--started", "yesterday", "--path", "human"]
        assert ds.main(argv, api = FakeVercel(_meta())) == 1


    @pytest.mark.parametrize("name", ["VERCEL_TOKEN", "VERCEL_PROJECT_ID"])
    def test_a_missing_token_or_project_fails_closed_before_any_call(self, env, monkeypatch, name):
        monkeypatch.delenv(name)
        assert ds.main(["bot", "--version", "1.4.0", "--commit", COMMIT]) == 1


    def test_the_api_is_scoped_to_a_team_alone(self, monkeypatch):
        assert ds.Vercel("t", "team_abc").scope == {"teamId": "team_abc"}
        assert ds.Vercel("t", "").scope == {}
