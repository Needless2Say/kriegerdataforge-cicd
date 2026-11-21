"""
The backup's and the restore's steps, each run by a step of `db-backup.yml` or `db-restore.yml` (the secrets moves,
step 2). Run from cicd's `scripts/` as `python -m kdf_backup.cli <command>`.

Each command reads its secret from its own step's environment alone, never an argument, and its files from one work
folder, `KDF_BACKUP_WORK`, so a step holds only what it needs and a child process inherits nothing more.

The backup, in order
    options     KDF_PRUNE, KDF_KEEP, KDF_CAPACITY, KDF_BOUND, KDF_LOCK_WAIT, checked before the dump
    precheck    BACKUP_STORE_WRITER_URL, the whole store and the next archive's bound against the capacity
    pack        KDF_APP, KDF_ENVIRONMENT, KDF_TOOL_DIR, the dump tool's folder into the archive's tar
    encrypt     KDF_RECIPIENT_FILE, the tar to the app's `age` recipient, the tar removed
    verify      BACKUP_AGE_IDENTITY, in a job of its own, the sealed archive decrypted and opened, the plaintext removed
    sign        BACKUP_HMAC_KEY and KDF_VERIFIED_SHA256, the row's metadata signed once its archive is the verified one
    store       BACKUP_STORE_WRITER_URL and BACKUP_HMAC_KEY, KDF_PREVIOUS_RECEIPT, stored, read back and pruned

The restore, in order
    plan        BACKUP_STORE_READER_URL and BACKUP_HMAC_KEY, KDF_APP, KDF_ENVIRONMENT, KDF_BACKUP_ID, the row
                checked and its server's major given as the step's output
    fetch       BACKUP_STORE_READER_URL, the row and its encrypted archive
    check       BACKUP_HMAC_KEY, the row's signature, the store's SHA256 and the file's
    decrypt     BACKUP_AGE_IDENTITY, the archive decrypted, the identity in a file of the owner's alone and removed
    open        the tar opened in its exact layout, its manifest bound to the row
    target      KDF_RESTORE_TARGET_URL and KDF_MODE, a drill held to the job's own service of the archive's major, and
                no archive from a newer pg_dump than the server
    counts      KDF_RESTORE_TARGET_URL, the restored tables and counts against the manifest's
"""

from __future__ import annotations

# standard imports
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# third party imports
from kdf_backup import archive, store

# ======================================================================================================================
# Configuration
# ======================================================================================================================

WORK_ENV:        str = "KDF_BACKUP_WORK"
RECIPIENT_SHAPE: re.Pattern[str] = re.compile(r"^age1[0-9a-z]{58}$")
IDENTITY_MARK:   str = "AGE-SECRET-KEY-1"
LOCAL_HOSTS:     frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})
MODES:           frozenset[str] = frozenset({"drill", "live"})

# the majors a drill has a service for on cicd's mirror, each a job of db-restore.yml
DRILL_MAJORS: frozenset[int] = frozenset({16, 17})

# every table outside the catalogs, as the apps' dump tools count them
TABLES:             str = (
    "SELECT schemaname, tablename FROM pg_catalog.pg_tables"
    " WHERE schemaname NOT IN ('pg_catalog', 'information_schema') AND left(schemaname, 3) <> 'pg_'"
    " ORDER BY schemaname, tablename"
)
SERVER_VERSION_NUM: str = "SELECT pg_catalog.current_setting('server_version_num')"


class CliError(Exception):
    """
    A step refused. Its message names no secret.
    """

# ======================================================================================================================
# Helpers
# ======================================================================================================================

def env(name: str) -> str:
    """
    A value from the step's environment.

    Args:
        name: its name

    Returns:
        str: its value

    Raises:
        CliError: it is unset or empty
    """
    value = os.environ.get(name, "")
    if not value:
        raise CliError(f"{name} is not set in this step's environment")
    return value


def work() -> Path:
    """
    The work folder, made if absent.

    Returns:
        Path: the folder
    """
    folder = Path(env(WORK_ENV))
    folder.mkdir(parents = True, exist_ok = True)
    return folder


def output(name: str, value: str) -> None:
    """
    A step output, when the step has an output file.

    Args:
        name: its name
        value: its value, one line
    """
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding = "utf-8") as handle:
            handle.write(f"{name}={value}\n")


