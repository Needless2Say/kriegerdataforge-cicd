"""Seed the hub DB for the self-contained E2E — run INSIDE the kdf-api container.

The driver (ci_stack.py) pipes this file into the container's Python over stdin
(`docker compose exec -T kdf-api python -`) after `alembic upgrade head`. It
provisions the two things a fresh CI database lacks (both gitignored out of a
clean checkout):

  1. TWO active login users — `seed-all-users` reads gitignored JSON fixtures, so
     it creates zero users in CI; we create them programmatically instead:
     a plain user (the default journey identity) and a MODERATOR
     (global_permission_role=moderator) for journeys exercising moderator-gated
     surfaces (e.g. the reports standard: POST /reports is moderator+admin only).
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

from api.auth.enums import UserGlobalPermissionRole
from api.auth.models import KDFUser
from api.auth.schemas import RegisterRequest
from api.auth.service import AuthDatabaseService
from api.database.dependencies import get_engine
from api.oauth.enums import OAuthClientType
from api.oauth.models import OAuthClient
from api.oauth.service import hash_client_secret

USERNAME = os.environ.get("E2E_LOGIN_USERNAME", "e2e-user")
PASSWORD = os.environ.get("E2E_LOGIN_PASSWORD", "E2eTest123!")
EMAIL = os.environ.get("E2E_LOGIN_EMAIL", "e2e-user@example.com")
MOD_USERNAME = os.environ.get("E2E_MOD_USERNAME", "e2e-moderator")
MOD_PASSWORD = os.environ.get("E2E_MOD_PASSWORD", "E2eModTest123!")
MOD_EMAIL = os.environ.get("E2E_MOD_EMAIL", "e2e-moderator@example.com")


def seed_user(
    username: str, password: str, email: str, role: UserGlobalPermissionRole | None = None
) -> None:
    svc = AuthDatabaseService()
    if not svc.get_user_by_username(username):
        user = svc.create_user(
            RegisterRequest(username=username, password=password, email=email),
            auto_activate=True,  # status=active so /oauth/login accepts it
        )
        print(f"[seed] created active user {username!r} id={user.id}")
    else:
        print(f"[seed] user {username!r} already active — skip create")
    if role is None:
        return
    # Idempotent role ensure (fresh session — create_user's instance is detached):
    # tokens carry this global_permission_role claim, which moderator-gated app
    # endpoints (e.g. kdf_reports POST /reports) enforce.
    with Session(get_engine()) as s:
        row = s.exec(select(KDFUser).where(KDFUser.username == username)).one()
        if row.global_permission_role != role:
            row.global_permission_role = role
            s.add(row)
            s.commit()
            print(f"[seed] set {username!r} global_permission_role={role.value}")
        else:
            print(f"[seed] {username!r} already {role.value} — skip role")


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
    seed_user(USERNAME, PASSWORD, EMAIL)
    seed_user(MOD_USERNAME, MOD_PASSWORD, MOD_EMAIL, role=UserGlobalPermissionRole.moderator)
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
