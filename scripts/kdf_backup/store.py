"""
The backup store, a Neon project of its own (the secrets moves, step 2, Round Table 110, the design's 5.17).

Each app and environment writes through its own role, which row security holds to its own rows, and a restrictive
policy lets a delete remove only a row the server inserted longer ago than its scope's floor. Here the job's side.

- The precheck, before the dump, refuses when the whole store's size and the next archive's bound would pass the
  capacity.
- The store step takes one session advisory lock every scope's job takes, waiting only so long. Under it, it compares
  the scope with the last run's receipt, checks the capacity again with the archive's actual size, inserts the row,
  reads it back and checks its signature and the store's own SHA256 of its archive, then prunes.
- The prune counts a row only when its signature checks over its own columns and the store's SHA256 of its archive is
  its digest. It ranks those by their signed `taken_at`, then `backup_id`, newest first, keeps the newest N and
  deletes the rest by name, printing them first. The floor keeps any younger, and a prune that removes none is no
  failure. A row that fails either check is kept, counted for nothing, and raises an issue.
- A missing or changed row since the last receipt, an unexplained one, or no receipt for a scope that holds rows,
  skips the prune and raises an issue, the backup standing. Each run leaves its own receipt for the next.

psycopg is imported only when a job connects, so the tests run against a fake connection.
"""

from __future__ import annotations

# standard imports
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

# third party imports
from kdf_backup import archive

# ======================================================================================================================
# The statements
# ======================================================================================================================

# one lock every scope's job takes, since the capacity is the whole store's
LOCK_KEY: int = int.from_bytes(b"kdfbkup1", "big") & 0x7FFFFFFFFFFFFFFF

SET_LOCK_WAIT: str = "SELECT pg_catalog.set_config('lock_timeout', %s, false)"
LOCK:          str = "SELECT pg_catalog.pg_advisory_lock(%s)"
UNLOCK:        str = "SELECT pg_catalog.pg_advisory_unlock(%s)"
SIZE:          str = "SELECT pg_catalog.pg_database_size(pg_catalog.current_database())"
ROWS:          str = (
    "SELECT backup_id::text, app, environment, taken_at, pg_dump_version, server_version, size_bytes, archive_sha256,"
    " signature, pg_catalog.encode(pg_catalog.sha256(archive), 'hex'), inserted_at"
    " FROM kdf_backup.backup WHERE app = %s AND environment = %s ORDER BY taken_at DESC, backup_id DESC"
)
INSERT:        str = (
    "INSERT INTO kdf_backup.backup (backup_id, app, environment, taken_at, pg_dump_version, server_version,"
    " size_bytes, archive_sha256, signature, archive)"
    " VALUES (%s::uuid, %s, %s, %s::timestamptz, %s, %s, %s, %s, %s, %s)"
)
PRUNE:         str = (
    "DELETE FROM kdf_backup.backup WHERE app = %s AND environment = %s AND backup_id = ANY(%s::uuid[])"
    " RETURNING backup_id::text"
)

# psycopg's LockNotAvailable, a lock wait that ran out
LOCK_TIMEOUT_STATE: str = "55P03"

# the receipt's format
RECEIPT_FORMAT: str = "kdf-backup-receipt-1"

# the longest an option may set a lock's wait, an hour
LOCK_WAIT_MOST: int = 3600


class StoreError(Exception):
    """
    A store step refused or failed. Its message names a host at most, never a password.
    """

# ======================================================================================================================
# The options
# ======================================================================================================================

@dataclass(frozen = True)
class Options:
    """
    A run's store options, read before the dump.

    Attributes:
        prune: whether the run prunes
        keep: N, the newest valid rows of the scope a prune keeps, None when pruning is off and N unset
        capacity: the store's capacity in bytes
        bound: the bound on the next archive's size, for the precheck
        lock_wait: how many seconds the store step waits for the lock
    """
    prune:     bool
    keep:      int | None
    capacity:  int
    bound:     int
    lock_wait: int


def _positive(name: str, text: str, most: int | None = None) -> int:
    """
    A positive whole number from an option's text.

    Args:
        name: the option's name
        text: its text
        most: its greatest value, if any

    Returns:
        int: the number

    Raises:
        StoreError: the text is not a positive whole number within its bound
    """
    stripped = text.strip() if isinstance(text, str) else ""
    if not stripped.isdigit() or int(stripped) < 1 or (most is not None and int(stripped) > most):
        bounded = f" of at most {most}" if most is not None else ""
        raise StoreError(f"{name} is not a positive whole number{bounded}")
    return int(stripped)


