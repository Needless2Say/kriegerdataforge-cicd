"""
The backup's and the restore's steps (the secrets moves, step 2), kdf_backup/cli.py.

Each step reads its secret from its own environment alone. `age` runs with no environment but PATH. The identity's file
is the job's alone and is removed even when the decryption fails. A drill restores into the job's own service alone,
of the archive's major, and no restore loads an archive from a newer pg_dump than its server.
"""

from __future__ import annotations

# standard imports
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# third party imports
import pytest
from kdf_backup import archive, cli, store


KEY_HEX:   str = "11" * 32
KEY:       bytes = bytes.fromhex(KEY_HEX)
RECIPIENT: str = "age1" + "q" * 58
ID:        str = "3f2b8c1e-7d4a-4b9e-9c1f-2a6d8e0b5c47"


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    The work folder, its step output file and a clean environment of the steps' names.
    """
    work = tmp_path / "work"
    for name in list(os.environ):
        if name.startswith(("KDF_", "BACKUP_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv(cli.WORK_ENV, str(work))
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output.txt"))
    return work


def outputs(tmp_path: Path) -> dict[str, str]:
    """
    The step outputs written so far.

    Args:
        tmp_path: pytest's folder

    Returns:
        dict[str, str]: each output
    """
    path  = tmp_path / "output.txt"
    lines = path.read_text(encoding = "utf-8").splitlines() if path.exists() else []
    return dict(line.split("=", 1) for line in lines)


class FakeAge:
    """
    A stand in for `age` that reverses its input's bytes, and records each call and its environment.
    """
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.fail = fail


    def __call__(self, command: list[str], **kwargs: Any) -> Any:
        self.calls.append((command, kwargs["env"]))
        out = Path(command[command.index("-o") + 1])
        if not self.fail:
            out.write_bytes(Path(command[-1]).read_bytes()[::-1])


        class Done:
            returncode = 1 if self.fail else 0


        return Done()


@pytest.fixture
def age(monkeypatch: pytest.MonkeyPatch) -> FakeAge:
    fake = FakeAge()
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/age" if name == "age" else None)
    monkeypatch.setattr(cli.subprocess, "run", fake)
    return fake


class Connection:
    """
    A fake connection answering each statement from a table, and closing.
    """
    def __init__(self, answers: dict[str, list[tuple]]) -> None:
        self.answers = answers
        self.closed  = False


    def execute(self, query: str, params: tuple = ()) -> Any:
        rows = self.answers[query] if query in self.answers else self.answers["*"]


        class Cursor:
            def fetchone(self) -> tuple | None:
                return rows[0] if rows else None


            def fetchall(self) -> list[tuple]:
                return list(rows)


        return Cursor()


    def close(self) -> None:
        self.closed = True


def signed_row(data: bytes, key: bytes = KEY, server: str = "17.12 (4d8000a)") -> tuple:
    """
    A stored row as ROW selects it, its archive *data*.

    Args:
        data: the archive's bytes
        key: the signing key
        server: its server_version

    Returns:
        tuple: the row
    """
    metadata = {
        "backup_id": ID,
        "app": "fitness",
        "environment": "prod",
        "taken_at": "2026-11-20T06:00:00Z",
        "pg_dump_version": "pg_dump (PostgreSQL) 17.12",
        "server_version": server,
        "size_bytes": len(data),
        "archive_sha256": hashlib.sha256(data).hexdigest(),
    }
    taken    = datetime(2026, 11, 20, 6, 0, tzinfo = UTC)
    return (
        ID,
        "fitness",
        "prod",
        taken,
        metadata["pg_dump_version"],
        server,
        len(data),
        metadata["archive_sha256"],
        archive.sign(metadata, key),
        metadata["archive_sha256"],
        datetime(2026, 11, 20, 6, 5, tzinfo = UTC),
    )


def scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KDF_APP", "fitness")
    monkeypatch.setenv("KDF_ENVIRONMENT", "prod")
    monkeypatch.setenv("KDF_BACKUP_ID", ID)

# ======================================================================================================================
# The backup's steps
# ======================================================================================================================

def test_the_options_are_checked_and_kept(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "KDF_PRUNE": "true",
        "KDF_KEEP": "4",
        "KDF_CAPACITY": "1000000000",
        "KDF_BOUND": "50000000",
        "KDF_LOCK_WAIT": "300",
    }.items():
        monkeypatch.setenv(name, value)

    assert cli.main(["options"]) == 0
    assert json.loads((folder / "options.json").read_text())["keep"] == 4


def test_pruning_on_with_no_n_fails_before_the_dump(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "KDF_PRUNE": "true",
        "KDF_CAPACITY": "1000000000",
        "KDF_BOUND": "50000000",
        "KDF_LOCK_WAIT": "300",
    }.items():
        monkeypatch.setenv(name, value)

    assert cli.main(["options"]) == 1
    assert not (folder / "options.json").exists()


def test_a_pack_names_a_new_backup_and_keeps_its_metadata(
    folder: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = tmp_path / "tool"
    tool.mkdir()
    (tool / "dump.pgdump").write_bytes(b"PGDMP")
    (tool / "manifest.json").write_text(json.dumps({
        "taken_at": "2026-11-20T06:00:00Z",
        "server_version": "17.12",
        "pg_dump_version": "pg_dump (PostgreSQL) 17.12",
        "alembic_revision": None,
        "tables": {"public.a": 1},
        "dump": {"file": "dump.pgdump", "bytes": 5, "sha256": hashlib.sha256(b"PGDMP").hexdigest()},
    }))
    monkeypatch.setenv("KDF_TOOL_DIR", str(tool))
    monkeypatch.setenv("KDF_APP", "fitness")
    monkeypatch.setenv("KDF_ENVIRONMENT", "prod")

    assert cli.main(["pack"]) == 0

    metadata = json.loads((folder / "metadata.json").read_text())
    assert metadata["backup_id"] == outputs(tmp_path)["backup_id"]
    assert (folder / "archive.tar").is_file()


def test_the_encryption_runs_age_with_path_alone_and_removes_the_tar(
    folder: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    age: FakeAge,
) -> None:
    folder.mkdir()
    (folder / "archive.tar").write_bytes(b"plain tar")
    (folder / "metadata.json").write_text(json.dumps({"backup_id": ID}))
    recipient = tmp_path / "recipient.txt"
    recipient.write_text(RECIPIENT + "\n")
    monkeypatch.setenv("KDF_RECIPIENT_FILE", str(recipient))
    monkeypatch.setenv("BACKUP_HMAC_KEY", KEY_HEX)

    assert cli.main(["encrypt"]) == 0

    command, environment = age.calls[0]
    assert command[1:3] == ["-r", RECIPIENT]
    assert set(environment) == {"PATH"}
    assert not (folder / "archive.tar").exists()
    metadata = json.loads((folder / "metadata.json").read_text())
    assert metadata["archive_sha256"] == hashlib.sha256(b"plain tar"[::-1]).hexdigest()
    assert metadata["size_bytes"] == 9


@pytest.mark.parametrize("text", ["", "age1short", "AGE-SECRET-KEY-1" + "Q" * 58, RECIPIENT + "\n" + RECIPIENT])
def test_a_recipient_file_that_is_not_one_recipient_is_refused(
    folder: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    age: FakeAge,
    text: str,
) -> None:
    recipient = tmp_path / "recipient.txt"
    recipient.write_text(text)
    monkeypatch.setenv("KDF_RECIPIENT_FILE", str(recipient))

    assert cli.main(["encrypt"]) == 1
    assert age.calls == []


def test_the_signature_is_the_metadatas(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    metadata = {
        "backup_id": ID,
        "app": "fitness",
        "environment": "prod",
        "taken_at": "2026-11-20T06:00:00Z",
        "pg_dump_version": "pg_dump (PostgreSQL) 17.12",
        "server_version": "17.12",
        "size_bytes": 9,
        "archive_sha256": "ab" * 32,
    }
    folder.mkdir()
    (folder / "metadata.json").write_text(json.dumps(metadata))
    monkeypatch.setenv("BACKUP_HMAC_KEY", KEY_HEX)

    assert cli.main(["sign"]) == 0
    assert archive.verify(metadata, (folder / "signature.txt").read_text(), KEY)


def test_a_malformed_key_is_refused_without_its_text(
    folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder.mkdir()
    (folder / "metadata.json").write_text("{}")
    monkeypatch.setenv("BACKUP_HMAC_KEY", "not-a-key-but-a-secret-anyway")

    assert cli.main(["sign"]) == 1
    assert "not-a-key-but-a-secret-anyway" not in capsys.readouterr().out


def test_the_store_step_leaves_its_receipt_and_its_issues(
    folder: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder.mkdir()
    (folder / "options.json").write_text(
        json.dumps({"prune": True, "keep": 4, "capacity": 10, "bound": 1, "lock_wait": 60}),
    )
    (folder / "metadata.json").write_text(json.dumps({"backup_id": ID}))
    (folder / "signature.txt").write_text("ab" * 32)
    monkeypatch.setenv("BACKUP_HMAC_KEY", KEY_HEX)
    monkeypatch.setenv("BACKUP_STORE_WRITER_URL", "postgresql://w:p@store/neondb")
    seen: dict[str, Any] = {}
    connection = Connection({})
    monkeypatch.setattr(cli.store, "connect", lambda url: connection)


    def fake_store(conn: Any, **kwargs: Any) -> store.Outcome:
        seen.update(kwargs)
        return store.Outcome(
            receipt = {"format": "kdf-backup-receipt-1"},
            issues = ["x is missing since the last receipt"],
        )


    monkeypatch.setattr(cli.store, "store_backup", fake_store)

    assert cli.main(["store"]) == 0

    assert seen["previous"] is None and seen["keep"] == 4 and seen["key"] == KEY
    assert json.loads((folder / "receipt.json").read_text()) == {"format": "kdf-backup-receipt-1"}
    assert "missing" in (folder / "issues.md").read_text()
    assert outputs(tmp_path)["issues"] == "true"
    assert connection.closed

# ======================================================================================================================
# The restore's steps
# ======================================================================================================================

def test_the_plan_gives_the_checked_rows_major(folder: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope(monkeypatch)
    monkeypatch.setenv("BACKUP_HMAC_KEY", KEY_HEX)
    monkeypatch.setenv("BACKUP_STORE_READER_URL", "postgresql://r:p@store/neondb")
    monkeypatch.setattr(cli.store, "connect", lambda url: Connection({store.ROW: [signed_row(b"sealed")]}))

    assert cli.main(["plan"]) == 0
    assert outputs(tmp_path)["major"] == "17"


def test_the_plan_refuses_a_row_whose_signature_fails(
    folder: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope(monkeypatch)
    monkeypatch.setenv("BACKUP_HMAC_KEY", KEY_HEX)
    monkeypatch.setenv("BACKUP_STORE_READER_URL", "postgresql://r:p@store/neondb")
    forged = signed_row(b"sealed", key = bytes.fromhex("22" * 32))
    monkeypatch.setattr(cli.store, "connect", lambda url: Connection({store.ROW: [forged]}))

    assert cli.main(["plan"]) == 1
    assert "major" not in outputs(tmp_path)


def test_a_fetched_archive_changed_from_its_row_is_refused(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope(monkeypatch)
    monkeypatch.setenv("BACKUP_HMAC_KEY", KEY_HEX)
    monkeypatch.setenv("BACKUP_STORE_READER_URL", "postgresql://r:p@store/neondb")
    answers = {store.ROW: [signed_row(b"sealed")], store.FETCH: [(b"sealed but swapped",)]}
    monkeypatch.setattr(cli.store, "connect", lambda url: Connection(answers))

    assert cli.main(["fetch"]) == 0
    assert cli.main(["check"]) == 1
    assert not (folder / "metadata.json").exists()


def test_a_fetched_archive_that_matches_its_row_is_checked(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope(monkeypatch)
    monkeypatch.setenv("BACKUP_HMAC_KEY", KEY_HEX)
    monkeypatch.setenv("BACKUP_STORE_READER_URL", "postgresql://r:p@store/neondb")
    answers = {store.ROW: [signed_row(b"sealed")], store.FETCH: [(b"sealed",)]}
    monkeypatch.setattr(cli.store, "connect", lambda url: Connection(answers))

    assert cli.main(["fetch"]) == 0
    assert cli.main(["check"]) == 0
    assert json.loads((folder / "metadata.json").read_text())["backup_id"] == ID


@pytest.mark.parametrize("fail", [False, True])
def test_the_identitys_file_is_removed_after_the_decryption_either_way(
    folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail: bool,
) -> None:
    folder.mkdir()
    (folder / "archive.age").write_bytes(b"sealed")
    monkeypatch.setenv("BACKUP_AGE_IDENTITY", "# created\nAGE-SECRET-KEY-1" + "Q" * 58)
    fake = FakeAge(fail = fail)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/age")
    monkeypatch.setattr(cli.subprocess, "run", fake)

    assert cli.main(["decrypt"]) == (1 if fail else 0)

    command, environment = fake.calls[0]
    assert command[1:3] == ["-d", "-i"]
    assert set(environment) == {"PATH"}
    assert not (folder / "identity.txt").exists()


def test_an_identity_that_is_not_one_is_refused_before_any_file(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKUP_AGE_IDENTITY", "a recipient, not an identity")

    assert cli.main(["decrypt"]) == 1
    assert not (folder / "identity.txt").exists()


def write_manifest(folder: Path, dumped: str = "pg_dump (PostgreSQL) 17.12", tables: dict | None = None) -> None:
    (folder / "restore").mkdir(parents = True)
    (folder / "restore" / "manifest.json").write_text(json.dumps({
        "pg_dump_version": dumped,
        "tables": tables if tables is not None else {"public.a": 2, "public.b": 0},
    }))


def test_a_drill_pointed_at_a_live_target_is_refused_before_it_connects(
    folder: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_manifest(folder)
    monkeypatch.setenv("KDF_MODE", "drill")
    monkeypatch.setenv("KDF_RESTORE_TARGET_URL", "postgresql://owner:p@ep-x.us-east-1.aws.neon.tech/neondb")


    def never(url: str) -> Any:
        raise AssertionError("a drill never connects to a live target")


    monkeypatch.setattr(cli.store, "connect", never)

    assert cli.main(["target"]) == 1


@pytest.mark.parametrize(
    "mode, served, code",
    [
        ("drill", "170012", 0),
        ("drill", "180001", 1),
        ("drill", "160015", 1),
        ("live", "180001", 0),
        ("live", "160015", 1),
    ],
)
def test_the_target_holds_the_archives_major(
    folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    served: str,
    code: int,
) -> None:
    write_manifest(folder)
    monkeypatch.setenv("KDF_MODE", mode)
    monkeypatch.setenv("KDF_RESTORE_TARGET_URL", "postgresql://postgres:local@127.0.0.1:5432/drill")
    monkeypatch.setattr(cli.store, "connect", lambda url: Connection({cli.SERVER_VERSION_NUM: [(served,)]}))

    assert cli.main(["target"]) == code


def test_restored_counts_equal_to_the_manifests_pass(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_manifest(folder)
    monkeypatch.setenv("KDF_RESTORE_TARGET_URL", "postgresql://postgres:local@127.0.0.1:5432/drill")
    answers = {
        cli.TABLES: [("public", "a"), ("public", "b")],
        'SELECT count(*) FROM "public"."a"': [(2,)],
        'SELECT count(*) FROM "public"."b"': [(0,)],
    }
    monkeypatch.setattr(cli.store, "connect", lambda url: Connection(answers))

    assert cli.main(["counts"]) == 0


def test_a_restored_count_that_differs_fails_naming_it(
    folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_manifest(folder)
    monkeypatch.setenv("KDF_RESTORE_TARGET_URL", "postgresql://postgres:local@127.0.0.1:5432/drill")
    answers = {
        cli.TABLES: [("public", "a"), ("public", "b")],
        'SELECT count(*) FROM "public"."a"': [(1,)],
        'SELECT count(*) FROM "public"."b"': [(0,)],
    }
    monkeypatch.setattr(cli.store, "connect", lambda url: Connection(answers))

    assert cli.main(["counts"]) == 1
    assert "public.a holds 1 rows, the manifest 2" in capsys.readouterr().out


def test_an_unknown_command_is_refused() -> None:
    assert cli.main(["drop"]) == 2
    assert cli.main([]) == 2
