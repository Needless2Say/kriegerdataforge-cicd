"""
Tests for scripts/token_generations.py, the shared Vercel deployment token's generations (the secrets fence, step 10,
design 5.5). A stateful fake Vercel and a durable fake record stand in for the providers, the engine is built again
between runs as a restart, and each test asserts the exact set of valid token ids and that no target holds a revoked
token. The due job and the six hour boundary run on an injected clock. The deploy's compare runs as a script.
"""

from __future__ import annotations

# standard imports
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

# third party imports
import pytest
import rotate_secret as rs
import token_generations as tg

# ======================================================================================================================
# Configuration
# ======================================================================================================================

ROOT      = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
CHECK     = ROOT / ".github" / "actions" / "token-generation" / "check.sh"
NAME      = "VERCEL_DEPLOYMENT_TOKEN"
TARGETS   = ["Needless2Say/app-a:dev", "Needless2Say/app-a:prod", "Needless2Say/app-b:dev", "Needless2Say/app-b:prod"]
COPIES    = ["Needless2Say/app-a", "Needless2Say/app-b"]
START     = datetime(2026, 12, 1, 9, 0, tzinfo = timezone.utc)

# ======================================================================================================================
# The fakes
# ======================================================================================================================

class Clock:
    """
    A clock the test moves.
    """
    def __init__(self, now: datetime = START) -> None:
        self.now = now


    def __call__(self) -> datetime:
        return self.now


    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


class FakeVercel:
    """
    Vercel's token list, each token valid until revoked.
    """
    def __init__(self) -> None:
        self.tokens: dict[str, dict[str, str]] = {}
        self.count = 0
        self.fail_revoke: set[str] = set()


    def names(self, name: str) -> list[str]:
        return [token_id for token_id, token in self.tokens.items() if token["name"] == name]


    def mint(self, name: str) -> tuple[str, str]:
        self.count += 1
        token_id = f"tok{self.count}"
        value    = f"value-{self.count}"
        self.tokens[token_id] = {"name": name, "value": value}
        return token_id, value


    def revoke(self, token_id: str) -> None:
        if token_id in self.fail_revoke:
            raise RuntimeError(f"Vercel refused the delete of {token_id}")
        self.tokens.pop(token_id, None)


    def valid(self) -> set[str]:
        return set(self.tokens)


    def valid_values(self) -> set[str]:
        return {token["value"] for token in self.tokens.values()}


class FakeGitHub:
    """
    Each target's environment secret and variable, the repository copies, cicd's record and its public facts, each
    write able to fail or lose its answer.
    """
    def __init__(self) -> None:
        self.secrets:       dict[str, str]      = {}
        self.variables:     dict[str, str]    = {}
        self.repo_copies:   dict[str, str]  = {repo: "value-era" for repo in COPIES}
        self.record:        str | None           = None
        self.facts:         str | None            = None
        self.fail_write:    set[str]         = set()
        self.fail_variable: set[str]      = set()
        self.lost_answer:   set[str]        = set()
        self.fail_delete:   set[str]        = set()
        self.saves_left:    int | None       = None
        self.fail_facts:    bool             = False


    def write_secret(self, target: str, name: str, value: str) -> None:
        if target in self.fail_write:
            raise RuntimeError(f"GitHub refused the write to {target}")
        self.secrets[target] = value
        if target in self.lost_answer:
            raise RuntimeError(f"the answer from {target} was lost")


    def write_variable(self, target: str, name: str, value: str) -> None:
        if target in self.fail_variable:
            raise RuntimeError(f"GitHub refused the variable in {target}")
        self.variables[target] = value


    def delete_repo_secret(self, repo: str, name: str) -> None:
        if repo in self.fail_delete:
            raise RuntimeError(f"GitHub refused the delete in {repo}")
        self.repo_copies.pop(repo, None)


    def read_record(self) -> str | None:
        return self.record


    def write_record(self, text: str) -> None:
        if self.saves_left is not None:
            if self.saves_left == 0:
                raise RuntimeError("GitHub refused the record's write")
            self.saves_left -= 1
        self.record = text


    def write_facts(self, text: str) -> None:
        if self.fail_facts:
            raise RuntimeError("GitHub refused the facts' write")
        self.facts = text


