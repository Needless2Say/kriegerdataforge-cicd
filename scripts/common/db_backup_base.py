"""
Shared backup logic for all KDF database backup scripts.

The connection string comes from --url, else DB_BACKUP_URL in the environment, else the env file, Tiffany's path kept
as it is. pg_dump gets it as libpq's PG variables in its own environment, never in its arguments, which a process
listing shows, and a failure is reported with the password masked, never the raw stderr (the secrets moves, step 2).

Usage (from a tenant script):
    from common.db_backup_base import run_backup

    run_backup(
        app_name="auth",
        default_env_file=".env.backup",
    )
"""

from __future__ import annotations

# standard imports
import argparse
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

# each URL query parameter libpq also reads from its environment, by the variable's name
QUERY_VARIABLES: dict[str, str] = {
    "sslmode": "PGSSLMODE",
    "sslrootcert": "PGSSLROOTCERT",
    "channel_binding": "PGCHANNELBINDING",
    "connect_timeout": "PGCONNECT_TIMEOUT",
    "options": "PGOPTIONS",
    "application_name": "PGAPPNAME",
}


def _check_pg_dump() -> None:
    """
    Check if pg_dump is available on system PATH. If not, exit with an error message.
    """
    if shutil.which("pg_dump") is None:
        sys.exit(
            "Error: pg_dump not found on PATH.\n" "Install PostgreSQL client tools and ensure pg_dump is accessible.",
        )


def _load_env_file(env_file: str) -> None:
    """
    Load key=value pairs from a .env file into the current process environment.

    Args:
        env_file: Path to the .env file

    Returns:
        None. Modifies os.environ in place
    """
    path = Path(env_file)
    if not path.is_file():
        sys.exit(f"Error: env file not found: {env_file}")

    with open(path) as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, _, value = line.partition("=")
            key   = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def connection_environment(db_url: str) -> dict[str, str]:
    """
    libpq's variables for a connection URL, so pg_dump's arguments carry no password.

    Args:
        db_url: A postgresql:// URL, a SQLAlchemy driver suffix allowed

    Returns:
        dict[str, str]: Each variable set, PGSSLMODE require when the URL names none
    """
    scheme, _, rest = db_url.partition("://")
    if scheme.split("+", 1)[0] not in ("postgresql", "postgres") or not rest:
        sys.exit("Error: the connection string is not a postgresql:// URL.")
    parts  = urlsplit("postgresql://" + rest)
    values = {
        "PGHOST": parts.hostname,
        "PGPORT": str(parts.port) if parts.port else None,
        "PGUSER": unquote(parts.username) if parts.username else None,
        "PGPASSWORD": unquote(parts.password) if parts.password else None,
        "PGDATABASE": unquote(parts.path.lstrip("/")) or None,
        "PGSSLMODE": "require",
    }
    for name, value in parse_qsl(parts.query):
        if name in QUERY_VARIABLES:
            values[QUERY_VARIABLES[name]] = value
    return {name: value for name, value in values.items() if value}


def masked(text: str, db_url: str) -> str:
    """
    A message with the URL's password masked wherever it appears.

    Args:
        text: The message
        db_url: The URL

    Returns:
        str: The message masked
    """
    rest = db_url.partition("://")[2]
    try:
        password = urlsplit("postgresql://" + rest).password if rest else None
    except ValueError:
        password = None
    for value in filter(None, {password, unquote(password) if password else None}):
        text = text.replace(value, "***")
    return text


def run_backup(app_name: str, default_env_file: str = ".env.backup") -> None:
    """
    Parse CLI args and run pg_dump for the given app.

    Args:
        app_name:        Short name used in the output filename (e.g. "auth", "fitness")
        default_env_file: Path to the .env file loaded when --url is not supplied

    Returns:
        None. Exits with an error message if something goes wrong
    """
    parser = argparse.ArgumentParser(description = f"Backup the {app_name} database to a pg_dump custom-format file.")
    parser.add_argument(
        "--env",
        choices = ["prod", "dev"],
        required = True,
        help = "Target environment (prod or dev). Used in the output filename.",
    )
    parser.add_argument(
        "--url",
        default = None,
        help = (
            "PostgreSQL connection URL (overrides DB_BACKUP_URL from the env file). " "Example: postgresql://user:pass@host:5432/dbname"
        ),
    )
    parser.add_argument(
        "--env-file",
        default = default_env_file,
        help = f"Path to the .env file containing DB_BACKUP_URL (default: {default_env_file}).",
    )
    parser.add_argument(
        "--out-dir",
        default = None,
        help = "Override the output directory (default: backups/<app_name>/ relative to script).",
    )
    args = parser.parse_args()

    _check_pg_dump()

    # resolve database URL, the environment's before the env file, which a job never has
    if args.url:
        db_url = args.url
    elif os.environ.get("DB_BACKUP_URL"):
        db_url = os.environ["DB_BACKUP_URL"]
    else:
        _load_env_file(args.env_file)
        db_url = os.environ.get("DB_BACKUP_URL")
        if not db_url:
            sys.exit(f"Error: DB_BACKUP_URL not set.\n" f"Supply --url or set DB_BACKUP_URL in {args.env_file}.")

    # resolve output path
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename  = f"{app_name}_{args.env}_{timestamp}.dump"

    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        # Default: <script_dir>/../../backups/<app_name>/
        # (scripts live in scripts/<app>/, backups go to scripts/backups/<app>/)
        script_dir = Path(__file__).resolve().parent.parent
        out_dir    = script_dir / "backups" / app_name

    out_dir.mkdir(parents = True, exist_ok = True)
    out_path = out_dir / filename

    # run pg_dump, the connection in libpq's variables alone and never in its arguments
    connection = connection_environment(db_url)
    child_env  = {name: value for name, value in os.environ.items() if name != "DB_BACKUP_URL"}
    child_env.update(connection)
    print(f"Backing up {app_name} [{args.env}] → {out_path}")
    result = subprocess.run(
        [
            "pg_dump",
            "--format=custom",
            "--no-password",
            "--file",
            str(out_path),
        ],
        capture_output = True,
        text = True,
        env = child_env,
    )

    if result.returncode != 0:
        print(masked(result.stderr.strip(), db_url), file = sys.stderr)
        sys.exit(f"pg_dump failed against {connection.get('PGHOST', 'the database')} (exit {result.returncode})")

    size_bytes = out_path.stat().st_size
    size_kb    = size_bytes / 1024
    print(f"Done. {out_path}  ({size_kb:.1f} KB)")
