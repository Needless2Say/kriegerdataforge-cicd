"""
The backup archive's contract (the secrets moves, step 2), kdf_backup/archive.py.

The app's own dump tool writes a folder of its manifest and its dump. cicd checks both, adds the backup's identity and
packs them into a tar whose bytes depend on its contents alone. The HMAC signs the row's plain columns, the encrypted
archive's SHA256 among them, so no field and no archive changes unseen, and a restore refuses an inner manifest that
names another backup than the row it came from.
"""

from __future__ import annotations

# standard imports
import hashlib
import io
import json
import tarfile
from pathlib import Path

# third party imports
import pytest
from kdf_backup import archive


KEY_HEX: str = "11" * 32
KEY:     bytes = bytes.fromhex(KEY_HEX)
DUMP:    bytes = b"PGDMP fake custom archive bytes"
ID:      str = "3f2b8c1e-7d4a-4b9e-9c1f-2a6d8e0b5c47"


def tool_folder(tmp_path: Path, **changes: object) -> Path:
    """
    A folder as an app's dump tool writes it, a dump and a manifest that names it.

    Args:
        tmp_path: pytest's folder
        **changes: manifest fields to replace, None removing one

    Returns:
        Path: the folder
    """
    folder = tmp_path / "tool"
    folder.mkdir()
    (folder / "dump.pgdump").write_bytes(DUMP)
    manifest: dict[str, object] = {
        "taken_at": "2026-11-20T06:00:00Z",
        "server_version": "17.12 (4d8000a)",
        "pg_dump_version": "pg_dump (PostgreSQL) 17.12 (Debian 17.12-1.pgdg13+1)",
        "alembic_revision": "a1b2c3d4e5f6",
        "tables": {"public.alembic_version": 1, "public.kdfusers": 11},
        "dump": {"file": "dump.pgdump", "bytes": len(DUMP), "sha256": hashlib.sha256(DUMP).hexdigest()},
    }
    for name, value in changes.items():
        if value is None:
            manifest.pop(name, None)
        else:
            manifest[name] = value
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding = "utf-8")
    return folder


def signed_metadata(**changes: object) -> dict[str, object]:
    """
    The row's plain columns as a run signs them.

    Args:
        **changes: fields to replace

    Returns:
        dict[str, object]: the metadata
    """
    metadata: dict[str, object] = {
        "backup_id": ID,
        "app": "fitness",
        "environment": "prod",
        "taken_at": "2026-11-20T06:00:00Z",
        "pg_dump_version": "pg_dump (PostgreSQL) 17.12 (Debian 17.12-1.pgdg13+1)",
        "server_version": "17.12 (4d8000a)",
        "size_bytes": 4096,
        "archive_sha256": "ab" * 32,
    }
    metadata.update(changes)
    return metadata

# ======================================================================================================================
# The tool's folder
# ======================================================================================================================

def test_a_tool_folder_whose_dump_matches_its_manifest_is_read(tmp_path: Path) -> None:
    manifest, dump = archive.read_tool_folder(tool_folder(tmp_path))

    assert manifest["tables"] == {"public.alembic_version": 1, "public.kdfusers": 11}
    assert dump.read_bytes() == DUMP


@pytest.mark.parametrize(
    "changes",
    [
        {"dump": {"file": "dump.pgdump", "bytes": len(DUMP), "sha256": "00" * 32}},
        {"dump": {"file": "dump.pgdump", "bytes": len(DUMP) + 1, "sha256": hashlib.sha256(DUMP).hexdigest()}},
        {"dump": {"file": "../dump.pgdump", "bytes": len(DUMP), "sha256": hashlib.sha256(DUMP).hexdigest()}},
        {"dump": {"file": "absent.pgdump", "bytes": len(DUMP), "sha256": hashlib.sha256(DUMP).hexdigest()}},
        {"taken_at": "2026-11-20 06:00:00"},
        {"taken_at": None},
        {"server_version": None},
        {"pg_dump_version": ""},
        {"tables": {"public.kdfusers": -1}},
        {"tables": {"public.kdfusers": "11"}},
        {"tables": []},
        {"alembic_revision": 7},
        {"server_version": "16.4", "pg_dump_version": "pg_dump (PostgreSQL) 17.12"},
        {"server_version": "17.12", "pg_dump_version": "pg_dump (PostgreSQL) 16.4"},
        {"server_version": "seventeen"},
        {"backup_id": ID},
        {"app": "hub"},
    ],
)
def test_a_tool_folder_out_of_its_contract_is_refused(tmp_path: Path, changes: dict[str, object]) -> None:
    with pytest.raises(archive.ArchiveError):
        archive.read_tool_folder(tool_folder(tmp_path, **changes))