def read_options(*, prune: str, keep: str, capacity: str, bound: str, lock_wait: str) -> Options:
    """
    Read and check a run's store options, so a missing or malformed N fails before the dump.

    Args:
        prune: `true` or `false`
        keep: N, required when pruning is on
        capacity: the store's capacity in bytes
        bound: the next archive's bound in bytes
        lock_wait: the lock's wait in seconds

    Returns:
        Options: the options

    Raises:
        StoreError: an option out of its shape, or pruning on with no valid N
    """
    if prune not in ("true", "false"):
        raise StoreError("prune is neither true nor false")
    pruning = prune == "true"
    if pruning or (isinstance(keep, str) and keep.strip()):
        kept: int | None = _positive("keep", keep)
    else:
        kept = None
    return Options(
        prune = pruning,
        keep = kept,
        capacity = _positive("capacity", capacity),
        bound = _positive("bound", bound),
        lock_wait = _positive("lock_wait", lock_wait, LOCK_WAIT_MOST),
    )

# ======================================================================================================================
# A stored row
# ======================================================================================================================

def _utc(moment: datetime, precise: bool) -> str:
    """
    A moment in UTC as text, to the second for a signed time, to the microsecond for an insert time.

    A signed time with any fraction is written whole, so its signature, made over seconds alone, fails.

    Args:
        moment: the moment
        precise: whether to write microseconds

    Returns:
        str: its text
    """
    moment = moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo = UTC)
    if precise:
        return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return moment.isoformat() if moment.microsecond else moment.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen = True)
class Stored:
    """
    A row of the store as the job reads it, every column but its archive, and the store's own SHA256 of it.
    """
    backup_id:       str
    app:             str
    environment:     str
    taken_at:        str
    pg_dump_version: str
    server_version:  str
    size_bytes:      int
    archive_sha256:  str
    signature:       str
    store_sha256:    str
    inserted_at:     str


    @classmethod
    def of(cls, row: tuple) -> Stored:
        """
        A stored row from the columns ROWS selects.

        Args:
            row: the columns

        Returns:
            Stored: the row
        """
        (backup_id, app, environment, taken, dumped, served, size, digest, signature, store_digest, inserted) = row
        return cls(
            backup_id = str(backup_id),
            app = app,
            environment = environment,
            taken_at = _utc(taken, precise = False),
            pg_dump_version = dumped,
            server_version = served,
            size_bytes = size,
            archive_sha256 = digest,
            signature = signature,
            store_sha256 = store_digest,
            inserted_at = _utc(inserted, precise = True),
        )


    def metadata(self) -> dict[str, Any]:
        """
        The row's signed columns.

        Returns:
            dict[str, Any]: the metadata
        """
        return {name: getattr(self, name) for name in archive.SIGNED_FIELDS}


    def fault(self, key: bytes) -> str | None:
        """
        Why the row counts for nothing, or None when its signature checks and its archive is its digest.

        Args:
            key: the HMAC key

        Returns:
            str | None: the fault
        """
        if not archive.verify(self.metadata(), self.signature, key):
            return f"{self.backup_id} fails its signature, kept and counted for nothing"
        if self.store_sha256 != self.archive_sha256:
            return f"{self.backup_id}'s archive no longer matches its digest, kept and counted for nothing"
        return None

# ======================================================================================================================
# The receipt
# ======================================================================================================================

def receipt(app: str, environment: str, rows: list[Stored], pruned: list[str], invalid: list[str]) -> dict[str, Any]:
    """
    The receipt a run leaves, the scope's rows after its prune, the names it pruned and those it could not count.

    Args:
        app: the scope's app
        environment: its environment
        rows: its rows after the prune
        pruned: the names the prune deleted
        invalid: the names that failed a check

    Returns:
        dict[str, Any]: the receipt
    """
    return {
        "format": RECEIPT_FORMAT,
        "app": app,
        "environment": environment,
        "rows": [
            {
                "backup_id": row.backup_id,
                "inserted_at": row.inserted_at,
                "archive_sha256": row.archive_sha256,
                "verified": row.backup_id not in invalid,
            }
            for row in rows
        ],
        "pruned": list(pruned),
    }


