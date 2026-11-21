"""
A backup archive's contract (the secrets moves, step 2).

The app's own dump tool writes a folder of two files, its dump and a `manifest.json` that names it, the snapshot's
time, the server's and the dump tool's versions, the Alembic revision and each table's count from the snapshot the dump
imports. cicd checks both, adds the backup's identity, and packs them into a tar whose bytes depend on its contents
alone, the manifest first. The tar is then encrypted to the app's `age` recipient, and the row's plain columns, the
encrypted archive's SHA256 among them, are signed with the app's HMAC key, so no field and no archive changes unseen.
A restore opens a tar only in that exact layout, and refuses one whose manifest names another backup than its row.

The dump's major must be the server's own, since an archive loads into a server of its own major or newer, never back.
"""

from __future__ import annotations

# standard imports
import hashlib
import hmac
import io
import json
import re
import tarfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# ======================================================================================================================
# The contract
# ======================================================================================================================

# the archive's format, written into its manifest
FORMAT: str = "kdf-backup-1"

# each member of the tar, in order
MANIFEST_NAME: str = "manifest.json"
DUMP_NAME:     str = "dump.pgdump"

# the row's plain columns the HMAC signs, in the store's own names
SIGNED_FIELDS: tuple[str, ...] = (
    "backup_id",
    "app",
    "environment",
    "taken_at",
    "pg_dump_version",
    "server_version",
    "size_bytes",
    "archive_sha256",
)

# the fields of the manifest cicd adds, which a tool's own manifest may not name
IDENTITY_FIELDS: tuple[str, ...] = ("kdf_backup_format", "backup_id", "app", "environment")

# the fields an archive's manifest must hold equal to its row, for a restore
BOUND_FIELDS: tuple[str, ...] = ("backup_id", "app", "environment", "taken_at", "server_version", "pg_dump_version")

# the HMAC's message starts with this, so a signature made for anything else never checks here
DOMAIN: bytes = b"kdf-backup-metadata-1\n"

ENVIRONMENTS:    frozenset[str] = frozenset({"dev", "prod"})
APP_SHAPE:       re.Pattern[str] = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
TIME_SHAPE:      re.Pattern[str] = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_SHAPE:    re.Pattern[str] = re.compile(r"^[0-9a-f]{64}$")
KEY_SHAPE:       re.Pattern[str] = re.compile(r"^[0-9a-fA-F]{64}$")
FILE_SHAPE:      re.Pattern[str] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAJOR_PATTERN:   re.Pattern[str] = re.compile(r"(?<![\d.])(\d{1,3})(?:\.\d+|beta\d*|rc\d*|devel)")
VERSION_MAXIMUM: int = 256
MANIFEST_BYTES:  int = 1 << 20
CHUNK:           int = 1 << 20

# the first bytes of every pg_dump custom format archive
DUMP_MAGIC: bytes = b"PGDMP"


class ArchiveError(Exception):
    """
    An archive, a manifest, a key or a signature out of its contract. Its message never holds a key.
    """


def canonical(value: Any) -> bytes:
    """
    The one byte form of a JSON value, its keys sorted, no spaces and ASCII alone.

    Args:
        value: the value

    Returns:
        bytes: its canonical form
    """
    return json.dumps(value, sort_keys = True, separators = (",", ":"), ensure_ascii = True).encode("ascii")


def sha256_of(path: Path) -> str:
    """
    The SHA256 of a file, read in chunks.

    Args:
        path: the file

    Returns:
        str: its hexadecimal digest
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def major_of(version: str) -> int:
    """
    The major number in a server's `server_version` or a client tool's `--version` line.

    Args:
        version: `17.12 (4d8000a)`, `pg_dump (PostgreSQL) 16.4`, `18beta1`

    Returns:
        int: the major

    Raises:
        ArchiveError: the text names no version
    """
    match = MAJOR_PATTERN.search(version) if isinstance(version, str) else None
    if not match:
        raise ArchiveError(f"no PostgreSQL version in {version!r}")
    return int(match.group(1))

# ======================================================================================================================
# Shapes
# ======================================================================================================================

def _is_count(value: Any) -> bool:
    """
    Whether a value is a row count, an integer of zero or more and never a boolean.

    Args:
        value: the value

    Returns:
        bool: whether it is one
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_version(value: Any) -> bool:
    """
    Whether a value is a version's text, printable, not empty and bounded.

    Args:
        value: the value

    Returns:
        bool: whether it is one
    """
    return isinstance(value, str) and 0 < len(value) <= VERSION_MAXIMUM and value.isprintable()


