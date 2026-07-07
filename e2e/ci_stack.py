#!/usr/bin/env python3
"""Driver for the self-contained Tier-2 E2E stack (docker-compose.e2e.yml).

One entry point for both `make e2e-ci*` locally and the CI workflow. It owns the
parts a bare `docker compose up` can't do:

  * generates a throwaway RS256 keypair + fixed-per-run OIDC client_id/secret +
    session secret + DB password, and threads them into the compose via the
    process env (so the hub, the frontend, and the seed all agree — no
    capture-and-inject). Secrets persist to e2e/.e2e-ci.json (gitignored) so
    re-running `up` reuses them instead of churning containers; `--regen` forces
    a fresh set.
  * sources GH_PACKAGES_PAT (env → fitness-app-backend/.env.local fallback) so
    the private-SDK image build works locally without exporting it by hand. In
    CI it comes from the GH_PACKAGES_PAT secret. Never printed.
  * builds, brings the stack up with healthcheck gating, migrates BOTH databases
    to head, seeds the active login user + the OIDC client (hub) and the food
    catalogue (fitness), in the one correct order.

Commands:
  up      build + up --wait + migrate + seed        (idempotent; leaves it up)
  down    stop + remove containers, volumes, network
  logs    tail compose logs (debug)

Then run Playwright against http://localhost:3000 (`make e2e` / `npm test`).

Generated keys are ephemeral and never touch a developer's real dev keypair.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent.parent  # e2e/ → cicd repo → workspace root (siblings)
COMPOSE = HERE / "docker-compose.e2e.yml"
SEED = HERE / "seed_e2e.py"
STATE = HERE / ".e2e-ci.json"  # gitignored — persisted per-run secrets

# Fixed login creds: match e2e/.env.example + Playwright's E2E_* defaults so the
# suite needs no wiring. Not sensitive (throwaway account in an ephemeral DB).
LOGIN_USERNAME = "e2e-user"
LOGIN_PASSWORD = "E2eTest123!"
LOGIN_EMAIL = "e2e-user@example.com"

BUILD_TIMEOUT = 1800  # first cold build (npm ci + SDK clone) can be minutes
WAIT_TIMEOUT = 420  # healthcheck gate; `next dev` compiles on first hit


# ── secret material ──────────────────────────────────────────────────────────


def _generate_keypair() -> tuple[str, str]:
    """RS256 keypair as (private PKCS#8 PEM, public SPKI PEM). Prefers the
    `cryptography` lib; falls back to the `openssl` CLI so the driver runs on a
    host without it (both produce the exact formats the hub + frontend expect)."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        priv = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        pub = (
            key.public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )
        return priv, pub
    except ImportError:
        priv = subprocess.run(
            ["openssl", "genpkey", "-algorithm", "RSA",
             "-pkeyopt", "rsa_keygen_bits:2048"],
            check=True, capture_output=True, text=True,
        ).stdout
        pub = subprocess.run(
            ["openssl", "pkey", "-pubout"],
            check=True, input=priv, capture_output=True, text=True,
        ).stdout
        return priv, pub


def _load_or_make_state(regen: bool) -> dict:
    if STATE.exists() and not regen:
        return json.loads(STATE.read_text(encoding="utf-8"))
    priv, pub = _generate_keypair()
    state = {
        "auth_private_key": priv,
        "auth_public_key": pub,
        "oidc_session_secret": secrets.token_urlsafe(48),
        "postgres_password": secrets.token_urlsafe(18),
        "oidc_client_id": secrets.token_urlsafe(24),
        "oidc_client_secret": secrets.token_urlsafe(48),
    }
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"[ci_stack] generated fresh secrets -> {STATE.name}")
    return state