def receipt_faults(previous: Any, app: str, environment: str, rows: list[Stored]) -> list[str]:
    """
    How the scope's rows differ from the last receipt, before this run's insert.

    Args:
        previous: the last run's receipt, or None
        app: the scope's app
        environment: its environment
        rows: its rows now

    Returns:
        list[str]: each difference, empty when they match
    """
    if previous is None:
        return ["no receipt for a scope that holds rows"] if rows else []
    if (
        not isinstance(previous, dict)
        or previous.get("format") != RECEIPT_FORMAT
        or (previous.get("app"), previous.get("environment")) != (app, environment)
        or not isinstance(previous.get("rows"), list)
    ):
        return ["the last receipt is not this scope's, so no receipt counts"]
    then   = {
        entry.get("backup_id"): (entry.get("inserted_at"), entry.get("archive_sha256"))
        for entry in previous["rows"]
        if isinstance(entry, dict)
    }
    now    = {row.backup_id: (row.inserted_at, row.archive_sha256) for row in rows}
    faults = [f"{name} is missing since the last receipt" for name in sorted(set(then) - set(now), key = str)]
    faults += [
        f"{name} changed since the last receipt" for name in sorted(set(then) & set(now)) if then[name] != now[name]
    ]
    faults += [f"{name} is unexplained by the last receipt" for name in sorted(set(now) - set(then))]
    return faults

# ======================================================================================================================
# The steps
# ======================================================================================================================

def precheck(connection: Any, *, capacity: int, bound: int) -> int:
    """
    Before the dump, refuse when the whole store and the next archive's bound would pass the capacity.

    Args:
        connection: the writer's connection
        capacity: the store's capacity in bytes
        bound: the next archive's bound in bytes

    Returns:
        int: the store's size in bytes

    Raises:
        StoreError: the bound would pass the capacity
    """
    size = int(connection.execute(SIZE).fetchone()[0])
    if size + bound > capacity:
        raise StoreError(f"the store holds {size} bytes, so the next archive's bound {bound} passes the capacity "
                         f"{capacity}, and the run stops before its dump")
    print(f"the store holds {size} bytes, the next archive's bound {bound} within the capacity {capacity}")
    return size


@dataclass
class Outcome:
    """
    What a store step did.

    Attributes:
        receipt: the receipt it leaves
        pruned: the names it deleted
        kept_by_floor: the names it meant to delete that the floor kept
        issues: what an issue reports, empty when nothing does
    """
    receipt:       dict[str, Any]
    pruned:        list[str] = field(default_factory = list)
    kept_by_floor: list[str] = field(default_factory = list)
    issues:        list[str] = field(default_factory = list)


def _scope_rows(connection: Any, app: str, environment: str) -> list[Stored]:
    """
    The scope's rows, newest first.

    Args:
        connection: the connection
        app: the scope's app
        environment: its environment

    Returns:
        list[Stored]: the rows
    """
    return [Stored.of(row) for row in connection.execute(ROWS, (app, environment)).fetchall()]


def _check_new(metadata: dict[str, Any], signature: str, archive_path: Path, key: bytes) -> bytes:
    """
    Check the new archive against its metadata and signature before it goes near the store.

    Args:
        metadata: its signed metadata
        signature: its signature
        archive_path: its encrypted file
        key: the HMAC key

    Returns:
        bytes: its bytes

    Raises:
        StoreError: the signature fails, or the file is not the size and SHA256 it signed
    """
    if not archive.verify(metadata, signature, key):
        raise StoreError("the new archive's signature does not check over its metadata, nothing is stored")
    data = archive_path.read_bytes()
    if len(data) != metadata["size_bytes"] or hashlib.sha256(data).hexdigest() != metadata["archive_sha256"]:
        raise StoreError("the new archive is not the size and SHA256 its metadata signed, nothing is stored")
    return data


def _lock(connection: Any, lock_wait: int) -> None:
    """
    Take the store's lock, waiting at most *lock_wait* seconds.

    Args:
        connection: the connection
        lock_wait: the wait in seconds

    Raises:
        StoreError: the wait ran out, so another job holds the lock
    """
    connection.execute(SET_LOCK_WAIT, (f"{lock_wait}s",))
    try:
        connection.execute(LOCK, (LOCK_KEY,))
    except Exception as refused:
        if getattr(refused, "sqlstate", None) == LOCK_TIMEOUT_STATE:
            raise StoreError(f"the store's lock was held past {lock_wait} seconds, so nothing is stored") from None
        raise


def _unlock(connection: Any) -> None:
    """
    Release the store's lock, the session's end releasing it anyway.

    Args:
        connection: the connection
    """
    try:
        connection.execute(UNLOCK, (LOCK_KEY,))
    except Exception:
        print("::warning::the store's lock could not be released, and the session's end releases it")


