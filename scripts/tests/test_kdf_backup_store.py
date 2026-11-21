"""
The backup store (the secrets moves, step 2, Round Table 110), kdf_backup/store.py.

Against a fake connection that keeps rows as the store would, its floor and its lock among them. The second capacity
check, the insert, the readback and the prune share one session lock. The prune counts a row only when its signature
checks over its own columns and the store's own SHA256 of its archive is its digest, ranks those by their signed time,
keeps the newest N and deletes the rest by name, the floor keeping any younger. A receipt the next run compares before
its prune catches a row that went missing.
"""

from __future__ import annotations

# standard imports
import hashlib
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

# third party imports
import pytest
from kdf_backup import archive, store


KEY:   bytes = bytes.fromhex("11" * 32)
NOW:   datetime = datetime(2026, 11, 20, 6, 30, tzinfo = UTC)
FLOOR: timedelta = timedelta(hours = 480)


def make_row(number: int, *, taken: str, inserted: datetime, data: bytes | None = None, key: bytes = KEY) -> dict:
    """
    A stored row, signed as a run signs it.

    Args:
        number: its number, which picks its backup_id
        taken: its taken_at
        inserted: its inserted_at
        data: its archive's bytes
        key: the key that signs it

    Returns:
        dict: the row
    """
    data     = data if data is not None else f"archive {number}".encode()
    metadata = {
        "backup_id": f"00000000-0000-4000-8000-{number:012d}",
        "app": "fitness",
        "environment": "prod",
        "taken_at": taken,
        "pg_dump_version": "pg_dump (PostgreSQL) 17.12",
        "server_version": "17.12",
        "size_bytes": len(data),
        "archive_sha256": hashlib.sha256(data).hexdigest(),
    }
    return {**metadata, "signature": archive.sign(metadata, key), "archive": data, "inserted_at": inserted}


class LockHeld(Exception):
    """
    The fake's lock wait running out, as psycopg's LockNotAvailable carries SQLSTATE 55P03.
    """
    sqlstate = "55P03"


class Cursor:
    """
    A fake cursor over fixed rows.
    """
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows


    def fetchone(self) -> tuple | None:
        return self.rows[0] if self.rows else None


    def fetchall(self) -> list[tuple]:
        return list(self.rows)