def read_json(path: Path) -> Any:
    """
    A JSON file the run wrote.

    Args:
        path: the file

    Returns:
        Any: its value

    Raises:
        CliError: it is missing or not JSON
    """
    try:
        return json.loads(path.read_text(encoding = "utf-8"))
    except (OSError, json.JSONDecodeError) as unreadable:
        raise CliError(f"{path.name} is missing or not JSON, so an earlier step did not finish") from unreadable


def write_json(path: Path, value: Any) -> None:
    """
    Write a JSON file in its canonical form.

    Args:
        path: the file
        value: its value
    """
    path.write_bytes(archive.canonical(value))


def run_age(arguments: list[str]) -> None:
    """
    Run `age` with no environment but PATH, so it inherits no secret.

    Args:
        arguments: its arguments

    Raises:
        CliError: age is absent or failed
    """
    tool = shutil.which("age")
    if tool is None:
        raise CliError("age is not on PATH")
    done = subprocess.run(  # noqa: S603  # nosec B603
        [tool, *arguments],
        env = {"PATH": os.environ.get("PATH", "")},
        capture_output = True,
        check = False,
    )
    if done.returncode != 0:
        raise CliError(f"age failed with exit status {done.returncode}")


def quote_identifier(name: str) -> str:
    """
    A name from the catalog quoted as an identifier.

    Args:
        name: the name

    Returns:
        str: it quoted
    """
    return '"' + name.replace('"', '""') + '"'

# ======================================================================================================================
# The backup
# ======================================================================================================================

def options() -> None:
    """
    Check the run's store options before the dump, and keep them for the later steps.
    """
    read = store.read_options(
        prune = os.environ.get("KDF_PRUNE", ""),
        keep = os.environ.get("KDF_KEEP", ""),
        capacity = os.environ.get("KDF_CAPACITY", ""),
        bound = os.environ.get("KDF_BOUND", ""),
        lock_wait = os.environ.get("KDF_LOCK_WAIT", ""),
    )
    write_json(work() / "options.json", asdict(read))
    print(f"options checked, prune {read.prune}, keep {read.keep}, capacity {read.capacity}, bound {read.bound}")


def _options() -> store.Options:
    """
    The options the first step kept.

    Returns:
        store.Options: the options
    """
    return store.Options(**read_json(work() / "options.json"))


def precheck() -> None:
    """
    Refuse before the dump when the store is too full for the next archive's bound.
    """
    kept = _options()
    with closing(store.connect(env("BACKUP_STORE_WRITER_URL"), direct = True)) as connection:
        store.precheck(connection, capacity = kept.capacity, bound = kept.bound)


def pack() -> None:
    """
    Pack the dump tool's folder into the archive's tar, under a new backup_id.
    """
    manifest, dump = archive.read_tool_folder(Path(env("KDF_TOOL_DIR")))
    backup_id = str(uuid.uuid4())
    metadata  = archive.pack(
        manifest,
        dump,
        app = env("KDF_APP"),
        environment = env("KDF_ENVIRONMENT"),
        backup_id = backup_id,
        out = work() / "archive.tar",
    )
    write_json(work() / "metadata.json", metadata)
    output("backup_id", backup_id)
    print(f"packed {backup_id}, {len(manifest['tables'])} tables, server {manifest['server_version']}")


def encrypt() -> None:
    """
    Encrypt the tar to the app's committed `age` recipient, then remove the tar.

    Raises:
        CliError: the recipient file is not one `age` recipient
    """
    recipient = Path(env("KDF_RECIPIENT_FILE")).read_text(encoding = "utf-8").strip()
    if not RECIPIENT_SHAPE.match(recipient):
        raise CliError("the recipient file is not one age recipient, age1 and 58 characters")
    folder = work()
    plain, sealed = folder / "archive.tar", folder / "archive.age"
    run_age(["-r", recipient, "-o", str(sealed), str(plain)])
    plain.unlink()
    metadata = read_json(folder / "metadata.json")
    metadata.update(size_bytes = sealed.stat().st_size, archive_sha256 = archive.sha256_of(sealed))
    write_json(folder / "metadata.json", metadata)
    print(f"encrypted to {recipient}, {metadata['size_bytes']} bytes, the tar removed")