def test_a_folder_with_no_manifest_is_refused(tmp_path: Path) -> None:
    folder = tool_folder(tmp_path)
    (folder / "manifest.json").unlink()

    with pytest.raises(archive.ArchiveError, match = "manifest"):
        archive.read_tool_folder(folder)


def test_the_major_of_a_version_is_read_from_a_server_or_a_tool() -> None:
    assert archive.major_of("17.12 (4d8000a)") == 17
    assert archive.major_of("pg_dump (PostgreSQL) 16.4 (Ubuntu 16.4-1)") == 16
    assert archive.major_of("18beta1") == 18
    with pytest.raises(archive.ArchiveError):
        archive.major_of("no version here")

# ======================================================================================================================
# The pack
# ======================================================================================================================

def test_a_pack_is_the_manifest_with_its_identity_then_the_dump(tmp_path: Path) -> None:
    manifest, dump = archive.read_tool_folder(tool_folder(tmp_path))
    out = tmp_path / "archive.tar"

    metadata = archive.pack(manifest, dump, app = "fitness", environment = "prod", backup_id = ID, out = out)

    with tarfile.open(out, mode = "r:") as tar:
        names = tar.getnames()
        inner = json.loads(tar.extractfile("manifest.json").read())
        assert tar.extractfile("dump.pgdump").read() == DUMP
    assert names == ["manifest.json", "dump.pgdump"]
    assert (inner["backup_id"], inner["app"], inner["environment"]) == (ID, "fitness", "prod")
    assert inner["kdf_backup_format"] == archive.FORMAT
    assert metadata == {
        "backup_id": ID,
        "app": "fitness",
        "environment": "prod",
        "taken_at": "2026-11-20T06:00:00Z",
        "pg_dump_version": manifest["pg_dump_version"],
        "server_version": "17.12 (4d8000a)",
    }


def test_two_packs_of_the_same_contents_are_the_same_bytes(tmp_path: Path) -> None:
    manifest, dump = archive.read_tool_folder(tool_folder(tmp_path))
    first, second = tmp_path / "one.tar", tmp_path / "two.tar"

    archive.pack(manifest, dump, app = "fitness", environment = "prod", backup_id = ID, out = first)
    archive.pack(manifest, dump, app = "fitness", environment = "prod", backup_id = ID, out = second)

    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize(
    "identity",
    [
        {"app": "Fitness", "environment": "prod", "backup_id": ID},
        {"app": "fitness", "environment": "staging", "backup_id": ID},
        {"app": "fitness", "environment": "prod", "backup_id": "not-a-uuid"},
        {"app": "fitness", "environment": "prod", "backup_id": ID.upper()},
    ],
)
def test_a_pack_with_an_identity_out_of_its_shape_is_refused(tmp_path: Path, identity: dict[str, str]) -> None:
    manifest, dump = archive.read_tool_folder(tool_folder(tmp_path))

    with pytest.raises(archive.ArchiveError):
        archive.pack(manifest, dump, out = tmp_path / "archive.tar", **identity)

# ======================================================================================================================
# The signature
# ======================================================================================================================

def test_a_signature_checks_against_the_metadata_it_signed() -> None:
    signature = archive.sign(signed_metadata(), KEY)

    assert len(signature) == 64
    assert archive.verify(signed_metadata(), signature, KEY)


@pytest.mark.parametrize(
    "field, value",
    [
        ("backup_id", "3f2b8c1e-7d4a-4b9e-9c1f-2a6d8e0b5c48"),
        ("app", "hub"),
        ("environment", "dev"),
        ("taken_at", "2026-11-20T06:00:01Z"),
        ("pg_dump_version", "pg_dump (PostgreSQL) 17.11"),
        ("server_version", "17.11 (4d8000a)"),
        ("size_bytes", 4097),
        ("archive_sha256", "cd" * 32),
    ],
)
def test_a_tampered_field_fails_the_signature(field: str, value: object) -> None:
    signature = archive.sign(signed_metadata(), KEY)

    assert not archive.verify(signed_metadata(**{field: value}), signature, KEY)