def store_backup(
    connection: Any,
    *,
    metadata: dict[str, Any],
    signature: str,
    archive_path: Path,
    key: bytes,
    keep: int | None,
    prune: bool,
    previous: Any,
    capacity: int,
    lock_wait: int,
) -> Outcome:
    """
    Store the new archive and prune its scope, all under the store's one lock.

    Args:
        connection: the writer's connection
        metadata: the new archive's signed metadata
        signature: its signature
        archive_path: its encrypted file
        key: the HMAC key
        keep: N, the newest valid rows a prune keeps
        prune: whether the run prunes
        previous: the last run's receipt for the scope, or None
        capacity: the store's capacity in bytes
        lock_wait: the lock's wait in seconds

    Returns:
        Outcome: what it did

    Raises:
        StoreError: the archive does not check, the lock was held too long, the capacity would pass, the insert failed
            or its readback did not check. Nothing is pruned after any of them
    """
    if prune and (not isinstance(keep, int) or keep < 1):
        raise StoreError("pruning is on with no N")
    data = _check_new(metadata, signature, archive_path, key)
    app, environment, backup_id = metadata["app"], metadata["environment"], metadata["backup_id"]
    _lock(connection, lock_wait)
    try:
        drift  = receipt_faults(previous, app, environment, _scope_rows(connection, app, environment))
        issues = list(drift)
        size   = int(connection.execute(SIZE).fetchone()[0])
        if size + len(data) > capacity:
            raise StoreError(f"the store holds {size} bytes, so this archive's {len(data)} would pass the capacity "
                             f"{capacity}, and nothing is inserted")
        try:
            connection.execute(INSERT, (
                backup_id,
                app,
                environment,
                metadata["taken_at"],
                metadata["pg_dump_version"],
                metadata["server_version"],
                metadata["size_bytes"],
                metadata["archive_sha256"],
                signature,
                data,
            ))
        except Exception as failed:
            raise StoreError(
                f"the insert of {backup_id} failed, {type(failed).__name__}, so nothing is pruned",
            ) from None
        rows = _scope_rows(connection, app, environment)
        new  = next((row for row in rows if row.backup_id == backup_id), None)
        if new is None or new.metadata() != metadata or new.signature != signature or new.fault(key):
            raise StoreError(f"the readback of {backup_id} does not check, so nothing is pruned")
        print(f"stored and read back {backup_id}, {len(data)} bytes, its signature and its digest checked")

        faults  = {row.backup_id: row.fault(key) for row in rows}
        invalid = [name for name, fault in faults.items() if fault]
        issues += [faults[name] for name in invalid]
        pruned:        list[str] = []
        kept_by_floor: list[str] = []
        if not prune:
            print("pruning is off, so nothing is pruned")
        elif drift:
            issues.append("the prune is skipped, since the store does not match the last receipt, the backup stands")
        else:
            ranked = sorted(
                (row for row in rows if row.backup_id not in invalid),
                key = lambda row: (row.taken_at, row.backup_id),
                reverse = True,
            )
            meant  = [row.backup_id for row in ranked[keep:]]
            if meant:
                print(f"the prune keeps the newest {keep} and means to delete {', '.join(meant)}")
                gone          = {row[0] for row in connection.execute(PRUNE, (app, environment, meant)).fetchall()}
                pruned        = [name for name in meant if name in gone]
                kept_by_floor = [name for name in meant if name not in gone]
                print(f"pruned {', '.join(pruned) or 'none'}, the floor kept {', '.join(kept_by_floor) or 'none'}")
            else:
                print(f"the scope holds no more than {keep} valid rows, so nothing is pruned")
        remaining = [row for row in rows if row.backup_id not in pruned]
        return Outcome(
            receipt = receipt(app, environment, remaining, pruned, invalid),
            pruned = pruned,
            kept_by_floor = kept_by_floor,
            issues = issues,
        )
    finally:
        _unlock(connection)

# ======================================================================================================================
# The connection
# ======================================================================================================================

def masked(text: str, url: str) -> str:
    """
    A message with the password a URL carries masked wherever it appears.

    Args:
        text: the message
        url: the URL

    Returns:
        str: the message masked
    """
    try:
        password = urlsplit(url).password
    except ValueError:
        password = None
    for value in filter(None, {password, unquote(password) if password else None}):
        text = text.replace(value, "***")
    return text


def connect(url: str) -> Any:
    """
    Connect to the store or a database by a URL from the job's environment, never an argument.

    Args:
        url: the URL

    Returns:
        Any: the connection, in autocommit

    Raises:
        StoreError: the connection failed, named by its host with any password masked
    """
    import psycopg  # noqa: PLC0415  # the backup and restore jobs alone install it

    try:
        return psycopg.connect(url, autocommit = True, connect_timeout = 30, application_name = "kdf-backup")
    except psycopg.Error as failed:
        host = urlsplit(url).hostname or "the database"
        raise StoreError(f"could not connect to {host}, {masked(str(failed).strip(), url)}") from None