def engine(github: FakeGitHub, vercel: FakeVercel, clock: Clock, targets: list[str] | None = None) -> tg.Engine:
    """
    A fresh engine on the same providers, a restart between runs.
    """
    return tg.Engine(github, vercel, targets or TARGETS, COPIES, NAME, NAME, clock)


def reaper(github: FakeGitHub, vercel: FakeVercel, clock: Clock) -> tg.Engine:
    """
    An engine with no repository copy, as after their retirement, so a reap tests its other rules alone.
    """
    return tg.Engine(github, vercel, TARGETS, [], NAME, NAME, clock)


def record(github: FakeGitHub) -> dict:
    return json.loads(github.record)


def holders_valid(github: FakeGitHub, vercel: FakeVercel) -> bool:
    """
    Whether every target holds a token Vercel still accepts.
    """
    return all(value in vercel.valid_values() for value in github.secrets.values())


@pytest.fixture
def world() -> tuple[FakeGitHub, FakeVercel, Clock]:
    return FakeGitHub(), FakeVercel(), Clock()

# ======================================================================================================================
# The rotation
# ======================================================================================================================

class TestRotate:
    """
    A generation recorded before any write, each target saved as it lands.
    """
    def test_a_complete_generation_writes_every_target_with_its_variable(self, world: tuple) -> None:
        github, vercel, clock = world
        assert engine(github, vercel, clock).rotate() == []
        gen = record(github)["generations"][-1]
        assert gen["id"] == "G1" and gen["completed_at"] == clock.now.isoformat()
        assert set(gen["written"]) == set(TARGETS)
        fingerprint = hashlib.sha256(b"value-1").hexdigest()[:16]
        assert set(github.variables.values()) == {f"G1:{fingerprint}"}
        assert set(github.secrets.values()) == {"value-1"}


    def test_the_record_is_pending_before_any_target_is_written(self, world: tuple) -> None:
        github, vercel, clock = world
        github.fail_write = set(TARGETS)
        engine(github, vercel, clock).rotate()
        gen = record(github)["generations"][-1]
        assert gen["completed_at"] is None and gen["written"] == {}
        assert github.secrets == {}


    def test_tokens_of_the_name_before_the_first_generation_are_its_predecessors(self, world: tuple) -> None:
        github, vercel, clock = world
        era, _ = vercel.mint(NAME)
        other, _ = vercel.mint("SOMETHING_ELSE")
        engine(github, vercel, clock).rotate()
        tokens = record(github)["tokens"]
        assert tokens[era] == {"generation": None, "revoked": None}
        assert other not in tokens


    def test_a_failed_record_save_stops_the_run_and_revokes_the_new_token(self, world: tuple) -> None:
        github, vercel, clock = world
        era, _ = vercel.mint(NAME)
        github.saves_left = 0
        with pytest.raises(tg.RecordError):
            engine(github, vercel, clock).rotate()
        assert vercel.valid() == {era}
        assert github.secrets == {}


    def test_a_failed_save_after_a_write_stops_the_run_with_the_generation_incomplete(self, world: tuple) -> None:
        github, vercel, clock = world
        engine(github, vercel, clock).rotate()
        github.saves_left = 2
        with pytest.raises(tg.RecordError):
            engine(github, vercel, clock).rotate()
        gen = record(github)["generations"][-1]
        assert gen["id"] == "G2" and len(gen["written"]) == 1 and gen["completed_at"] is None
        assert holders_valid(github, vercel)


    def test_a_run_that_stops_part_way_is_tried_again_the_next_day(self, world: tuple) -> None:
        github, vercel, clock = world
        github.saves_left = 2
        with pytest.raises(tg.RecordError):
            engine(github, vercel, clock).rotate()
        assert tg.parse_facts(github.facts)["state"] == "pending"
        assert tg.due(github.facts, clock.now + timedelta(days = 1)) == "rotate"


    def test_an_interrupted_newer_generation_is_not_hidden_behind_an_older_one(self, world: tuple) -> None:
        github, vercel, clock = world
        engine(github, vercel, clock).rotate()
        clock.advance(days = 1)
        github.saves_left = 2
        with pytest.raises(tg.RecordError):
            engine(github, vercel, clock).rotate()
        facts = tg.parse_facts(github.facts)
        assert facts["generation"] == "G2" and facts["state"] == "pending"
        assert tg.due(github.facts, clock.now + timedelta(days = 1)) == "rotate"


    def test_facts_that_cannot_say_pending_stop_the_run_before_any_write(self, world: tuple) -> None:
        github, vercel, clock = world
        github.fail_facts = True
        with pytest.raises(tg.RecordError, match = "pending"):
            engine(github, vercel, clock).rotate()
        assert github.secrets == {}
        assert record(github)["generations"] == [] and vercel.valid() == set()
        assert record(github)["tokens"]["tok1"] == {"generation": None, "revoked": clock.now.isoformat()}


    def test_a_withdrawn_generation_leaves_the_older_one_and_its_facts_agreeing(self, world: tuple) -> None:
        github, vercel, clock = world
        engine(github, vercel, clock).rotate()
        g1    = record(github)["generations"][-1]["token_id"]
        facts = github.facts
        clock.advance(days = 1)
        github.fail_facts = True
        with pytest.raises(tg.RecordError):
            engine(github, vercel, clock).rotate()
        assert record(github)["generations"][-1]["id"] == "G1" and github.facts == facts
        assert vercel.valid() == {g1} and holders_valid(github, vercel)


    def test_a_withdrawn_token_vercel_refused_to_revoke_is_reaped_by_the_next_generation(self, world: tuple) -> None:
        github, vercel, clock = world
        github.fail_facts  = True
        vercel.fail_revoke = {"tok1"}
        with pytest.raises(tg.RecordError):
            engine(github, vercel, clock).rotate()
        assert record(github)["tokens"]["tok1"] == {"generation": None, "revoked": None}
        github.fail_facts  = False
        vercel.fail_revoke = set()
        engine(github, vercel, clock).rotate()
        clock.advance(hours = 6)
        reaper(github, vercel, clock).reap()
        assert "tok1" not in vercel.valid()


    def test_a_lost_write_answer_leaves_the_target_unrecorded(self, world: tuple) -> None:
        github, vercel, clock = world
        github.lost_answer = {TARGETS[0]}
        errors             = engine(github, vercel, clock).rotate()
        gen                = record(github)["generations"][-1]
        assert errors and TARGETS[0] not in gen["written"] and gen["completed_at"] is None


    def test_a_failed_variable_leaves_the_target_unrecorded(self, world: tuple) -> None:
        github, vercel, clock = world
        github.fail_variable = {TARGETS[1]}
        engine(github, vercel, clock).rotate()
        assert TARGETS[1] not in record(github)["generations"][-1]["written"]


    def test_generations_are_numbered_on_and_the_record_keeps_the_last_twelve(self, world: tuple) -> None:
        github, vercel, clock = world
        for _ in range(14):
            engine(github, vercel, clock).rotate()
            clock.advance(days = 1)
        gens = record(github)["generations"]
        assert len(gens) == 12 and gens[0]["id"] == "G3" and gens[-1]["id"] == "G14"


    def test_a_malformed_record_stops_the_run_before_a_mint(self, world: tuple) -> None:
        github, vercel, clock = world
        github.record = "{not json"
        with pytest.raises(tg.RecordError):
            engine(github, vercel, clock).rotate()
        assert vercel.valid() == set()


    def test_the_public_facts_name_the_newest_generation(self, world: tuple) -> None:
        github, vercel, clock = world
        engine(github, vercel, clock).rotate()
        facts = tg.parse_facts(github.facts)
        assert facts["generation"] == "G1" and facts["state"] == "complete" and facts["outstanding"] == "0"

