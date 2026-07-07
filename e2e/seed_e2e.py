"""Seed the hub DB for the self-contained E2E — run INSIDE the kdf-api container.

The driver (ci_stack.py) pipes this file into the container's Python over stdin
(`docker compose exec -T kdf-api python -`) after `alembic upgrade head`, passing
the run's fixed credentials via `-e` env flags. It provisions the two things a
fresh CI database lacks (both are gitignored out of a clean checkout):

  1. An ACTIVE login user  — `seed-all-users` reads gitignored JSON fixtures, so
     it creates zero users in CI; we create one programmatically instead.
  2. One OIDC client PER TENANT — the `seed oauth_clients` CLI mints RANDOM creds
     and prints the secret once (unrecoverable). For a repeatable stack we
     direct-insert each row with the run's FIXED creds — the same values the
     compose injects into that tenant's frontend/backend. Mirrors
     integration_tests/test_oidc_e2e_db.py.

A client is seeded only when its client_id env is present, so a single-tenant run
(`ci_stack.py up --tenants fitness`) seeds just that tenant's client.

Idempotent: re-running is a no-op if the user / client already exist. Exits
non-zero on any failure so the driver surfaces it.
"""
import os
import sys

from sqlmodel import Session, select

from api.auth.schemas import RegisterRequest
from api.auth.service import AuthDatabaseService
from api.database.dependencies import get_engine
from api.oauth.enums import OAuthClientType
from api.oauth.models import OAuthClient
from api.oauth.service import hash_client_secret

USERNAME = os.environ.get("E2E_LOGIN_USERNAME", "e2e-user")
PASSWORD = os.environ.get("E2E_LOGIN_PASSWORD", "E2eTest123!")
EMAIL = os.environ.get("E2E_LOGIN_EMAIL", "e2e-user@example.com")

# One entry per tenant. Seeded only when the *_ID + *_SECRET envs are both set.
CLIENTS = [
    {
        "env_id": "E2E_OIDC_CLIENT_ID",
        "env_secret": "E2E_OIDC_CLIENT_SECRET",
        "redirect": os.environ.get(
            "E2E_OIDC_REDIRECT_URI", "http://localhost:3000/api/auth/oidc/callback"
        ),
        "name": "Fitness App (E2E)",
    },
    {
        "env_id": "E2E_TIFFANYS_CLIENT_ID",
        "env_secret": "E2E_TIFFANYS_CLIENT_SECRET",
        "redirect": os.environ.get(
            "E2E_TIFFANYS_REDIRECT_URI", "http://localhost:3001/api/auth/oidc/callback"
        ),
        "name": "Tiffany's Space (E2E)",
    },
    {
        # The `auth` journey has no tenant app — a synthetic client whose callback
        # the auth spec intercepts (nothing listens on :9999).
        "env_id": "E2E_AUTH_CLIENT_ID",
        "env_secret": "E2E_AUTH_CLIENT_SECRET",
        "redirect": os.environ.get(
            "E2E_AUTH_REDIRECT_URI", "http://localhost:9999/callback"
        ),
        "name": "Auth-UI Journey (E2E)",
    },
]


def seed_user() -> None:
    svc = AuthDatabaseService()
    if svc.get_user_by_username(USERNAME):
        print(f"[seed] user {USERNAME!r} already active — skip")
        return
    user = svc.create_user(
        RegisterRequest(username=USERNAME, password=PASSWORD, email=EMAIL),
        auto_activate=True,  # status=active so /oauth/login accepts it
    )
    print(f"[seed] created active user {USERNAME!r} id={user.id}")


def seed_oidc_client(client_id: str, client_secret: str, redirect: str, name: str) -> None:
    with Session(get_engine()) as s:
        exists = s.exec(
            select(OAuthClient).where(OAuthClient.client_id == client_id)
        ).first()
        if exists is not None:
            print(f"[seed] OIDC client {client_id!r} already present — skip")
            return
        s.add(
            OAuthClient(
                client_id=client_id,
                client_secret_hash=hash_client_secret(client_secret),
                client_name=name,
                client_type=OAuthClientType.confidential,
                redirect_uris=[redirect],
                allowed_scopes=["openid", "profile", "email", "offline_access"],
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                token_endpoint_auth_method="client_secret_basic",
                audience=client_id,  # per-client aud == client_id
                is_active=True,
            )
        )
        s.commit()
    print(f"[seed] inserted OIDC client {name!r} ({client_id!r}) redirect={redirect}")


def main() -> None:
    seed_user()
    seeded = 0
    for c in CLIENTS:
        client_id = os.environ.get(c["env_id"])
        client_secret = os.environ.get(c["env_secret"])
        if client_id and client_secret:
            seed_oidc_client(client_id, client_secret, c["redirect"], c["name"])
            seeded += 1
    if seeded == 0:
        print("[seed] WARNING: no OIDC client env provided — seeded none", file=sys.stderr)
    print("[seed] hub seed complete")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — surface any failure to the driver
        print(f"[seed] FAILED: {exc!r}", file=sys.stderr)
        raise