def _is_time(value: Any) -> bool:
    """
    Whether a value is a time in UTC to the second, `2026-11-20T06:00:00Z`.

    Args:
        value: the value

    Returns:
        bool: whether it is one
    """
    if not isinstance(value, str) or not TIME_SHAPE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _is_backup_id(value: Any) -> bool:
    """
    Whether a value is a UUID in its canonical lower case form.

    Args:
        value: the value

    Returns:
        bool: whether it is one
    """
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def identity_faults(app: Any, environment: Any, backup_id: Any) -> list[str]:
    """
    Where a backup's identity leaves its shape.

    Args:
        app: the app's short name, lower case
        environment: `dev` or `prod`
        backup_id: a UUID in its canonical form

    Returns:
        list[str]: each fault
    """
    faults = []
    if not isinstance(app, str) or not APP_SHAPE.match(app):
        faults.append("the app is not a short lower case name")
    if environment not in ENVIRONMENTS:
        faults.append("the environment is neither dev nor prod")
    if not _is_backup_id(backup_id):
        faults.append("the backup_id is not a UUID in its canonical lower case form")
    return faults


def metadata_faults(metadata: Any) -> list[str]:
    """
    Where a row's signed metadata leaves its shape, its fields exactly the signed columns.

    Args:
        metadata: the metadata

    Returns:
        list[str]: each fault
    """
    if not isinstance(metadata, dict) or set(metadata) != set(SIGNED_FIELDS):
        return [f"the metadata's fields are not exactly {', '.join(SIGNED_FIELDS)}"]
    faults = identity_faults(metadata["app"], metadata["environment"], metadata["backup_id"])
    if not _is_time(metadata["taken_at"]):
        faults.append("taken_at is not a time in UTC to the second")
    for name in ("pg_dump_version", "server_version"):
        if not _is_version(metadata[name]):
            faults.append(f"{name} is not a version's text")
    size = metadata["size_bytes"]
    if not _is_count(size) or size == 0:
        faults.append("size_bytes is not a positive integer")
    if not isinstance(metadata["archive_sha256"], str) or not SHA256_SHAPE.match(metadata["archive_sha256"]):
        faults.append("archive_sha256 is not 64 lower case hexadecimal digits")
    return faults


def manifest_faults(manifest: Any) -> list[str]:
    """
    Where a dump tool's manifest leaves its contract.

    Args:
        manifest: the manifest

    Returns:
        list[str]: each fault
    """
    if not isinstance(manifest, dict):
        return ["the manifest is not an object"]
    faults = [f"the manifest names {name}, which cicd adds" for name in IDENTITY_FIELDS if name in manifest]
    if not _is_time(manifest.get("taken_at")):
        faults.append("taken_at is not a time in UTC to the second")
    for name in ("server_version", "pg_dump_version"):
        if not _is_version(manifest.get(name)):
            faults.append(f"{name} is not a version's text")
    if "alembic_revision" not in manifest or not isinstance(manifest["alembic_revision"], (str, type(None))):
        faults.append("alembic_revision is neither a revision nor null")
    tables = manifest.get("tables")
    if not isinstance(tables, dict) or not all(isinstance(name, str) and _is_count(n) for name, n in tables.items()):
        faults.append("tables is not an object of each table's row count")
    dump = manifest.get("dump")
    if (
        not isinstance(dump, dict)
        or not isinstance(dump.get("file"), str)
        or not FILE_SHAPE.match(dump["file"])
        or ".." in dump["file"]
        or not _is_count(dump.get("bytes"))
        or dump["bytes"] < len(DUMP_MAGIC)
        or not isinstance(dump.get("sha256"), str)
        or not SHA256_SHAPE.match(dump["sha256"])
    ):
        faults.append(
            "dump is not the file's plain name, its bytes, at least a custom archive's header, and its SHA256",
        )
    if not faults:
        try:
            dumped, served = major_of(manifest["pg_dump_version"]), major_of(manifest["server_version"])
        except ArchiveError as refused:
            faults.append(str(refused))
        else:
            if dumped != served:
                faults.append(f"pg_dump {dumped} dumped a server of major {served}, not its own")
    return faults

# ======================================================================================================================
# The tool's folder and the pack
# ======================================================================================================================