def _sealed_matches(folder: Path, metadata: dict[str, Any]) -> bool:
    """
    Whether the sealed archive in the work folder is the size and SHA256 its metadata names.

    Args:
        folder: the work folder
        metadata: its metadata

    Returns:
        bool: whether it is
    """
    sealed = folder / "archive.age"
    return (
        sealed.is_file()
        and sealed.stat().st_size == metadata.get("size_bytes")
        and archive.sha256_of(sealed) == metadata.get("archive_sha256")
    )


def verify() -> None:
    """
    Prove the sealed archive decrypts with the app's identity and opens in its exact layout, its manifest bound to its
    metadata and its dump a custom archive, then remove the plaintext and give the sealed archive's SHA256 as the
    step's output, which the store's signing step holds it to.

    Raises:
        CliError: the archive is not its metadata's, or does not decrypt
    """
    folder   = work()
    metadata = read_json(folder / "metadata.json")
    if not _sealed_matches(folder, metadata):
        raise CliError("the sealed archive is not the size and SHA256 its metadata names")
    try:
        _decrypt(folder)
        manifest, _dump = archive.open_archive(folder / "archive.tar", folder / "verify", expected = metadata)
    finally:
        shutil.rmtree(folder / "verify", ignore_errors = True)
        (folder / "archive.tar").unlink(missing_ok = True)
    output("sealed_sha256", metadata["archive_sha256"])
    print(f"{metadata['backup_id']} decrypts and opens, {len(manifest['tables'])} tables, the plaintext removed")


def sign() -> None:
    """
    Sign the row's metadata with the app's HMAC key, once the sealed archive the dump's job passed on is the one its
    metadata names, of this run's own app and environment, and the one the verify job decrypted and opened.

    Raises:
        CliError: the metadata names another scope, or the archive is not its size and SHA256 or not the verified one
    """
    folder   = work()
    key      = archive.read_key(env("BACKUP_HMAC_KEY"))
    metadata = read_json(folder / "metadata.json")
    if (metadata.get("app"), metadata.get("environment")) != (env("KDF_APP"), env("KDF_ENVIRONMENT")):
        raise CliError("the archive's metadata names another app or environment than this run")
    if not _sealed_matches(folder, metadata):
        raise CliError("the sealed archive is not the size and SHA256 its metadata names")
    if metadata.get("archive_sha256") != env("KDF_VERIFIED_SHA256"):
        raise CliError("the sealed archive is not the one the verify job decrypted and opened")
    (folder / "signature.txt").write_text(archive.sign(metadata, key), encoding = "ascii")
    print(f"signed the row's metadata of {metadata['backup_id']}")


def _previous_receipt() -> Any:
    """
    The last run's receipt, None when there is none, a value no scope matches when it is unreadable.

    Returns:
        Any: the receipt
    """
    path = Path(os.environ.get("KDF_PREVIOUS_RECEIPT", "") or "absent")
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding = "utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"format": "unreadable"}


def store_step() -> None:
    """
    Store the archive, read it back and prune, under the store's lock, and leave the run's receipt and issues.
    """
    kept     = _options()
    folder   = work()
    key      = archive.read_key(env("BACKUP_HMAC_KEY"))
    metadata = read_json(folder / "metadata.json")
    with closing(store.connect(env("BACKUP_STORE_WRITER_URL"), direct = True)) as connection:
        outcome = store.store_backup(
            connection,
            metadata = metadata,
            signature = (folder / "signature.txt").read_text(encoding = "ascii").strip(),
            archive_path = folder / "archive.age",
            key = key,
            keep = kept.keep,
            prune = kept.prune,
            previous = _previous_receipt(),
            capacity = kept.capacity,
            lock_wait = kept.lock_wait,
        )
    write_json(folder / "receipt.json", outcome.receipt)
    lines = [f"- {issue}" for issue in outcome.issues]
    (folder / "issues.md").write_text("\n".join(lines) + ("\n" if lines else ""), encoding = "utf-8")
    output("issues", "true" if outcome.issues else "false")
    for issue in outcome.issues:
        print(f"::warning::{issue}")

# ======================================================================================================================
# The restore
# ======================================================================================================================