def test_another_key_fails_the_signature() -> None:
    signature = archive.sign(signed_metadata(), KEY)

    assert not archive.verify(signed_metadata(), signature, bytes.fromhex("22" * 32))


@pytest.mark.parametrize("signature", ["", "zz" * 32, "ab" * 31, None, 7])
def test_a_signature_out_of_its_shape_never_checks(signature: object) -> None:
    assert not archive.verify(signed_metadata(), signature, KEY)


@pytest.mark.parametrize(
    "changes",
    [
        {"size_bytes": 0},
        {"size_bytes": "4096"},
        {"archive_sha256": "AB" * 32},
        {"extra": "a field no column holds"},
        {"backup_id": None},
    ],
)
def test_metadata_out_of_its_shape_is_neither_signed_nor_checked(changes: dict[str, object]) -> None:
    metadata = signed_metadata(**changes)
    metadata = {name: value for name, value in metadata.items() if value is not None}

    with pytest.raises(archive.ArchiveError):
        archive.sign(metadata, KEY)
    assert not archive.verify(metadata, "ab" * 32, KEY)


def test_a_key_is_read_from_its_64_hexadecimal_digits_alone() -> None:
    assert archive.read_key(KEY_HEX + "\n") == KEY
    for text in ("", "11" * 31, "zz" * 32, "11" * 33):
        with pytest.raises(archive.ArchiveError) as refused:
            archive.read_key(text)
        assert text not in str(refused.value) or not text

# ======================================================================================================================
# The open, for a restore
# ======================================================================================================================