def read_tool_folder(folder: Path) -> tuple[dict[str, Any], Path]:
    """
    Read and check the folder an app's dump tool wrote.

    Args:
        folder: the folder

    Returns:
        tuple[dict[str, Any], Path]: the tool's manifest and its dump

    Raises:
        ArchiveError: no manifest, a manifest out of its contract, or a dump whose size or SHA256 is not the
            manifest's
    """
    path = folder / MANIFEST_NAME
    if not path.is_file() or path.stat().st_size > MANIFEST_BYTES:
        raise ArchiveError(f"the dump tool wrote no {MANIFEST_NAME} of at most {MANIFEST_BYTES} bytes")
    try:
        manifest = json.loads(path.read_text(encoding = "utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as unreadable:
        raise ArchiveError(f"the dump tool's {MANIFEST_NAME} is not JSON") from unreadable
    faults = manifest_faults(manifest)
    if faults:
        raise ArchiveError("the dump tool's manifest is refused, " + ", ".join(faults))
    dump = folder / manifest["dump"]["file"]
    if not dump.is_file() or dump.is_symlink():
        raise ArchiveError("the dump tool's manifest names a dump the folder does not hold")
    if dump.stat().st_size != manifest["dump"]["bytes"] or sha256_of(dump) != manifest["dump"]["sha256"]:
        raise ArchiveError("the dump's size or SHA256 is not its manifest's")
    if not is_custom_archive(dump):
        raise ArchiveError("the dump is not a pg_dump custom archive, its header is not PGDMP")
    return manifest, dump


def is_custom_archive(path: Path) -> bool:
    """
    Whether a file starts as pg_dump's custom format does.

    Args:
        path: the file

    Returns:
        bool: whether its first bytes are PGDMP
    """
    with path.open("rb") as handle:
        return handle.read(len(DUMP_MAGIC)) == DUMP_MAGIC


def _member(name: str, size: int) -> tarfile.TarInfo:
    """
    A tar member whose header depends on its name and size alone.

    Args:
        name: the member's name
        size: its size

    Returns:
        tarfile.TarInfo: its header
    """
    info = tarfile.TarInfo(name)
    info.size, info.mtime, info.mode = size, 0, 0o644
    info.uid, info.gid, info.uname, info.gname = 0, 0, "", ""
    return info


def pack(
    manifest: dict[str, Any],
    dump: Path,
    *,
    app: str,
    environment: str,
    backup_id: str,
    out: Path,
) -> dict[str, Any]:
    """
    Pack a checked tool folder into the archive's tar, its manifest holding the backup's identity.

    Args:
        manifest: the tool's checked manifest
        dump: its checked dump
        app: the app's short name
        environment: `dev` or `prod`
        backup_id: the backup's UUID
        out: where the tar is written

    Returns:
        dict[str, Any]: the row's metadata the tar fixes, all but its size and its SHA256 once encrypted

    Raises:
        ArchiveError: an identity out of its shape, or a manifest out of its contract
    """
    faults = identity_faults(app, environment, backup_id) + manifest_faults(manifest)
    if faults:
        raise ArchiveError("the pack is refused, " + ", ".join(faults))
    inner = {
        **manifest,
        "kdf_backup_format": FORMAT,
        "backup_id": backup_id,
        "app": app,
        "environment": environment,
        "dump": {**manifest["dump"], "file": DUMP_NAME},
    }
    data  = canonical(inner)
    if len(data) > MANIFEST_BYTES:
        raise ArchiveError(f"the packed {MANIFEST_NAME} is over {MANIFEST_BYTES} bytes, which no restore opens")
    with tarfile.open(out, mode = "w", format = tarfile.USTAR_FORMAT) as tar:
        tar.addfile(_member(MANIFEST_NAME, len(data)), io.BytesIO(data))
        with dump.open("rb") as handle:
            tar.addfile(_member(DUMP_NAME, dump.stat().st_size), handle)
    return {
        "backup_id": backup_id,
        "app": app,
        "environment": environment,
        "taken_at": manifest["taken_at"],
        "pg_dump_version": manifest["pg_dump_version"],
        "server_version": manifest["server_version"],
    }

# ======================================================================================================================
# The signature
# ======================================================================================================================

def read_key(text: str) -> bytes:
    """
    The HMAC key from its 64 hexadecimal digits, its surrounding space ignored.

    Args:
        text: the key's text

    Returns:
        bytes: the key's 32 bytes

    Raises:
        ArchiveError: the text is not 64 hexadecimal digits, named without the text
    """
    stripped = text.strip() if isinstance(text, str) else ""
    if not KEY_SHAPE.match(stripped):
        raise ArchiveError("the HMAC key is not 64 hexadecimal digits")
    return bytes.fromhex(stripped)


def _message(metadata: dict[str, Any]) -> bytes:
    """
    What the HMAC signs, the domain and the canonical metadata.

    Args:
        metadata: the checked metadata

    Returns:
        bytes: the message
    """
    return DOMAIN + canonical({name: metadata[name] for name in SIGNED_FIELDS})


def sign(metadata: dict[str, Any], key: bytes) -> str:
    """
    Sign a row's metadata.

    Args:
        metadata: the row's plain columns, exactly the signed fields
        key: the HMAC key

    Returns:
        str: the signature, 64 hexadecimal digits

    Raises:
        ArchiveError: the metadata is out of its shape
    """
    faults = metadata_faults(metadata)
    if faults:
        raise ArchiveError("the metadata is refused, " + ", ".join(faults))
    return hmac.new(key, _message(metadata), hashlib.sha256).hexdigest()


def verify(metadata: Any, signature: Any, key: bytes) -> bool:
    """
    Whether a signature checks over a row's metadata. Anything out of its shape never checks.

    Args:
        metadata: the row's plain columns
        signature: the row's signature
        key: the HMAC key

    Returns:
        bool: whether it checks
    """
    if metadata_faults(metadata) or not isinstance(signature, str) or not SHA256_SHAPE.match(signature):
        return False
    return hmac.compare_digest(hmac.new(key, _message(metadata), hashlib.sha256).hexdigest(), signature)

# ======================================================================================================================
# The open, for a restore
# ======================================================================================================================

def open_archive(tar_path: Path, out_dir: Path, *, expected: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    """
    Open a decrypted archive in its exact layout, its manifest bound to its row, and write its dump.

    Nothing is written until the layout and the manifest are checked, and a dump whose bytes are not the manifest's is
    removed before the refusal.

    Args:
        tar_path: the decrypted tar
        out_dir: where the dump is written
        expected: the row's checked metadata

    Returns:
        tuple[dict[str, Any], Path]: the archive's manifest and its dump

    Raises:
        ArchiveError: a tar out of its layout, a manifest that names another backup or another format, or a dump whose
            size or SHA256 is not the manifest's
    """
    try:
        tar = tarfile.open(tar_path, mode = "r:")
    except tarfile.TarError as unreadable:
        raise ArchiveError("the archive is not a tar") from unreadable
    with tar:
        members = tar.getmembers()
        if [member.name for member in members] != [MANIFEST_NAME, DUMP_NAME] or not all(
            member.type == tarfile.REGTYPE and not member.issparse() for member in members
        ):
            raise ArchiveError(f"the archive is not exactly {MANIFEST_NAME} then {DUMP_NAME}, each a plain file")
        head, body = members
        if head.size > MANIFEST_BYTES:
            raise ArchiveError(f"the archive's {MANIFEST_NAME} is over {MANIFEST_BYTES} bytes")
        try:
            manifest = json.loads(tar.extractfile(head).read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as unreadable:
            raise ArchiveError(f"the archive's {MANIFEST_NAME} is not JSON") from unreadable
        if not isinstance(manifest, dict) or manifest.get("kdf_backup_format") != FORMAT:
            raise ArchiveError(f"the archive's manifest is not of the format {FORMAT}")
        for name in BOUND_FIELDS:
            if manifest.get(name) != expected.get(name):
                raise ArchiveError(f"the archive's manifest names another {name} than its row")
        faults = manifest_faults({name: value for name, value in manifest.items() if name not in IDENTITY_FIELDS})
        if faults:
            raise ArchiveError("the archive's manifest is refused, " + ", ".join(faults))
        dump_entry = manifest["dump"]
        if dump_entry["file"] != DUMP_NAME or dump_entry["bytes"] != body.size:
            raise ArchiveError("the archive's dump is not the file and the size its manifest names")
        out_dir.mkdir(parents = True, exist_ok = True)
        dump   = out_dir / DUMP_NAME
        digest = hashlib.sha256()
        with tar.extractfile(body) as source, dump.open("wb") as target:
            for chunk in iter(lambda: source.read(CHUNK), b""):
                digest.update(chunk)
                target.write(chunk)
    if digest.hexdigest() != dump_entry["sha256"] or not is_custom_archive(dump):
        dump.unlink()
        raise ArchiveError("the archive's dump is not the SHA256 its manifest names, or not a custom archive")
    return manifest, dump

# ======================================================================================================================
# The counts, after a restore
# ======================================================================================================================

def count_differences(expected: dict[str, int], restored: dict[str, int]) -> list[str]:
    """
    Each table whose restored count is not the manifest's, missing or not in it, in the tables' order.

    Args:
        expected: the manifest's counts
        restored: the restored database's counts

    Returns:
        list[str]: each difference, empty when the two are equal
    """
    differences = []
    for name in sorted(set(expected) | set(restored)):
        if name not in restored:
            differences.append(f"{name} is missing, the manifest holds {expected[name]} rows")
        elif name not in expected:
            differences.append(f"{name} is not in the manifest, restored with {restored[name]} rows")
        elif expected[name] != restored[name]:
            differences.append(f"{name} holds {restored[name]} rows, the manifest {expected[name]}")
    return differences