def _row(connection: Any, key: bytes) -> store.Stored:
    """
    The chosen backup's row, checked.

    Args:
        connection: the reader's connection
        key: the HMAC key

    Returns:
        store.Stored: the row

    Raises:
        CliError: no such row in the scope, or one that fails a check
    """
    app, environment, backup_id = env("KDF_APP"), env("KDF_ENVIRONMENT"), env("KDF_BACKUP_ID")
    row = connection.execute(store.ROW, (app, environment, backup_id)).fetchone()
    if row is None:
        raise CliError(f"no backup {backup_id} of {app} in {environment}")
    stored = store.Stored.of(row)
    fault  = stored.fault(key)
    if fault or (stored.app, stored.environment, stored.backup_id) != (app, environment, backup_id):
        raise CliError(fault or "the row read is not the backup asked for")
    return stored


def plan() -> None:
    """
    Check the chosen row and give its server's major as the step's output, for the drill's service.

    Raises:
        CliError: the row's pg_dump and server majors differ, or a drill of a major no drill job serves
    """
    mode = env("KDF_MODE")
    key  = archive.read_key(env("BACKUP_HMAC_KEY"))
    with closing(store.connect(env("BACKUP_STORE_READER_URL"))) as connection:
        stored = _row(connection, key)
    major = archive.major_of(stored.server_version)
    if archive.major_of(stored.pg_dump_version) != major:
        raise CliError("the row's pg_dump and server majors differ")
    if mode == "drill" and major not in DRILL_MAJORS:
        raise CliError(
            f"no drill job serves Postgres {major}, so the drill would restore nothing, add its service first",
        )
    output("major", str(major))
    print(f"{stored.backup_id}, taken {stored.taken_at}, server major {major}, its signature checked")


def fetch() -> None:
    """
    Fetch the chosen row and its encrypted archive.

    Raises:
        CliError: no such backup in the scope
    """
    folder = work()
    app, environment, backup_id = env("KDF_APP"), env("KDF_ENVIRONMENT"), env("KDF_BACKUP_ID")
    with closing(store.connect(env("BACKUP_STORE_READER_URL"))) as connection:
        row  = connection.execute(store.ROW, (app, environment, backup_id)).fetchone()
        data = connection.execute(store.FETCH, (app, environment, backup_id)).fetchone()
    if row is None or data is None:
        raise CliError(f"no backup {backup_id} of {app} in {environment}")
    write_json(folder / "row.json", asdict(store.Stored.of(row)))
    (folder / "archive.age").write_bytes(bytes(data[0]))
    print(f"fetched {backup_id}, {len(data[0])} bytes")


def check() -> None:
    """
    Check the fetched row's signature, the store's SHA256 and the file's, and keep its metadata.

    Raises:
        CliError: any check fails
    """
    folder = work()
    stored = store.Stored(**read_json(folder / "row.json"))
    fault  = stored.fault(archive.read_key(env("BACKUP_HMAC_KEY")))
    if fault:
        raise CliError(fault)
    sealed = folder / "archive.age"
    if sealed.stat().st_size != stored.size_bytes or archive.sha256_of(sealed) != stored.archive_sha256:
        raise CliError("the fetched archive is not the size and SHA256 its row signed")
    write_json(folder / "metadata.json", stored.metadata())
    print(f"{stored.backup_id} checked, its signature, the store's SHA256 and the file's")


def _decrypt(folder: Path) -> None:
    """
    Decrypt the work folder's archive, the identity written to a file only the job's user reads and removed after.

    Args:
        folder: the work folder

    Raises:
        CliError: the identity is not an age identity, or age failed
    """
    identity = env("BACKUP_AGE_IDENTITY")
    if IDENTITY_MARK not in identity:
        raise CliError("BACKUP_AGE_IDENTITY is not an age identity")
    path   = folder / "identity.txt"
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(handle, "w", encoding = "ascii") as stream:
            stream.write(identity.strip() + "\n")
        run_age(["-d", "-i", str(path), "-o", str(folder / "archive.tar"), str(folder / "archive.age")])
    finally:
        path.unlink(missing_ok = True)


def decrypt() -> None:
    """
    Decrypt the archive for a restore, the identity's file removed either way.
    """
    _decrypt(work())
    print("decrypted, the identity's file removed")


