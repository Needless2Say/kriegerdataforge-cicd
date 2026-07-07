#!/usr/bin/env python3
"""Driver for the self-contained Tier-2 E2E stack (docker-compose.e2e.yml).

One entry point for both `make e2e-ci*` locally and the CI workflow. It owns the
parts a bare `docker compose up` can't do:

  * generates a throwaway RS256 keypair + fixed-per-run OIDC client_id/secret PER
    TENANT + session secret + DB password, and threads them into the compose via
    the process env (so the hub, each frontend, and the seed all agree — no
    capture-and-inject). Secrets persist to e2e/.e2e-ci.json (gitignored) so
    re-running `up` reuses them instead of churning containers; `--regen` forces
    a fresh set.
  * sources GH_PACKAGES_PAT (env → fitness-app-backend/.env.local fallback) so
    the private-SDK image build works locally without exporting it by hand. In
    CI it comes from the GH_PACKAGES_PAT secret. Never printed.
  * builds, brings the selected TENANTS up (via compose profiles) with healthcheck
    gating, migrates the hub + each tenant DB, and seeds the active login user +
    each tenant's OIDC client (hub) and catalogue, in the one correct order.

The stack is TWO tenants sharing the hub + auth-UI: `fitness` (FE :3000, BE :8001)
and `tiffanys` (FE :3001, BE :8002), tagged with docker-compose profiles. `up
--tenants fitness` brings up only the fitness tenant (+ shared hub/auth-UI), so a
single-tenant gate doesn't build the other tenant's images.

Commands:
  up      build + up --wait + migrate + seed        (idempotent; leaves it up)
  down    stop + remove containers, volumes, network (all tenants)
  logs    tail compose logs (debug)

Then run Playwright (`make e2e` / `cd e2e && npm test`).

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

# Per-tenant wiring. `client_id/secret` are the .e2e-ci.json state keys; the *_env
# are the env names seed_e2e.py + the compose read; `service` is the BE container
# to migrate/seed; `url` is the browser entry point.
TENANTS = {
    "fitness": {
        "service": "fitness-app-api",
        "seed": ("python", "-m", "api.seed.fitness", "seed-foods"),
        "seed_label": "seed fitness food catalogue",
        "id_key": "oidc_client_id",
        "secret_key": "oidc_client_secret",
        "id_env": "E2E_OIDC_CLIENT_ID",
        "secret_env": "E2E_OIDC_CLIENT_SECRET",
        "url": "http://localhost:3000",
    },
    "tiffanys": {
        "service": "tiffanys-space-api",
        "seed": ("python", "-m", "api.seed.tiffanys", "seed-products"),
        "seed_label": "seed tiffanys product catalogue",
        "id_key": "tiffanys_client_id",
        "secret_key": "tiffanys_client_secret",
        "id_env": "E2E_TIFFANYS_CLIENT_ID",
        "secret_env": "E2E_TIFFANYS_CLIENT_SECRET",
        "url": "http://localhost:3001",
    },
}
ALL_TENANTS = tuple(TENANTS)

# Env-tunable so CI (slower cold `next dev` compiles, image builds) can grant
# headroom without editing the driver. Defaults suit local runs.
BUILD_TIMEOUT = int(os.environ.get("E2E_BUILD_TIMEOUT", "1800"))  # cold build: SDK clone + npm ci
WAIT_TIMEOUT = int(os.environ.get("E2E_WAIT_TIMEOUT", "420"))  # healthcheck gate; next dev compiles on first hit


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
    """Load e2e/.e2e-ci.json, filling any missing keys (so an older state file
    gains the tenant client creds without a --regen). Rewrites only if changed."""
    state = {} if (regen or not STATE.exists()) else json.loads(STATE.read_text(encoding="utf-8"))
    changed = False
    if not state.get("auth_private_key") or not state.get("auth_public_key"):
        state["auth_private_key"], state["auth_public_key"] = _generate_keypair()
        changed = True
    randoms = {
        "oidc_session_secret": 48,
        "postgres_password": 18,
        "oidc_client_id": 24,
        "oidc_client_secret": 48,
        "tiffanys_client_id": 24,
        "tiffanys_client_secret": 48,
    }
    for key, nbytes in randoms.items():
        if not state.get(key):
            state[key] = secrets.token_urlsafe(nbytes)
            changed = True
    if changed:
        STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        print(f"[ci_stack] wrote secrets -> {STATE.name}")
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


def _compose_env(state: dict, profiles: tuple[str, ...] = ALL_TENANTS) -> dict:
    env = dict(os.environ)
    env.update(
        COMPOSE_PROFILES=",".join(profiles),
        POSTGRES_PASSWORD=state["postgres_password"],
        AUTH_PRIVATE_KEY=state["auth_private_key"],
        AUTH_PUBLIC_KEY=state["auth_public_key"],
        OIDC_SESSION_SECRET=state["oidc_session_secret"],
        E2E_OIDC_CLIENT_ID=state["oidc_client_id"],
        E2E_OIDC_CLIENT_SECRET=state["oidc_client_secret"],
        E2E_TIFFANYS_CLIENT_ID=state["tiffanys_client_id"],
        E2E_TIFFANYS_CLIENT_SECRET=state["tiffanys_client_secret"],
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


def cmd_up(tenants: tuple[str, ...], regen: bool) -> None:
    if not COMPOSE.exists():
        sys.exit(f"[ci_stack] missing {COMPOSE}")
    state = _load_or_make_state(regen)
    env = _compose_env(state, profiles=tenants)
    if not env["GH_PACKAGES_PAT"]:
        print("\033[1;33m[ci_stack] WARNING: no GH_PACKAGES_PAT — the private-SDK "
              "image build will fail unless the layer is cached.\033[0m")
    print(f"[ci_stack] tenants: {', '.join(tenants)}")

    _run(_compose("build"), env, timeout=BUILD_TIMEOUT, step="build images")
    _run(_compose("up", "-d", "--wait", "--wait-timeout", str(WAIT_TIMEOUT)),
         env, step="up + wait for healthchecks")

    # Hub: migrate, then seed the login user + the OIDC client of EACH active
    # tenant (seed_e2e.py inserts a client only for the creds it's handed).
    _run(_compose("exec", "-T", "kdf-api", "alembic", "upgrade", "head"),
         env, step="migrate hub DB → head")
    seed_flags = [
        "-e", f"E2E_LOGIN_USERNAME={LOGIN_USERNAME}",
        "-e", f"E2E_LOGIN_PASSWORD={LOGIN_PASSWORD}",
        "-e", f"E2E_LOGIN_EMAIL={LOGIN_EMAIL}",
    ]
    for t in tenants:
        cfg = TENANTS[t]
        seed_flags += [
            "-e", f"{cfg['id_env']}={state[cfg['id_key']]}",
            "-e", f"{cfg['secret_env']}={state[cfg['secret_key']]}",
        ]
    with open(SEED, "rb") as fh:
        _run(_compose("exec", "-T", *seed_flags, "kdf-api", "python", "-"),
             env, stdin=fh, step="seed hub: active user + OIDC client(s)")

    # Each tenant: migrate its DB + seed its catalogue.
    for t in tenants:
        cfg = TENANTS[t]
        _run(_compose("exec", "-T", cfg["service"], "alembic", "upgrade", "head"),
             env, step=f"migrate {t} DB → head")
        _run(_compose("exec", "-T", cfg["service"], *cfg["seed"]),
             env, step=cfg["seed_label"])

    urls = "\n".join(f"  {t:8} FE: {TENANTS[t]['url']}" for t in tenants)
    print(
        "\n\033[0;32m[ci_stack] stack up + seeded.\033[0m\n"
        f"{urls}\n"
        f"  hub auth-UI: http://localhost:3002  (E2E_AUTH_UI_URL)\n"
        f"  login as   : {LOGIN_USERNAME} / {LOGIN_PASSWORD}\n"
        "  run tests  : make e2e   (or: cd e2e && npm test)\n"
        "  tear down  : make e2e-ci-down\n"
    )


def _interp_env() -> dict:
    """Env for compose commands that only PARSE the file (down/logs) across ALL
    profiles. The ${VAR:?} refs must resolve or interpolation errors — use real
    values if a state file exists, else harmless placeholders."""
    if STATE.exists():
        # Backfill any keys an older state file lacks (e.g. the tenant client
        # creds) so _compose_env never KeyErrors on down/logs.
        return _compose_env(_load_or_make_state(regen=False))
    env = dict(os.environ, COMPOSE_PROFILES=",".join(ALL_TENANTS))
    for var in ("POSTGRES_PASSWORD", "AUTH_PRIVATE_KEY", "AUTH_PUBLIC_KEY",
                "OIDC_SESSION_SECRET", "E2E_OIDC_CLIENT_ID", "E2E_OIDC_CLIENT_SECRET",
                "E2E_TIFFANYS_CLIENT_ID", "E2E_TIFFANYS_CLIENT_SECRET"):
        env.setdefault(var, "placeholder")
    return env


def cmd_down() -> None:
    _run(_compose("down", "-v", "--remove-orphans"), _interp_env(), step="down + clean")


def cmd_logs(service: str | None) -> None:
    tail = ["--tail", "200"]
    svc = [service] if service else []
    subprocess.run(_compose("logs", *tail, *svc), env=_interp_env())


def _parse_tenants(raw: str) -> tuple[str, ...]:
    tenants = tuple(t.strip() for t in raw.split(",") if t.strip())
    bad = [t for t in tenants if t not in TENANTS]
    if bad:
        sys.exit(f"[ci_stack] unknown tenant(s): {', '.join(bad)} (valid: {', '.join(ALL_TENANTS)})")
    return tenants or ALL_TENANTS


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
    up.add_argument("--tenants", default=",".join(ALL_TENANTS),
                    help=f"comma-separated tenants to bring up (default: {','.join(ALL_TENANTS)})")
    up.add_argument("--regen", action="store_true",
                    help="regenerate secrets (default: reuse e2e/.e2e-ci.json)")
    sub.add_parser("down", help="stop + remove containers, volumes, network")
    lg = sub.add_parser("logs", help="tail compose logs")
    lg.add_argument("service", nargs="?", help="one service, or all if omitted")
    args = parser.parse_args()

    if args.command == "up":
        cmd_up(tenants=_parse_tenants(args.tenants), regen=args.regen)
    elif args.command == "down":
        cmd_down()
    elif args.command == "logs":
        cmd_logs(args.service)


if __name__ == "__main__":
    main()