def _resolve_gh_pat() -> str:
    """GH_PACKAGES_PAT for the private-SDK image build. Env first (CI secret),
    then the local fitness-app-backend/.env.local as a dev convenience. The value
    is never logged."""
    pat = os.environ.get("GH_PACKAGES_PAT", "").strip()
    if pat:
        return pat
    env_local = WORKSPACE / "fitness-app-backend" / ".env.local"
    if env_local.exists():
        # errors=replace: only the ASCII GH_PACKAGES_PAT= line matters; a stray
        # non-UTF-8 byte elsewhere in the file must not crash the read (Windows).
        for line in env_local.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("GH_PACKAGES_PAT="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _compose_env(state: dict) -> dict:
    env = dict(os.environ)
    env.update(
        POSTGRES_PASSWORD=state["postgres_password"],
        AUTH_PRIVATE_KEY=state["auth_private_key"],
        AUTH_PUBLIC_KEY=state["auth_public_key"],
        OIDC_SESSION_SECRET=state["oidc_session_secret"],
        E2E_OIDC_CLIENT_ID=state["oidc_client_id"],
        E2E_OIDC_CLIENT_SECRET=state["oidc_client_secret"],
        GH_PACKAGES_PAT=_resolve_gh_pat(),
    )
    return env


# ── compose helpers ──────────────────────────────────────────────────────────


def _compose(*args: str) -> list[str]:
    return ["docker", "compose", "-f", str(COMPOSE), *args]


def _run(cmd: list[str], env: dict, *, timeout: int | None = None,
         stdin=None, step: str = "") -> None:
    if step:
        print(f"\n\033[0;34m[ci_stack] {step}\033[0m", flush=True)
    result = subprocess.run(cmd, env=env, timeout=timeout, stdin=stdin)
    if result.returncode != 0:
        print(f"\033[0;31m[ci_stack] step failed ({result.returncode}): "
              f"{' '.join(cmd)}\033[0m", file=sys.stderr)
        sys.exit(result.returncode)


def cmd_up(regen: bool) -> None:
    if not COMPOSE.exists():
        sys.exit(f"[ci_stack] missing {COMPOSE}")
    state = _load_or_make_state(regen)
    env = _compose_env(state)
    if not env["GH_PACKAGES_PAT"]:
        print("\033[1;33m[ci_stack] WARNING: no GH_PACKAGES_PAT — the private-SDK "
              "image build will fail unless the layer is cached.\033[0m")

    _run(_compose("build"), env, timeout=BUILD_TIMEOUT, step="build images")
    _run(_compose("up", "-d", "--wait", "--wait-timeout", str(WAIT_TIMEOUT)),
         env, step="up + wait for healthchecks")

    _run(_compose("exec", "-T", "kdf-api", "alembic", "upgrade", "head"),
         env, step="migrate hub DB → head")
    with open(SEED, "rb") as fh:
        _run(_compose("exec", "-T",
                      "-e", f"E2E_OIDC_CLIENT_ID={state['oidc_client_id']}",
                      "-e", f"E2E_OIDC_CLIENT_SECRET={state['oidc_client_secret']}",
                      "-e", f"E2E_LOGIN_USERNAME={LOGIN_USERNAME}",
                      "-e", f"E2E_LOGIN_PASSWORD={LOGIN_PASSWORD}",
                      "-e", f"E2E_LOGIN_EMAIL={LOGIN_EMAIL}",
                      "kdf-api", "python", "-"),
             env, stdin=fh, step="seed hub: active user + OIDC client")

    _run(_compose("exec", "-T", "fitness-app-api", "alembic", "upgrade", "head"),
         env, step="migrate fitness DB → head")
    _run(_compose("exec", "-T", "fitness-app-api",
                  "python", "-m", "api.seed.fitness", "seed-foods"),
         env, step="seed fitness food catalogue")

    print(
        "\n\033[0;32m[ci_stack] stack up + seeded.\033[0m\n"
        f"  fitness FE : http://localhost:3000  (E2E_BASE_URL)\n"
        f"  hub auth-UI: http://localhost:3002  (E2E_AUTH_UI_URL)\n"
        f"  login as   : {LOGIN_USERNAME} / {LOGIN_PASSWORD}\n"
        "  run tests  : make e2e   (or: cd e2e && npm test)\n"
        "  tear down  : make e2e-ci-down\n"
    )


def _interp_env() -> dict:
    """Env for compose commands that only PARSE the file (down/logs). The
    ${VAR:?} refs must resolve or interpolation errors — use real values if a
    state file exists, else harmless placeholders (teardown ignores them)."""
    if STATE.exists():
        return _compose_env(json.loads(STATE.read_text(encoding="utf-8")))
    env = dict(os.environ)
    for var in ("POSTGRES_PASSWORD", "AUTH_PRIVATE_KEY", "AUTH_PUBLIC_KEY",
                "OIDC_SESSION_SECRET", "E2E_OIDC_CLIENT_ID", "E2E_OIDC_CLIENT_SECRET"):
        env.setdefault(var, "placeholder")
    return env


def cmd_down() -> None:
    _run(_compose("down", "-v", "--remove-orphans"), _interp_env(), step="down + clean")


def cmd_logs(service: str | None) -> None:
    tail = ["--tail", "200"]
    svc = [service] if service else []
    subprocess.run(_compose("logs", *tail, *svc), env=_interp_env())


def main() -> None:
    # Windows consoles default to cp1252; force UTF-8 so status lines never crash
    # the run on a stray non-ASCII char (the `make bump-patch` ✅ failure class).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Self-contained E2E stack driver")
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("up", help="build + up + migrate + seed")
    up.add_argument("--regen", action="store_true",
                    help="regenerate secrets (default: reuse e2e/.e2e-ci.json)")
    sub.add_parser("down", help="stop + remove containers, volumes, network")
    lg = sub.add_parser("logs", help="tail compose logs")
    lg.add_argument("service", nargs="?", help="one service, or all if omitted")
    args = parser.parse_args()

    if args.command == "up":
        cmd_up(regen=args.regen)
    elif args.command == "down":
        cmd_down()
    elif args.command == "logs":
        cmd_logs(args.service)


if __name__ == "__main__":
    main()