def packed(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    """
    A packed archive and the metadata the pack returned.

    Args:
        tmp_path: pytest's folder

    Returns:
        tuple[Path, dict[str, object]]: the tar and its metadata
    """
    manifest, dump = archive.read_tool_folder(tool_folder(tmp_path))
    out = tmp_path / "archive.tar"
    return out, archive.pack(manifest, dump, app = "fitness", environment = "prod", backup_id = ID, out = out)


def test_an_archive_opens_to_its_manifest_and_its_dump(tmp_path: Path) -> None:
    out, metadata = packed(tmp_path)

    manifest, dump = archive.open_archive(out, tmp_path / "opened", expected = metadata)

    assert manifest["backup_id"] == ID
    assert dump.read_bytes() == DUMP


@pytest.mark.parametrize("field", ["backup_id", "app", "environment", "taken_at", "server_version", "pg_dump_version"])
def test_an_archive_naming_another_backup_than_its_row_is_refused(tmp_path: Path, field: str) -> None:
    out, metadata = packed(tmp_path)
    expected = {**metadata, field: "something else"}

    with pytest.raises(archive.ArchiveError, match = field):
        archive.open_archive(out, tmp_path / "opened", expected = expected)


def tar_of(members: list[tuple[str, bytes, bytes]]) -> bytes:
    """
    A tar of the given members, each a name, a kind and its bytes.

    Args:
        members: each name, its kind (b"file", b"cont", b"link" or b"dir") and its bytes

    Returns:
        bytes: the tar
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj = buffer, mode = "w:") as tar:
        for name, kind, data in members:
            info = tarfile.TarInfo(name)
            if kind == b"link":
                info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
            elif kind == b"dir":
                info.type = tarfile.DIRTYPE
            else:
                info.size = len(data)
                if kind == b"cont":
                    info.type = tarfile.CONTTYPE
            tar.addfile(info, io.BytesIO(data) if kind in (b"file", b"cont") else None)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "members",
    [
        [("dump.pgdump", b"file", DUMP), ("manifest.json", b"file", b"{}")],
        [("manifest.json", b"file", b"{}")],
        [("manifest.json", b"file", b"{}"), ("dump.pgdump", b"file", DUMP), ("extra", b"file", b"x")],
        [("manifest.json", b"file", b"{}"), ("dump.pgdump", b"link", b"")],
        [("manifest.json", b"file", b"{}"), ("../dump.pgdump", b"file", DUMP)],
        [("manifest.json", b"dir", b""), ("dump.pgdump", b"file", DUMP)],
    ],
)
def test_a_tar_out_of_its_layout_is_refused_before_anything_is_written(
    tmp_path: Path,
    members: list[tuple[str, bytes, bytes]],
) -> None:
    out = tmp_path / "odd.tar"
    out.write_bytes(tar_of(members))

    with pytest.raises(archive.ArchiveError):
        archive.open_archive(out, tmp_path / "opened", expected = signed_metadata())
    assert not (tmp_path / "opened").exists() or not any((tmp_path / "opened").iterdir())


def test_a_dump_changed_inside_its_tar_is_refused(tmp_path: Path) -> None:
    out, metadata = packed(tmp_path)
    with tarfile.open(out, mode = "r:") as tar:
        inner = tar.extractfile("manifest.json").read()
    out.write_bytes(tar_of([("manifest.json", b"file", inner), ("dump.pgdump", b"file", DUMP + b"!")]))

    with pytest.raises(archive.ArchiveError, match = "dump"):
        archive.open_archive(out, tmp_path / "opened", expected = metadata)

# ======================================================================================================================
# The counts, after a restore
# ======================================================================================================================

def test_restored_counts_equal_to_the_manifest_differ_in_nothing() -> None:
    assert archive.count_differences({"public.a": 1, "public.b": 0}, {"public.b": 0, "public.a": 1}) == []


def test_each_missing_extra_or_changed_table_is_named() -> None:
    differences = archive.count_differences(
        {"public.a": 1, "public.b": 2, "public.c": 3},
        {"public.a": 1, "public.b": 5, "public.d": 0},
    )

    assert differences == [
        "public.b holds 5 rows, the manifest 2",
        "public.c is missing, the manifest holds 3 rows",
        "public.d is not in the manifest, restored with 0 rows",
    ]

# ======================================================================================================================
# What a restore could not use, refused before it is stored
# ======================================================================================================================

def test_an_empty_dump_is_refused(tmp_path: Path) -> None:
    folder = tool_folder(
        tmp_path,
        dump = {"file": "dump.pgdump", "bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()},
    )
    (folder / "dump.pgdump").write_bytes(b"")

    with pytest.raises(archive.ArchiveError):
        archive.read_tool_folder(folder)


def test_a_dump_that_is_not_a_custom_archive_is_refused(tmp_path: Path) -> None:
    plain  = b"-- PostgreSQL database dump, plain text"
    folder = tool_folder(
        tmp_path,
        dump = {"file": "dump.pgdump", "bytes": len(plain), "sha256": hashlib.sha256(plain).hexdigest()},
    )
    (folder / "dump.pgdump").write_bytes(plain)

    with pytest.raises(archive.ArchiveError, match = "PGDMP"):
        archive.read_tool_folder(folder)


def test_a_manifest_that_packs_past_the_limit_a_restore_opens_is_refused(tmp_path: Path) -> None:
    folder = tool_folder(tmp_path, notes = "")
    path   = folder / "manifest.json"
    filler = archive.MANIFEST_BYTES - path.stat().st_size - 8
    path.write_text(json.dumps({**json.loads(path.read_text()), "notes": "x" * filler}), encoding = "utf-8")
    manifest, dump = archive.read_tool_folder(folder)

    with pytest.raises(archive.ArchiveError, match = "packed"):
        archive.pack(manifest, dump, app = "fitness", environment = "prod", backup_id = ID, out = tmp_path / "out.tar")


def test_a_contiguous_member_is_refused_as_no_plain_file(tmp_path: Path) -> None:
    out, metadata = packed(tmp_path)
    with tarfile.open(out, mode = "r:") as tar:
        inner = tar.extractfile("manifest.json").read()
    out.write_bytes(tar_of([("manifest.json", b"file", inner), ("dump.pgdump", b"cont", DUMP)]))

    with pytest.raises(archive.ArchiveError, match = "plain file"):
        archive.open_archive(out, tmp_path / "opened", expected = metadata)


def test_an_inner_manifest_naming_another_dump_file_is_refused(tmp_path: Path) -> None:
    out, metadata = packed(tmp_path)
    with tarfile.open(out, mode = "r:") as tar:
        inner = json.loads(tar.extractfile("manifest.json").read())
    inner["dump"]["file"] = "other.pgdump"
    out.write_bytes(tar_of([("manifest.json", b"file", archive.canonical(inner)), ("dump.pgdump", b"file", DUMP)]))

    with pytest.raises(archive.ArchiveError, match = "dump"):
        archive.open_archive(out, tmp_path / "opened", expected = metadata)