class FakeStore:
    """
    A connection to a store holding *rows*, its database *size* bytes, its floor as the store's own.
    """
    def __init__(
        self,
        rows: list[dict],
        size: int = 10_000_000,
        *,
        held: bool = False,
        fail_insert: bool = False,
        corrupt: bool = False,
    ) -> None:
        self.rows        = rows
        self.size        = size
        self.held        = held
        self.fail_insert = fail_insert
        self.corrupt     = corrupt
        self.statements: list[str] = []
        self.locked = False


    def execute(self, query: str, params: tuple | list = ()) -> Cursor:
        self.statements.append(query)
        if query is store.SET_LOCK_WAIT:
            return Cursor([(params[0],)])
        if query is store.LOCK:
            if self.held:
                raise LockHeld("canceling statement due to lock timeout")
            self.locked = True
            return Cursor([("",)])
        if query is store.UNLOCK:
            self.locked = False
            return Cursor([(True,)])
        if query is store.SIZE:
            return Cursor([(self.size,)])
        if query is store.ROWS:
            assert params == ("fitness", "prod")
            return Cursor([self.as_tuple(row) for row in sorted(self.rows, key = self.order, reverse = True)])
        if query is store.INSERT:
            assert self.locked, "the insert runs under the lock"
            if self.fail_insert:
                raise OSError("the store refused the write")
            names  = (
                "backup_id",
                "app",
                "environment",
                "taken_at",
                "pg_dump_version",
                "server_version",
                "size_bytes",
                "archive_sha256",
                "signature",
                "archive",
            )
            stored = {**dict(zip(names, params, strict = True)), "inserted_at": NOW}
            if self.corrupt:
                stored["archive"] = stored["archive"] + b" changed on its way in"
            self.rows.append(stored)
            self.size += len(params[-1])
            return Cursor([])
        if query is store.PRUNE:
            assert self.locked, "the prune runs under the lock"
            app, environment, names = params
            gone      = [row for row in self.rows if row["backup_id"] in names and NOW - row["inserted_at"] > FLOOR]
            self.rows = [row for row in self.rows if row not in gone]
            return Cursor([(row["backup_id"],) for row in gone])
        raise AssertionError(f"an unexpected statement {query}")


    @staticmethod
    def order(row: dict) -> tuple[str, str]:
        return row["taken_at"], row["backup_id"]


    @staticmethod
    def as_tuple(row: dict) -> tuple:
        taken = datetime.strptime(row["taken_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo = UTC)
        return (
            row["backup_id"],
            row["app"],
            row["environment"],
            taken,
            row["pg_dump_version"],
            row["server_version"],
            row["size_bytes"],
            row["archive_sha256"],
            row["signature"],
            hashlib.sha256(row["archive"]).hexdigest(),
            row["inserted_at"],
        )


def new_backup(tmp_path: Any, number: int = 99, taken: str = "2026-11-20T06:00:00Z") -> tuple[dict, str, Any]:
    """
    A run's new archive, its metadata and its signature.

    Args:
        tmp_path: pytest's folder
        number: its number
        taken: its taken_at

    Returns:
        tuple[dict, str, Any]: its metadata, its signature and its file
    """
    row  = make_row(number, taken = taken, inserted = NOW)
    path = tmp_path / f"archive-{number}.age"
    path.write_bytes(row["archive"])
    metadata = {name: row[name] for name in archive.SIGNED_FIELDS}
    return metadata, row["signature"], path


def receipt_of(rows: list[dict]) -> dict:
    """
    The receipt a run that left these rows wrote.

    Args:
        rows: the rows

    Returns:
        dict: its receipt
    """
    return store.receipt("fitness", "prod", [store.Stored.of(FakeStore.as_tuple(row)) for row in rows], [], [])


def run(connection: FakeStore, tmp_path: Any, **options: Any) -> store.Outcome:
    """
    One store step against the fake.

    Args:
        connection: the fake
        tmp_path: pytest's folder
        **options: the step's options to replace

    Returns:
        store.Outcome: its outcome
    """
    metadata, signature, path = options.pop("backup", None) or new_backup(tmp_path)
    settings: dict[str, Any] = {
        "metadata": metadata,
        "signature": signature,
        "archive_path": path,
        "key": KEY,
        "keep": 2,
        "prune": True,
        "previous": receipt_of(connection.rows),
        "capacity": 1_000_000_000,
        "lock_wait": 60,
    }
    settings.update(options)
    return store.store_backup(connection, **settings)


def week(number: int) -> str:
    """
    The taken_at of a weekly backup *number* weeks before NOW.

    Args:
        number: weeks back

    Returns:
        str: its taken_at
    """
    return (NOW - timedelta(weeks = number)).strftime("%Y-%m-%dT%H:%M:%SZ")


def old_rows() -> list[dict]:
    """
    Three weekly backups, every one inserted past the floor.

    Returns:
        list[dict]: the rows
    """
    return [make_row(n, taken = week(n + 3), inserted = NOW - timedelta(weeks = n + 3)) for n in (1, 2, 3)]

# ======================================================================================================================
# The control
# ======================================================================================================================

def test_a_backup_is_inserted_read_back_and_the_oldest_beyond_n_pruned(tmp_path: Any) -> None:
    connection = FakeStore(old_rows())

    outcome = run(connection, tmp_path)

    kept = [row["backup_id"] for row in connection.rows]
    assert kept == ["00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000099"]
    assert outcome.pruned == ["00000000-0000-4000-8000-000000000002", "00000000-0000-4000-8000-000000000003"]
    assert outcome.issues == []
    assert not connection.locked, "the lock is released"
    assert [row["backup_id"] for row in outcome.receipt["rows"]] == sorted(kept, reverse = True)


def test_the_steps_under_the_lock_run_in_their_order(tmp_path: Any) -> None:
    connection = FakeStore(old_rows())

    run(connection, tmp_path)

    order = [store.SET_LOCK_WAIT, store.LOCK, store.ROWS, store.SIZE, store.INSERT, store.ROWS, store.PRUNE]
    assert connection.statements[: len(order)] == order
    assert connection.statements[-1] is store.UNLOCK


def test_a_valid_prune_that_removes_none_is_no_failure(tmp_path: Any) -> None:
    connection = FakeStore([make_row(1, taken = week(1), inserted = NOW - timedelta(weeks = 1))])

    outcome = run(connection, tmp_path)

    assert outcome.pruned == [] and outcome.issues == []
    assert len(connection.rows) == 2

# ======================================================================================================================
# What the prune never removes
# ======================================================================================================================

def test_a_new_archive_whose_signature_fails_is_never_stored(tmp_path: Any) -> None:
    connection = FakeStore(old_rows())
    metadata, signature, path = new_backup(tmp_path)
    forged = archive.sign({**metadata, "server_version": "17.11"}, KEY)

    with pytest.raises(store.StoreError, match = "nothing is stored"):
        run(connection, tmp_path, backup = (metadata, forged, path))

    assert store.INSERT not in connection.statements


def test_a_failed_readback_prunes_none(tmp_path: Any) -> None:
    connection = FakeStore(old_rows(), corrupt = True)

    with pytest.raises(store.StoreError, match = "readback"):
        run(connection, tmp_path)

    assert store.PRUNE not in connection.statements
    assert not connection.locked


def test_a_storage_failure_before_the_prune_prunes_none(tmp_path: Any) -> None:
    connection = FakeStore(old_rows(), fail_insert = True)

    with pytest.raises(store.StoreError, match = "insert"):
        run(connection, tmp_path)

    assert store.PRUNE not in connection.statements
    assert len(connection.rows) == 3


def test_n_rows_newer_than_a_row_within_the_floor_keep_that_row(tmp_path: Any) -> None:
    within     = make_row(5, taken = week(1), inserted = NOW - timedelta(days = 3))
    newer      = [make_row(n, taken = f"2026-11-1{n}T06:00:00Z", inserted = NOW - timedelta(days = 1)) for n in (6, 7)]
    connection = FakeStore([within, *newer])

    outcome = run(connection, tmp_path)

    assert "00000000-0000-4000-8000-000000000005" in [row["backup_id"] for row in connection.rows]
    assert outcome.kept_by_floor == [
        "00000000-0000-4000-8000-000000000006",
        "00000000-0000-4000-8000-000000000005",
    ]


def test_a_row_whose_signature_fails_is_never_counted_and_kept(tmp_path: Any) -> None:
    forged     = make_row(4, taken = week(9), inserted = NOW - timedelta(weeks = 9), key = bytes.fromhex("22" * 32))
    connection = FakeStore([*old_rows(), forged])

    outcome = run(connection, tmp_path)

    assert forged in connection.rows
    assert any("00000000-0000-4000-8000-000000000004" in issue and "signature" in issue for issue in outcome.issues)
    assert "00000000-0000-4000-8000-000000000004" not in outcome.pruned


def test_a_row_whose_archive_no_longer_matches_its_digest_is_never_counted_and_kept(tmp_path: Any) -> None:
    rows = old_rows()
    rows[2]["archive"] = b"bytes changed after the signature"
    connection = FakeStore(rows)

    outcome = run(connection, tmp_path, previous = receipt_of(old_rows()))

    assert rows[2] in connection.rows
    assert any("00000000-0000-4000-8000-000000000003" in issue and "digest" in issue for issue in outcome.issues)


def test_a_pruned_row_inserted_again_ranks_by_its_signed_taken_at(tmp_path: Any) -> None:
    again      = make_row(8, taken = week(12), inserted = NOW - timedelta(days = 30))
    rows       = [*old_rows(), again]
    connection = FakeStore(rows)

    outcome = run(connection, tmp_path)

    assert "00000000-0000-4000-8000-000000000008" in outcome.pruned

# ======================================================================================================================
# The receipt
# ======================================================================================================================

def test_a_receipts_row_missing_beside_a_green_run_skips_the_prune_with_an_issue(tmp_path: Any) -> None:
    rows       = old_rows()
    previous   = receipt_of(rows)
    connection = FakeStore(rows[:2])

    outcome = run(connection, tmp_path, previous = previous)

    assert store.PRUNE not in connection.statements
    assert len(connection.rows) == 3, "the backup stands"
    assert any("missing" in issue for issue in outcome.issues)
    assert any("prune" in issue for issue in outcome.issues)


@pytest.mark.parametrize("what", ["unexplained", "changed"])
def test_an_unexplained_or_changed_row_skips_the_prune(tmp_path: Any, what: str) -> None:
    rows     = old_rows()
    previous = receipt_of(rows)
    if what == "unexplained":
        rows.append(make_row(9, taken = week(5), inserted = NOW - timedelta(weeks = 5)))
    else:
        rows[0]["inserted_at"] = NOW - timedelta(days = 2)
    connection = FakeStore(rows)

    outcome = run(connection, tmp_path, previous = previous)

    assert store.PRUNE not in connection.statements
    assert any(what in issue for issue in outcome.issues)


def test_no_receipt_for_a_scope_that_holds_rows_skips_the_prune(tmp_path: Any) -> None:
    connection = FakeStore(old_rows())

    outcome = run(connection, tmp_path, previous = None)

    assert store.PRUNE not in connection.statements
    assert any("no receipt" in issue for issue in outcome.issues)


def test_no_receipt_for_an_empty_scope_is_the_first_run(tmp_path: Any) -> None:
    connection = FakeStore([])

    outcome = run(connection, tmp_path, previous = None)

    assert outcome.issues == []
    assert [row["backup_id"] for row in outcome.receipt["rows"]] == ["00000000-0000-4000-8000-000000000099"]


def test_a_receipt_of_another_scope_is_no_receipt(tmp_path: Any) -> None:
    connection = FakeStore(old_rows())
    previous   = {**receipt_of(connection.rows), "environment": "dev"}

    outcome = run(connection, tmp_path, previous = previous)

    assert store.PRUNE not in connection.statements
    assert outcome.issues


def test_pruning_off_prunes_nothing_and_says_so(tmp_path: Any) -> None:
    connection = FakeStore(old_rows())

    outcome = run(connection, tmp_path, prune = False)

    assert store.PRUNE not in connection.statements
    assert outcome.pruned == [] and outcome.issues == []

# ======================================================================================================================
# The capacity and the lock
# ======================================================================================================================

def test_two_scopes_competing_for_the_last_of_the_store_one_is_refused(tmp_path: Any) -> None:
    capacity   = 10_000_015
    connection = FakeStore([], size = 10_000_000)

    first  = new_backup(tmp_path, number = 98)
    second = new_backup(tmp_path, number = 99)
    run(connection, tmp_path, backup = first, capacity = capacity, previous = None)
    with pytest.raises(store.StoreError, match = "capacity"):
        run(connection, tmp_path, backup = second, capacity = capacity, previous = receipt_of(connection.rows))

    assert len(connection.rows) == 1
    assert not connection.locked


def test_the_lock_held_by_another_string_fails_the_run_after_its_wait(tmp_path: Any) -> None:
    connection = FakeStore(old_rows(), held = True)

    with pytest.raises(store.StoreError, match = "60 seconds"):
        run(connection, tmp_path)

    assert store.INSERT not in connection.statements


def test_the_precheck_refuses_a_store_too_full_for_the_next_archives_bound() -> None:
    with pytest.raises(store.StoreError, match = "capacity"):
        store.precheck(FakeStore([], size = 999_000_000), capacity = 1_000_000_000, bound = 2_000_000)

    assert store.precheck(FakeStore([], size = 100), capacity = 1_000_000_000, bound = 2_000_000) == 100

# ======================================================================================================================
# The options, checked before the dump
# ======================================================================================================================

@pytest.mark.parametrize(
    "options",
    [
        {"prune": "true", "keep": ""},
        {"prune": "true", "keep": "0"},
        {"prune": "true", "keep": "two"},
        {"prune": "true", "keep": "-1"},
        {"prune": "maybe", "keep": "4"},
        {"prune": "false", "keep": "4", "capacity": "a lot"},
        {"prune": "false", "keep": "", "bound": "0"},
        {"prune": "false", "keep": "", "lock_wait": "0"},
    ],
)
def test_options_out_of_their_shape_fail_before_the_dump(options: dict[str, str]) -> None:
    settings = {"prune": "false", "keep": "", "capacity": "1000000000", "bound": "50000000", "lock_wait": "300"}
    settings.update(options)

    with pytest.raises(store.StoreError):
        store.read_options(**settings)


def test_options_in_their_shape_are_read() -> None:
    options = store.read_options(
        prune = "true",
        keep = "4",
        capacity = "1000000000",
        bound = "50000000",
        lock_wait = "300",
    )

    assert options == store.Options(
        prune = True,
        keep = 4,
        capacity = 1_000_000_000,
        bound = 50_000_000,
        lock_wait = 300,
    )
    assert store.read_options(
        prune = "false",
        keep = "",
        capacity = "1000000000",
        bound = "50000000",
        lock_wait = "300",
    ).keep is None

# ======================================================================================================================
# A connection's failure
# ======================================================================================================================

def test_a_failure_naming_its_url_is_masked() -> None:
    url  = "postgresql://backup_fitness_prod_writer:s3cr3t-pass@ep-x.c-1.us-east-1.aws.neon.tech:5432/neondb"
    text = f"could not connect with {url}, password s3cr3t-pass rejected"

    masked = store.masked(text, url)

    assert "s3cr3t-pass" not in masked
    assert "ep-x.c-1.us-east-1.aws.neon.tech" in masked

# ======================================================================================================================
# Codex's security read, each finding taken
# ======================================================================================================================

def test_a_row_that_fails_its_check_skips_the_prune_and_good_backups_stay(tmp_path: Any) -> None:
    rows = old_rows()
    rows[2]["archive"] = b"bytes changed after the signature"
    connection = FakeStore(rows)

    outcome = run(connection, tmp_path, keep = 1, previous = receipt_of(old_rows()))

    assert store.PRUNE not in connection.statements
    assert len(connection.rows) == 4
    assert any("a row fails its check" in issue for issue in outcome.issues)


@pytest.mark.parametrize(
    "entry",
    [
        {"backup_id": "not-a-uuid", "inserted_at": "x", "archive_sha256": "ab" * 32},
        {"backup_id": "00000000-0000-4000-8000-000000000001", "inserted_at": 7, "archive_sha256": "ab" * 32},
        {"backup_id": "00000000-0000-4000-8000-000000000001", "inserted_at": "x", "archive_sha256": "<b>"},
        "a row that is no object",
    ],
)
def test_a_receipt_row_out_of_its_shape_is_no_receipt(tmp_path: Any, entry: Any) -> None:
    connection = FakeStore(old_rows())
    previous   = {**receipt_of(connection.rows), "rows": [entry]}

    outcome = run(connection, tmp_path, previous = previous)

    assert store.PRUNE not in connection.statements
    assert any("out of its shape" in issue for issue in outcome.issues)


def test_a_receipt_naming_one_row_twice_is_no_receipt(tmp_path: Any) -> None:
    connection = FakeStore(old_rows())
    previous   = receipt_of(connection.rows)
    previous["rows"].append(dict(previous["rows"][0]))

    outcome = run(connection, tmp_path, previous = previous)

    assert store.PRUNE not in connection.statements
    assert outcome.issues


class Duplicate(Exception):
    """
    psycopg's UniqueViolation, a row inserted already.
    """
    sqlstate = "23505"


def test_a_rerun_whose_row_is_stored_already_finishes_by_its_readback(tmp_path: Any) -> None:
    metadata, signature, path = new_backup(tmp_path)
    earlier    = {**metadata, "signature": signature, "archive": path.read_bytes(), "inserted_at": NOW}
    connection = FakeStore([*old_rows(), earlier])
    original   = connection.execute


    def execute(query: str, params: tuple | list = ()) -> Cursor:
        if query is store.INSERT:
            connection.statements.append(query)
            raise Duplicate("duplicate key value violates unique constraint")
        return original(query, params)


    connection.execute = execute

    outcome = run(connection, tmp_path, backup = (metadata, signature, path), previous = receipt_of(old_rows()))

    assert any(row["backup_id"] == metadata["backup_id"] for row in connection.rows)
    assert any("unexplained" in issue for issue in outcome.issues), "the earlier attempt left no receipt"


def test_the_capacity_check_counts_an_allowance_beside_the_archive(tmp_path: Any) -> None:
    connection = FakeStore([], size = 999_999_990)

    with pytest.raises(store.StoreError, match = "allowance"):
        run(connection, tmp_path, capacity = 1_000_000_000, previous = None)

# ======================================================================================================================
# The connection
# ======================================================================================================================

class FakePsycopg:
    """
    A stand in for psycopg that records each connection's URL and options.
    """
    class Error(Exception):
        """
        psycopg's base error.
        """


    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []


    def connect(self, url: str, **options: Any) -> str:
        self.calls.append((url, options))
        return "a connection"


@pytest.fixture
def psycopg(monkeypatch: pytest.MonkeyPatch) -> FakePsycopg:
    fake = FakePsycopg()
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    return fake


def test_a_remote_connection_verifies_its_certificate_whatever_its_url_says(psycopg: FakePsycopg) -> None:
    store.connect("postgresql+psycopg2://u:p@ep-x.us-east-1.aws.neon.tech/neondb?sslmode=disable")

    url, options = psycopg.calls[0]
    assert url == "postgresql://u:p@ep-x.us-east-1.aws.neon.tech/neondb?sslmode=disable"
    assert options["sslmode"] == "verify-full"


def test_the_drills_own_service_connects_without_a_certificate(psycopg: FakePsycopg) -> None:
    store.connect("postgresql://kdf_drill:kdf-drill-local@127.0.0.1:5432/kdf_drill")

    assert "sslmode" not in psycopg.calls[0][1]


@pytest.mark.parametrize(
    "url, direct",
    [
        ("postgresql://u:p@ep-x-pooler.us-east-1.aws.neon.tech/neondb", True),
        ("postgresql://u:p@127.0.0.1/drill?host=ep-x.us-east-1.aws.neon.tech", False),
        ("postgresql://u:p@127.0.0.1/drill?hostaddr=10.0.0.1", False),
        ("mysql://u:p@host/db", False),
    ],
)
def test_a_pooler_writer_a_host_in_the_query_or_another_scheme_is_refused(
    psycopg: FakePsycopg,
    url: str,
    direct: bool,
) -> None:
    with pytest.raises(store.StoreError):
        store.connect(url, direct = direct)

    assert psycopg.calls == []