def open_step() -> None:
    """
    Open the decrypted tar in its exact layout, its manifest bound to its row, and remove the tar.
    """
    folder = work()
    manifest, dump = archive.open_archive(
        folder / "archive.tar",
        folder / "restore",
        expected = read_json(folder / "metadata.json"),
    )
    (folder / "archive.tar").unlink()
    write_json(folder / "restore" / "manifest.json", manifest)
    output("dump", str(dump))
    print(f"opened {manifest['backup_id']}, {len(manifest['tables'])} tables, the tar removed")


def _manifest() -> dict[str, Any]:
    """
    The opened archive's manifest.

    Returns:
        dict[str, Any]: the manifest
    """
    return read_json(work() / "restore" / "manifest.json")


def target() -> None:
    """
    Check the restore's target before any tool runs.

    A drill is held to the job's own service on this runner, of the archive's own major. Any restore refuses an archive
    from a newer pg_dump than the target server, since an archive loads into a server of its own major or newer.

    Raises:
        CliError: a mode out of its shape, a drill pointed past the runner, or a server older than the archive
    """
    mode, url = env("KDF_MODE"), env("KDF_RESTORE_TARGET_URL")
    if mode not in MODES:
        raise CliError("KDF_MODE is neither drill nor live")
    if mode == "drill" and (urlsplit(url).hostname or "") not in LOCAL_HOSTS:
        raise CliError("a drill restores into the job's own service alone, never a live target")
    dumped = archive.major_of(_manifest()["pg_dump_version"])
    with closing(store.connect(url)) as connection:
        served = int(connection.execute(SERVER_VERSION_NUM).fetchone()[0]) // 10000
    if served < dumped:
        raise CliError(f"the archive is from pg_dump {dumped} and the server is of major {served}, an older major "
                       "PostgreSQL does not restore into")
    if mode == "drill" and served != dumped:
        raise CliError(f"the drill's service is of major {served}, not the archive's {dumped}")
    print(f"the {mode} target is of major {served}, the archive's {dumped}")


def counts() -> None:
    """
    Compare the restored tables and counts with the manifest's.

    Raises:
        CliError: any table's count differs, which a committed restore to investigate
    """
    expected = _manifest()["tables"]
    with closing(store.connect(env("KDF_RESTORE_TARGET_URL"))) as connection:
        restored = {}
        for schema, name in connection.execute(TABLES).fetchall():
            # the names come from the catalog, each quoted as an identifier
            table = f"{quote_identifier(schema)}.{quote_identifier(name)}"
            query = f"SELECT count(*) FROM {table}"  # noqa: S608  # nosec B608
            restored[f"{schema}.{name}"] = int(connection.execute(query).fetchone()[0])
    differences = archive.count_differences(expected, restored)
    for difference in differences:
        print(f"::error::{difference}")
    if differences:
        raise CliError("the restored counts differ from the manifest, a committed restore to investigate")
    print(f"the restored {len(restored)} tables and their counts are the manifest's")

# ======================================================================================================================
# Entry point
# ======================================================================================================================

def commands() -> dict[str, Any]:
    """
    Each command's name and its step.

    Returns:
        dict[str, Any]: the commands
    """
    return {
        "options": options,
        "precheck": precheck,
        "pack": pack,
        "encrypt": encrypt,
        "verify": verify,
        "sign": sign,
        "store": store_step,
        "plan": plan,
        "fetch": fetch,
        "check": check,
        "decrypt": decrypt,
        "open": open_step,
        "target": target,
        "counts": counts,
    }


def main(argv: list[str] | None = None) -> int:
    """
    Run one command.

    Args:
        argv: the command's name alone

    Returns:
        int: 0 when it passed, 1 when it refused, 2 for an unknown command
    """
    arguments = sys.argv[1:] if argv is None else argv
    known     = commands()
    if len(arguments) != 1 or arguments[0] not in known:
        print(f"usage: python -m kdf_backup.cli {{{','.join(known)}}}", file = sys.stderr)
        return 2
    try:
        known[arguments[0]]()
    except (CliError, archive.ArchiveError, store.StoreError) as refused:
        print(f"::error::{refused}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