# ======================================================================================================================
# The reap
# ======================================================================================================================

class TestReap:
    """
    The predecessors revoked only for a complete newest generation, six hours after its last write.
    """
    def test_a_complete_a_a_partial_b_and_a_reap_keep_every_holder_valid(self, world: tuple) -> None:
        github, vercel, clock = world
        engine(github, vercel, clock).rotate()
        a_token = record(github)["generations"][-1]["token_id"]
        clock.advance(days = 1)
        github.fail_write = {TARGETS[2]}
        engine(github, vercel, clock).rotate()
        b_token = record(github)["generations"][-1]["token_id"]
        clock.advance(hours = 7)
        with pytest.raises(tg.Refused, match = "incomplete"):
            reaper(github, vercel, clock).reap()
        assert vercel.valid() == {a_token, b_token} and holders_valid(github, vercel)
        github.fail_write = set()
        engine(github, vercel, clock).rotate()
        c_token = record(github)["generations"][-1]["token_id"]
        clock.advance(hours = 6)
        assert reaper(github, vercel, clock).reap() == []
        assert vercel.valid() == {c_token} and holders_valid(github, vercel)


    def test_the_reap_waits_six_hours_after_the_last_write(self, world: tuple) -> None:
        github, vercel, clock = world
        era, _ = vercel.mint(NAME)
        engine(github, vercel, clock).rotate()
        clock.advance(hours = 6, seconds = -1)
        with pytest.raises(tg.Refused, match = "six hours"):
            reaper(github, vercel, clock).reap()
        assert era in vercel.valid()
        clock.advance(seconds = 1)
        reaper(github, vercel, clock).reap()
        assert era not in vercel.valid()
        assert record(github)["tokens"][era]["revoked"] == clock.now.isoformat()


    def test_a_replaced_generation_is_never_reaped(self, world: tuple) -> None:
        github, vercel, clock = world
        engine(github, vercel, clock).rotate()
        github.fail_write = set(TARGETS)
        engine(github, vercel, clock).rotate()
        clock.advance(days = 2)
        with pytest.raises(tg.Refused, match = "incomplete"):
            reaper(github, vercel, clock).reap()
        assert len(vercel.valid()) == 2


    def test_a_failed_revoke_is_kept_for_the_next_reap(self, world: tuple) -> None:
        github, vercel, clock = world
        era, _ = vercel.mint(NAME)
        engine(github, vercel, clock).rotate()
        clock.advance(hours = 6)
        vercel.fail_revoke = {era}
        assert reaper(github, vercel, clock).reap()
        assert record(github)["tokens"][era]["revoked"] is None
        vercel.fail_revoke = set()
        assert reaper(github, vercel, clock).reap() == []
        assert era not in vercel.valid()


    def test_the_routine_reap_waits_until_every_repository_copy_is_retired(self, world: tuple) -> None:
        github, vercel, clock = world
        era, _ = vercel.mint(NAME)
        engine(github, vercel, clock).rotate()
        clock.advance(hours = 7)
        assert tg.parse_facts(github.facts)["copies"] == "kept"
        assert tg.due(github.facts, clock.now) == "none"
        with pytest.raises(tg.Refused, match = "retire-repo-copies"):
            engine(github, vercel, clock).reap()
        assert era in vercel.valid()
        verified = ",".join(target.split("/", 1)[1] for target in TARGETS)
        engine(github, vercel, clock).retire_repo_copies("G1", verified)
        assert tg.parse_facts(github.facts)["copies"] == "retired"
        assert tg.parse_facts(github.facts)["settled"] == clock.now.isoformat()
        # a job that read a repository copy just before its deletion still finishes on a valid token
        assert tg.due(github.facts, clock.now + timedelta(hours = 5, minutes = 59)) == "none"
        with pytest.raises(tg.Refused, match = "six hours"):
            engine(github, vercel, clock).reap()
        clock.advance(hours = 6)
        assert tg.due(github.facts, clock.now) == "reap"
        engine(github, vercel, clock).reap()
        assert era not in vercel.valid()


    def test_the_six_hours_count_from_the_last_of_staggered_retirements(self, world: tuple) -> None:
        github, vercel, clock = world
        era, _ = vercel.mint(NAME)
        engine(github, vercel, clock).rotate()
        verified = ",".join(target.split("/", 1)[1] for target in TARGETS)
        clock.advance(hours = 7)
        github.fail_delete = {COPIES[1]}
        engine(github, vercel, clock).retire_repo_copies("G1", verified)
        clock.advance(hours = 5)
        github.fail_delete = set()
        engine(github, vercel, clock).retire_repo_copies("G1", verified)
        last = clock.now
        clock.advance(hours = 2)
        with pytest.raises(tg.Refused, match = "six hours"):
            engine(github, vercel, clock).reap()
        assert tg.parse_facts(github.facts)["settled"] == last.isoformat()
        clock.now = last + timedelta(hours = 6)
        engine(github, vercel, clock).reap()
        assert era not in vercel.valid()


    def test_revoke_now_waits_for_no_retirement(self, world: tuple) -> None:
        github, vercel, clock = world
        era, _ = vercel.mint(NAME)
        engine(github, vercel, clock).rotate()
        engine(github, vercel, clock).revoke_now("G1")
        assert era not in vercel.valid()


    def test_a_reap_reloads_the_record_another_entry_point_changed(self, world: tuple) -> None:
        github, vercel, clock = world
        first = reaper(github, vercel, clock)
        first.rotate()
        g1 = record(github)["generations"][-1]["token_id"]
        clock.advance(days = 1)
        engine(github, vercel, clock).rotate()
        g2 = record(github)["generations"][-1]["token_id"]
        clock.advance(hours = 6)
        first.reap()
        assert vercel.valid() == {g2} and g1 not in vercel.valid()


    def test_an_orphan_from_a_crashed_mint_is_reaped_by_the_next_generation(self, world: tuple) -> None:
        github, vercel, clock = world
        engine(github, vercel, clock).rotate()
        orphan, _ = vercel.mint(NAME)
        clock.advance(days = 1)
        engine(github, vercel, clock).rotate()
        clock.advance(hours = 6)
        reaper(github, vercel, clock).reap()
        assert orphan not in vercel.valid()

