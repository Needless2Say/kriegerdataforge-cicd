"""Seed the hub DB for the self-contained E2E — run INSIDE the kdf-api container.

The driver (ci_stack.py) pipes this file into the container's Python over stdin
(`docker compose exec -T kdf-api python -`) after `alembic upgrade head`, passing
the run's fixed credentials via `-e` env flags. It provisions the two things a
fresh CI database lacks (both are gitignored out of a clean checkout):

  1. An ACTIVE login user  — `seed-all-users` reads gitignored JSON fixtures, so
     it creates zero users in CI; we create one programmatically instead.
  2. The Fitness App OIDC client — the `seed oauth_clients` CLI mints a RANDOM
     client_id/secret and prints the secret once (unrecoverable). For a
     repeatable stack we direct-insert the row with the run's FIXED creds — the
     same values the compose injects into the frontend — so there is no
     capture-and-inject dance. This mirrors integration_tests/test_oidc_e2e_db.py.

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

CLIENT_ID = os.environ["E2E_OIDC_CLIENT_ID"]
CLIENT_SECRET = os.environ["E2E_OIDC_CLIENT_SECRET"]
REDIRECT_URI = os.environ.get(
    "E2E_OIDC_REDIRECT_URI", "http://localhost:3000/api/auth/oidc/callback"
)


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


def seed_oidc_client() -> None:
    with Session(get_engine()) as s:
        exists = s.exec(
            select(OAuthClient).where(OAuthClient.client_id == CLIENT_ID)
        ).first()
        if exists is not None:
            print(f"[seed] OIDC client {CLIENT_ID!r} already present — skip")
            return
        s.add(
            OAuthClient(
                client_id=CLIENT_ID,
                client_secret_hash=hash_client_secret(CLIENT_SECRET),
                client_name="Fitness App (E2E)",
                client_type=OAuthClientType.confidential,
                redirect_uris=[REDIRECT_URI],
                allowed_scopes=["openid", "profile", "email", "offline_access"],
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                token_endpoint_auth_method="client_secret_basic",
                audience=CLIENT_ID,  # per-client aud == client_id
                is_active=True,
            )
        )
        s.commit()
    print(f"[seed] inserted OIDC client {CLIENT_ID!r} redirect={REDIRECT_URI}")


def main() -> None:
    seed_user()
    seed_oidc_client()
    print("[seed] hub seed complete")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — surface any failure to the driver
        print(f"[seed] FAILED: {exc!r}", file=sys.stderr)
        raise
