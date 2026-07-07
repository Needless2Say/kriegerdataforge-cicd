"""Seed the hub DB for the self-contained E2E — run INSIDE the kdf-api container.

The driver (ci_stack.py) pipes this file into the container's Python over stdin
(`docker compose exec -T kdf-api python -`) after `alembic upgrade head`. It
provisions the two things a fresh CI database lacks (both gitignored out of a
clean checkout):

  1. An ACTIVE login user  — `seed-all-users` reads gitignored JSON fixtures, so
     it creates zero users in CI; we create one programmatically instead.
  2. One OIDC client PER ACTIVE JOURNEY — the `seed oauth_clients` CLI mints
     RANDOM creds and prints the secret once (unrecoverable). For a repeatable
     stack we direct-insert each row with the run's FIXED creds — the same values
     the compose injects into that tenant's frontend/backend. Mirrors
     integration_tests/test_oidc_e2e_db.py.

The client list is TENANT-AGNOSTIC: the driver builds it from each active
journey's manifest + generated creds and hands it in as the JSON env
`E2E_SEED_CLIENTS` (list of {client_id, client_secret, redirect, name}). This
file has no per-tenant knowledge — onboarding a journey never edits it.

Idempotent: re-running is a no-op if the user / client already exist. Exits
non-zero on any failure so the driver surfaces it.
"""
import json
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
    clients = json.loads(os.environ.get("E2E_SEED_CLIENTS", "[]"))
    for c in clients:
        seed_oidc_client(c["client_id"], c["client_secret"], c["redirect"], c["name"])
    if not clients:
        print("[seed] WARNING: no OIDC clients provided (E2E_SEED_CLIENTS empty)", file=sys.stderr)
    print(f"[seed] hub seed complete ({len(clients)} client(s))")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — surface any failure to the driver
        print(f"[seed] FAILED: {exc!r}", file=sys.stderr)
        raise