# ======================================================================================================================
# The emergency revoke and the retirement of the repository copies
# ======================================================================================================================

class TestRevokeNow:
    """
    The emergency, at once and despite failed targets, for the newest generation alone.
    """
    def test_it_revokes_the_predecessors_at_once_and_names_the_targets_to_repair(self, world: tuple) -> None:
        github, vercel, clock = world
        era, _ = vercel.mint(NAME)
        github.fail_write = {TARGETS[3]}
        engine(github, vercel, clock).rotate()
        repair = engine(github, vercel, clock).revoke_now("G1")
        assert era not in vercel.valid()
        assert repair == [TARGETS[3]]
        assert record(github)["tokens"][era]["revoked"] == clock.now.isoformat()


    def test_it_refuses_a_generation_that_is_not_the_newest(self, world: tuple) -> None:
        github, vercel, clock = world
        engine(github, vercel, clock).rotate()
        engine(github, vercel, clock).rotate()
        with pytest.raises(tg.Refused, match = "newest"):
            engine(github, vercel, clock).revoke_now("G1")
        assert len(vercel.valid()) == 2


class TestRetireRepoCopies:
    """
    The repository copies deleted only for a complete newest generation and its exact verified targets.
    """
    def verified(self) -> str:
        return ",".join(target.split("/", 1)[1] for target in TARGETS)


    def test_it_deletes_every_repository_copy_and_records_each(self, world: tuple) -> None:
        github, vercel, clock = world
        engine(github, vercel, clock).rotate()
        assert engine(github, vercel, clock).retire_repo_copies("G1", self.verified()) == []
        assert github.repo_copies == {}
        assert set(record(github)["retired_repo_copies"]) == set(COPIES)


    def test_a_failed_delete_is_kept_and_the_next_run_does_only_the_rest(self, world: tuple) -> None:
        github, vercel, clock = world
        engine(github, vercel, clock).rotate()
        github.fail_delete = {COPIES[1]}
        assert engine(github, vercel, clock).retire_repo_copies("G1", self.verified())
        assert set(record(github)["retired_repo_copies"]) == {COPIES[0]}
        github.fail_delete = set()
        assert engine(github, vercel, clock).retire_repo_copies("G1", self.verified()) == []
        assert github.repo_copies == {}


    def test_an_incomplete_generation_is_refused(self, world: tuple) -> None:
        github, vercel, clock = world
        github.fail_write = {TARGETS[0]}
        engine(github, vercel, clock).rotate()
        with pytest.raises(tg.Refused, match = "incomplete"):
            engine(github, vercel, clock).retire_repo_copies("G1", self.verified())
        assert set(github.repo_copies) == set(COPIES)


    def test_a_list_missing_a_target_is_refused(self, world: tuple) -> None:
        github, vercel, clock = world
        engine(github, vercel, clock).rotate()
        short = ",".join(target.split("/", 1)[1] for target in TARGETS[:-1])
        with pytest.raises(tg.Refused, match = "app-b:prod"):
            engine(github, vercel, clock).retire_repo_copies("G1", short)
        assert set(github.repo_copies) == set(COPIES)


    def test_a_changed_target_inventory_is_refused(self, world: tuple) -> None:
        github, vercel, clock = world
        engine(github, vercel, clock).rotate()
        grown = TARGETS + ["Needless2Say/app-c:dev"]
        with pytest.raises(tg.Refused, match = "app-c:dev"):
            engine(github, vercel, clock, grown).retire_repo_copies("G1", self.verified())


    def test_a_stale_generation_s_yes_is_refused(self, world: tuple) -> None:
        github, vercel, clock = world
        engine(github, vercel, clock).rotate()
        engine(github, vercel, clock).rotate()
        with pytest.raises(tg.Refused, match = "newest"):
            engine(github, vercel, clock).retire_repo_copies("G1", self.verified())


    def test_a_list_naming_a_stranger_is_refused(self, world: tuple) -> None:
        github, vercel, clock = world
        engine(github, vercel, clock).rotate()
        with pytest.raises(tg.Refused, match = "app-z:dev"):
            engine(github, vercel, clock).retire_repo_copies("G1", self.verified() + ",app-z:dev")

# ======================================================================================================================
# The current generation's token, for the expiry fact
# ======================================================================================================================

class TestCurrentToken:
    """
    The token whose expiry alone is the fact, named only when no target can hold an older one.
    """
    def test_no_token_is_named_before_the_first_generation_or_while_one_is_incomplete(self, world: tuple) -> None:
        github, vercel, clock = world
        assert tg.current_token(engine(github, vercel, clock).load(), COPIES) == ""
        github.fail_write = {TARGETS[0]}
        engine(github, vercel, clock).rotate()
        assert tg.current_token(record(github), []) == ""


    def test_no_token_is_named_while_a_repository_copy_is_kept(self, world: tuple) -> None:
        github, vercel, clock = world
        engine(github, vercel, clock).rotate()
        assert tg.current_token(record(github), COPIES) == ""


    def test_the_newest_token_is_named_once_complete_and_every_copy_retired(self, world: tuple) -> None:
        github, vercel, clock = world
        engine(github, vercel, clock).rotate()
        verified = ",".join(target.split("/", 1)[1] for target in TARGETS)
        engine(github, vercel, clock).retire_repo_copies("G1", verified)
        assert tg.current_token(record(github), COPIES) == record(github)["generations"][-1]["token_id"]
        clock.advance(days = 31)
        github.fail_write = {TARGETS[0]}
        engine(github, vercel, clock).rotate()
        assert tg.current_token(record(github), COPIES) == "", "an incomplete newer generation names none"


    def test_the_current_mode_never_fails_and_names_none_without_a_token(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("FACTS_GH_TOKEN", raising = False)
        assert tg.main(["current"]) == 0
        assert capsys.readouterr().out.strip() == "token_id="

# ======================================================================================================================
# The daily due job
# ======================================================================================================================

class TestDue:
    """
    The daily due job's answer from the public facts, on an injected clock.
    """
    def facts(self, **fields: str) -> str:
        base = {
            "generation": "G1",
            "state": "complete",
            "minted": START.isoformat(),
            "completed": START.isoformat(),
            "outstanding": "0",
            "copies": "retired",
            "settled": START.isoformat(),
        }
        base.update(fields)
        return " ".join(f"{key}={value}" for key, value in base.items())


    def test_nothing_is_due_before_the_first_generation_the_owner_dispatches(self) -> None:
        assert tg.due("", START) == "none"
        assert tg.due("generation=none", START) == "none"


    def test_a_generation_of_an_earlier_month_makes_a_rotation_due(self) -> None:
        assert tg.due(self.facts(), START + timedelta(days = 31)) == "rotate"


    def test_an_incomplete_generation_makes_a_rotation_due_the_next_day(self) -> None:
        assert tg.due(self.facts(state = "pending", completed = "none"), START + timedelta(days = 1)) == "rotate"


    def test_outstanding_tokens_are_reaped_once_six_hours_have_passed(self) -> None:
        facts = self.facts(outstanding = "1")
        assert tg.due(facts, START + timedelta(hours = 5, minutes = 59)) == "none"
        assert tg.due(facts, START + timedelta(hours = 6)) == "reap"


    def test_no_reap_is_asked_while_a_repository_copy_is_kept(self) -> None:
        assert tg.due(self.facts(outstanding = "1", copies = "kept"), START + timedelta(hours = 7)) == "none"
        assert tg.due(self.facts(outstanding = "1", copies = ""), START + timedelta(hours = 7)) == "none"


    def test_the_six_hours_count_from_the_last_retirement(self) -> None:
        facts = self.facts(outstanding = "1", settled = (START + timedelta(days = 1)).isoformat())
        assert tg.due(facts, START + timedelta(days = 1, hours = 5)) == "none"
        assert tg.due(facts, START + timedelta(days = 1, hours = 6)) == "reap"
        assert tg.due(self.facts(outstanding = "1", settled = "none"), START + timedelta(days = 2)) == "none"


    def test_a_month_with_its_generation_complete_and_reaped_asks_nothing(self) -> None:
        assert tg.due(self.facts(), START + timedelta(days = 10)) == "none"


    def test_malformed_facts_ask_for_a_rotation_rather_than_nothing(self) -> None:
        assert tg.due("generation=G1 state=complete minted=yesterday", START) == "rotate"

# ======================================================================================================================
# The deploy's compare
# ======================================================================================================================

def compare(token: str, local: str, expected: str = "") -> str:
    """
    The compare script's one line, run as each deploy and the verifier run it.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not installed")
    env = {"PATH": str(Path(bash).parent), "TOKEN": token, "LOCAL": local, "EXPECTED": expected}
    out = subprocess.run([bash, str(CHECK)], env = env, capture_output = True, text = True, check = True)
    return out.stdout.strip().splitlines()[-1]


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


class TestCompare:
    """
    The compare each deploy and the verifier run, never relabelling an older pair.
    """
    def test_a_matching_token_says_its_own_generation_and_yes(self) -> None:
        assert compare("value-1", f"G1:{fingerprint('value-1')}") == "token generation=G1 result=yes"


    def test_a_token_written_before_its_variable_says_no(self) -> None:
        assert compare("value-2", f"G1:{fingerprint('value-1')}") == "token generation=G1 result=no"


    def test_a_missing_or_malformed_variable_says_no(self) -> None:
        assert compare("value-1", "") == "token generation=none result=no"
        assert compare("value-1", "G1-abc") == "token generation=none result=no"


    def test_the_trimmed_token_is_compared(self) -> None:
        assert compare("value-1\n", f"G1:{fingerprint('value-1')}") == "token generation=G1 result=yes"


    def test_the_expected_generation_says_yes_only_when_it_is_the_local_one(self) -> None:
        local = f"G1:{fingerprint('value-1')}"
        assert compare("value-1", local, "G1") == "token generation=G1 expected=G1 result=yes"
        assert compare("value-1", local, "G2") == "token generation=G1 expected=G2 result=stale"


    def test_an_old_pair_is_never_relabelled_as_the_expected_generation(self) -> None:
        line = compare("value-1", f"G1:{fingerprint('value-1')}", "G2")
        assert "result=yes" not in line and "generation=G2" not in line


    def test_a_mismatch_says_no_whatever_is_expected(self) -> None:
        assert compare("value-2", f"G2:{fingerprint('value-1')}", "G2") == "token generation=G2 expected=G2 result=no"


    def test_a_malformed_expected_generation_says_no(self) -> None:
        local = f"G1:{fingerprint('value-1')}"
        assert compare("value-1", local, "G1; rm") == "token generation=G1 expected=invalid result=no"


    def test_the_engine_and_the_compare_agree_on_the_fingerprint(self) -> None:
        assert tg.fingerprint("value-1\n") == fingerprint("value-1")

# ======================================================================================================================
# The registry and the workflows
# ======================================================================================================================

class TestRegistryAndWorkflows:
    """
    The registry's reversed entry and the workflows that carry the engine.
    """
    def entry(self) -> dict:
        registry = json.loads((ROOT / "scripts" / "secret_registry.json").read_text(encoding = "utf-8"))
        return next(entry for entry in registry["secrets"] if entry["name"] == NAME)


    def test_the_token_lives_in_each_repo_s_dev_and_prod_and_its_repository_copies_are_retired(self) -> None:
        entry = self.entry()
        envs  = {(t["repo"], t["environment"]) for t in entry["github_env_secrets"]}
        repos = {t["repo"] for t in entry["retired_github_repo_secrets"]}
        assert entry.get("generations") is True
        assert envs == {(repo, env) for repo in repos for env in ("dev", "prod")}
        assert "github_repo_secrets" not in entry and "retired_github_env_secrets" not in entry


    def test_rotate_secret_never_generates_the_token(self) -> None:
        with pytest.raises(SystemExit, match = "token_generations.py alone"):
            rs.cmd_generate([self.entry()], frozenset(), frozenset(), "gh", "master")


    def test_the_engine_reads_its_targets_from_the_registry(self) -> None:
        targets, copies = tg.registry_targets(self.entry())
        assert len(targets) == 2 * len(copies) and all(target.endswith((":dev", ":prod")) for target in targets)


    def test_every_entry_point_shares_one_group_that_never_cancels_a_running_job(self) -> None:
        text = (WORKFLOWS / "rotate-vercel-tokens.yml").read_text(encoding = "utf-8")
        assert "group: vercel-token-engine" in text and "cancel-in-progress: false" in text
        for mode in ("rotate", "reap", "revoke-now", "retire-repo-copies", "record-expiry", "prove-master"):
            assert f"- {mode}" in text


    def test_the_schedule_is_daily_and_its_first_job_holds_no_secret(self) -> None:
        text = (WORKFLOWS / "rotate-vercel-tokens.yml").read_text(encoding = "utf-8")
        assert 'cron: "0 9 * * *"' in text
        due = text.split("\n  due:\n", 1)[1].split("\n  authorize:\n", 1)[0]
        assert "secrets." not in due and "environment:" not in due


    def test_no_dispatch_input_carries_a_secret(self) -> None:
        text   = (WORKFLOWS / "rotate-vercel-tokens.yml").read_text(encoding = "utf-8")
        inputs = text.split("    inputs:\n", 1)[1].split("\npermissions:", 1)[0]
        names  = [line.strip()[:-1] for line in inputs.splitlines() if line.startswith("      ") and line.endswith(":")
                  and not line.startswith("        ")]
        assert names == ["mode", "generation", "verified"]


    def test_each_deploy_runs_the_compare_and_never_fails_on_it(self) -> None:
        for name in ("cd-nextjs-vercel.yml", "cd-python-vercel.yml"):
            text = (WORKFLOWS / name).read_text(encoding = "utf-8")
            assert "kriegerdataforge-cicd/.github/actions/token-generation@main" in text
            assert "vars.VERCEL_TOKEN_GENERATION" in text


    def test_the_verifier_requires_the_expected_generation(self) -> None:
        text = (WORKFLOWS / "verify-token-generation.yml").read_text(encoding = "utf-8")
        assert "expected_generation:" in text and "required: true" in text
        assert "environment: ${{ inputs.environment }}" in text
