#!/usr/bin/env python3
"""Driver for the self-contained Tier-2 E2E stack — DATA-DRIVEN, tenant-agnostic.

One entry point for both `make e2e-ci*` locally and the CI workflow. It owns the
parts a bare `docker compose up` can't do, and it is **discovery-based**: it never
hardcodes a tenant list. Each journey is declared by an `e2e/manifest.json` that
the driver finds in a sibling repo (the Phase-2 home) or in `e2e/tenants/<j>/`
(the Phase-1 transitional home) — see ADR D-006 + docs/design/e2e-test-decoupling.md.
Onboarding a journey adds a manifest in ITS repo; this file never changes.

What it does:
  * generates a throwaway RS256 keypair + session secret + DB password (shared),
    plus a fixed-per-run OIDC client_id/secret PER ACTIVE JOURNEY, threaded into
    the compose via the process env so the hub, each frontend, and the seed all
    agree. Persisted to e2e/.e2e-ci.json (gitignored); `--regen` forces fresh.
  * sources GH_PACKAGES_PAT (env → fitness-app-backend/.env.local fallback) for
    the private-SDK image build. Never printed.
  * merges the shared identity compose (docker-compose.shared.yml) with each
    active journey's fragment (`-f shared -f <fragment>`), brings them up with
    healthcheck gating, migrates the hub + each journey's backend, seeds the
    active login user + one OIDC client per journey.
  * STAGES the active journeys' Playwright specs into e2e/staged-tests/ (the
    testDir) and writes e2e/.env so `npm test` runs exactly those specs — no
    `--grep` plumbing needed.

Commands:
  up      build + up --wait + migrate + seed + stage specs   (idempotent)
  stage   only stage specs + write .env (no docker)           (for the delegated stack)
  down    stop + remove containers, volumes, network          (all journeys)
  logs    tail compose logs                                    (debug)

Generated keys are ephemeral and never touch a developer's real dev keypair.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent.parent  # e2e/ → cicd repo → workspace root (siblings)
SHARED_COMPOSE = HERE / "docker-compose.shared.yml"
LOCAL_TENANTS = HERE / "tenants"     # Phase-1 transitional journey homes
SEED = HERE / "seed_shared.py"
STAGED = HERE / "staged-tests"       # gitignored Playwright testDir (populated per run)
STATE = HERE / ".e2e-ci.json"        # gitignored — persisted per-run secrets
ENV_FILE = HERE / ".env"             # gitignored — loaded by playwright.config.ts

# Fixed login creds: match e2e/.env.example + Playwright's E2E_* defaults so the
# suite needs no wiring. Not sensitive (throwaway account in an ephemeral DB).
LOGIN_USERNAME = "e2e-user"
LOGIN_PASSWORD = "E2eTest123!"
LOGIN_EMAIL = "e2e-user@example.com"
AUTH_UI_URL = "http://localhost:3002"

# Env-tunable so CI (slower cold `next dev` compiles, image builds) can grant
# headroom without editing the driver. Defaults suit local runs.
BUILD_TIMEOUT = int(os.environ.get("E2E_BUILD_TIMEOUT", "1800"))  # cold: SDK clone + npm ci
WAIT_TIMEOUT = int(os.environ.get("E2E_WAIT_TIMEOUT", "420"))  # healthcheck gate

# Shared secrets (not per-journey) + their byte sizes for token_urlsafe.
_SHARED_RANDOMS = {"oidc_session_secret": 48, "postgres_password": 18}


# ── journey registry (discovered from manifests) ─────────────────────────────


@dataclass
class Journey:
    name: str
    app: bool                     # part of `journey: all`? (auth is opt-in → False)
    repos: list[str]              # sibling repos this journey's fragment builds from
    compose: Path | None          # tenant compose fragment (None → shared only)
    tests_dir: Path               # dir whose *.spec.ts are staged
    backend: dict | None          # {service, migrate, seed} or None
    oidc_client: dict             # {id_env, secret_env, redirect_uri, name}
    env: dict = field(default_factory=dict)  # extra E2E_* to write to .env
    source: str = "local"         # "sibling" | "local"


def _load_manifest(path: Path, source: str) -> Journey:
    data = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    compose = (base / data["compose"]).resolve() if data.get("compose") else None
    return Journey(
        name=data["journey"],
        app=data.get("app", True),
        repos=data.get("repos", []),
        compose=compose,
        tests_dir=(base / data.get("tests", "tests")).resolve(),
        backend=data.get("backend"),
        oidc_client=data["oidc_client"],
        env=data.get("env", {}),
        source=source,
    )


def discover() -> dict[str, Journey]:
    """Build the journey registry. Sibling-repo manifests (Phase-2 homes) take
    precedence over the cicd-local transitional ones, so a moved journey is
    picked up from its repo with no cicd change."""
    registry: dict[str, Journey] = {}
    # 1. cicd-local transitional homes (lower precedence).
    if LOCAL_TENANTS.is_dir():
        for mf in sorted(LOCAL_TENANTS.glob("*/manifest.json")):
            j = _load_manifest(mf, "local")
            registry[j.name] = j
    # 2. sibling repos (higher precedence — the Phase-2 homes win on collision).
    for mf in sorted(WORKSPACE.glob("*/e2e/manifest.json")):
        if mf.parent == HERE:  # never treat cicd/e2e itself as a tenant
            continue
        j = _load_manifest(mf, "sibling")
        registry[j.name] = j
    return registry


def resolve_journeys(raw: str, registry: dict[str, Journey]) -> list[str]:
    if raw in ("", "all"):
        return sorted(n for n, j in registry.items() if j.app)
    names = [t.strip() for t in raw.split(",") if t.strip()]
    bad = [n for n in names if n not in registry]
    if bad:
        sys.exit(f"[ci_stack] unknown journey(s): {', '.join(bad)} "
                 f"(discovered: {', '.join(sorted(registry)) or 'none'})")
    return names


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


def load_or_make_state(journeys: list[str], regen: bool) -> dict:
    """Load e2e/.e2e-ci.json, filling any missing keys (shared secrets + a client
    id/secret for each requested journey). An OLD flat-schema file (pre-D-006) is
    discarded and regenerated — the creds are throwaway. Rewrites only if changed."""
    state: dict = {}
    if not regen and STATE.exists():
        try:
            loaded = json.loads(STATE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            loaded = {}  # corrupt/truncated (e.g. an interrupted write) → regenerate
        if isinstance(loaded, dict) and "shared" in loaded:  # new schema; else regen
            state = loaded
    state.setdefault("shared", {})
    state.setdefault("clients", {})
    changed = False

    sh = state["shared"]
    if not sh.get("auth_private_key") or not sh.get("auth_public_key"):
        sh["auth_private_key"], sh["auth_public_key"] = _generate_keypair()
        changed = True
    for key, nbytes in _SHARED_RANDOMS.items():
        if not sh.get(key):
            sh[key] = secrets.token_urlsafe(nbytes)
            changed = True

    for j in journeys:
        if j not in state["clients"]:
            state["clients"][j] = {
                "id": secrets.token_urlsafe(24),
                "secret": secrets.token_urlsafe(48),
            }
            changed = True

    if changed:
        STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        print(f"[ci_stack] wrote secrets -> {STATE.name}")
    return state


def _resolve_gh_pat() -> str:
    """GH_PACKAGES_PAT for the private-SDK image build. Env first (CI secret),
    then the local fitness-app-backend/.env.local as a dev convenience. Never logged."""
    pat = os.environ.get("GH_PACKAGES_PAT", "").strip()
    if pat:
        return pat
    env_local = WORKSPACE / "fitness-app-backend" / ".env.local"
    if env_local.exists():
        # errors=replace: only the ASCII GH_PACKAGES_PAT= line matters; a stray
        # non-UTF-8 byte elsewhere must not crash the read (Windows).
        for line in env_local.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("GH_PACKAGES_PAT="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _base_env(state: dict) -> dict:
    """Env common to every compose invocation: workspace root (for the absolute
    ${E2E_WORKSPACE} build contexts) + the shared identity secrets + the PAT."""
    sh = state["shared"]
    env = dict(os.environ)
    env.update(
        E2E_WORKSPACE=WORKSPACE.as_posix(),  # forward slashes — Docker-friendly on Windows
        POSTGRES_PASSWORD=sh["postgres_password"],
        AUTH_PRIVATE_KEY=sh["auth_private_key"],
        AUTH_PUBLIC_KEY=sh["auth_public_key"],
        OIDC_SESSION_SECRET=sh["oidc_session_secret"],
        GH_PACKAGES_PAT=_resolve_gh_pat(),
    )
    return env


def _compose_env(state: dict, journeys: list[str], registry: dict[str, Journey]) -> dict:
    """Base env + each active journey's client id/secret under the var names its
    fragment/spec expect (manifest oidc_client.id_env / secret_env)."""
    env = _base_env(state)
    for j in journeys:
        oc = registry[j].oidc_client
        env[oc["id_env"]] = state["clients"][j]["id"]
        env[oc["secret_env"]] = state["clients"][j]["secret"]
    return env


# ── compose helpers ──────────────────────────────────────────────────────────


def _compose_files(journeys: list[str], registry: dict[str, Journey]) -> list[str]:
    files = ["-f", str(SHARED_COMPOSE)]
    for j in journeys:
        frag = registry[j].compose
        if frag:
            files += ["-f", str(frag)]
    return files


def _compose(files: list[str], *args: str) -> list[str]:
    return ["docker", "compose", *files, *args]


def _run(cmd: list[str], env: dict, *, timeout: int | None = None,
         stdin=None, step: str = "") -> None:
    if step:
        print(f"\n\033[0;34m[ci_stack] {step}\033[0m", flush=True)
    result = subprocess.run(cmd, env=env, timeout=timeout, stdin=stdin)
    if result.returncode != 0:
        print(f"\033[0;31m[ci_stack] step failed ({result.returncode}): "
              f"{' '.join(cmd)}\033[0m", file=sys.stderr)
        sys.exit(result.returncode)


def _stage_specs(journeys: list[str], registry: dict[str, Journey]) -> int:
    """Copy the active journeys' *.spec.ts into e2e/staged-tests/ (the testDir).
    Journey-prefixed to avoid name collisions across tenants. Cleared each run.
    Returns the number of spec files staged (0 → the caller should fail loudly,
    else `npm test` dies later with a confusing Playwright 'no tests found')."""
    if STAGED.exists():
        shutil.rmtree(STAGED)
    STAGED.mkdir(parents=True)
    total = 0
    for j in journeys:
        tests_dir = registry[j].tests_dir
        if not tests_dir.is_dir():
            print(f"\033[1;33m[ci_stack] WARNING: {j} tests dir not found: {tests_dir}\033[0m")
            continue
        specs = sorted(tests_dir.glob("*.spec.ts"))
        if not specs:
            print(f"\033[1;33m[ci_stack] WARNING: {j} has no *.spec.ts in {tests_dir}\033[0m")
        for spec in specs:
            shutil.copy2(spec, STAGED / f"{j}-{spec.name}")
            total += 1
    print(f"[ci_stack] staged {total} spec file(s) for: {', '.join(journeys)}")
    return total


def _write_env_file(state: dict, journeys: list[str], registry: dict[str, Journey]) -> None:
    """Write e2e/.env (gitignored) so `npm test` picks up the login creds + each
    journey's URLs + its generated client id/secret (playwright.config.ts loads it)."""
    lines = [
        "# Generated by ci_stack.py for the self-contained stack — gitignored.",
        "# Loaded by playwright.config.ts via process.loadEnvFile().",
        f"E2E_USERNAME={LOGIN_USERNAME}",
        f"E2E_PASSWORD={LOGIN_PASSWORD}",
        f"E2E_AUTH_UI_URL={AUTH_UI_URL}",
    ]
    for j in journeys:
        d = registry[j]
        oc = d.oidc_client
        lines.append(f"{oc['id_env']}={state['clients'][j]['id']}")
        # Also expose the generated client SECRET. A journey whose spec performs the
        # OIDC code->token exchange ITSELF — the backend/hub API journeys (ADR D-008),
        # which have no frontend BFF to do it — needs the secret to authenticate at
        # the token endpoint (the seeded clients are confidential/client_secret_basic).
        # The browser-app journeys simply don't read it. It's an ephemeral per-run
        # secret for a throwaway client in a disposable DB, and e2e/.env is gitignored.
        lines.append(f"{oc['secret_env']}={state['clients'][j]['secret']}")
        for k, v in d.env.items():
            lines.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[ci_stack] wrote {ENV_FILE.name} for: {', '.join(journeys)}")


def _check_repos(journeys: list[str], registry: dict[str, Journey]) -> None:
    """Friendly pre-flight: warn if a journey's build-context repos aren't checked
    out as siblings (the ${E2E_WORKSPACE}/<repo> contexts would fail to build)."""
    missing = set()
    for j in journeys:
        for repo in registry[j].repos:
            if not (WORKSPACE / repo).is_dir():
                missing.add(repo)
    if missing:
        print(f"\033[1;33m[ci_stack] WARNING: sibling repo(s) not found under "
              f"{WORKSPACE}: {', '.join(sorted(missing))} — their image builds will "
              f"fail. Check them out next to kriegerdataforge-cicd.\033[0m")


# ── commands ─────────────────────────────────────────────────────────────────


def cmd_up(raw_journeys: str, regen: bool) -> None:
    if not SHARED_COMPOSE.exists():
        sys.exit(f"[ci_stack] missing {SHARED_COMPOSE}")
    registry = discover()
    journeys = resolve_journeys(raw_journeys, registry)
    if not journeys:
        sys.exit("[ci_stack] no journeys resolved (no manifests discovered?)")
    _check_repos(journeys, registry)
    state = load_or_make_state(journeys, regen)
    env = _compose_env(state, journeys, registry)
    files = _compose_files(journeys, registry)
    if not env["GH_PACKAGES_PAT"]:
        print("\033[1;33m[ci_stack] WARNING: no GH_PACKAGES_PAT — the private-SDK "
              "image build will fail unless the layer is cached.\033[0m")
    print(f"[ci_stack] journeys: {', '.join(journeys)}")

    _run(_compose(files, "build"), env, timeout=BUILD_TIMEOUT, step="build images")
    _run(_compose(files, "up", "-d", "--wait", "--wait-timeout", str(WAIT_TIMEOUT)),
         env, step="up + wait for healthchecks")

    # Hub: migrate, then seed the login user + one OIDC client per active journey.
    _run(_compose(files, "exec", "-T", "kdf-api", "alembic", "upgrade", "head"),
         env, step="migrate hub DB → head")
    seed_clients = [
        {
            "client_id": state["clients"][j]["id"],
            "client_secret": state["clients"][j]["secret"],
            "redirect": registry[j].oidc_client["redirect_uri"],
            "name": registry[j].oidc_client["name"],
        }
        for j in journeys
    ]
    # Pass the seed inputs via the ENVIRONMENT (bare `-e NAME`, which docker reads
    # from this process's env), NOT `-e NAME=value` — so the generated client
    # secrets never land in argv. _run() echoes the command on failure, and this
    # runtime-generated secret is NOT a registered Actions secret (unmasked), so a
    # value in argv would leak to the CI log (SEC-1). Keeping it in the env is safe:
    # _run prints the command, never the environment.
    seed_env = dict(env)
    seed_env.update(
        E2E_LOGIN_USERNAME=LOGIN_USERNAME,
        E2E_LOGIN_PASSWORD=LOGIN_PASSWORD,
        E2E_LOGIN_EMAIL=LOGIN_EMAIL,
        E2E_SEED_CLIENTS=json.dumps(seed_clients),
    )
    seed_flags = ["-e", "E2E_LOGIN_USERNAME", "-e", "E2E_LOGIN_PASSWORD",
                  "-e", "E2E_LOGIN_EMAIL", "-e", "E2E_SEED_CLIENTS"]
    with open(SEED, "rb") as fh:
        _run(_compose(files, "exec", "-T", *seed_flags, "kdf-api", "python", "-"),
             seed_env, stdin=fh, step="seed hub: active user + OIDC client(s)")

    # Each app journey's backend: migrate its DB + seed its catalogue.
    for j in journeys:
        be = registry[j].backend
        if not be:
            continue
        if be.get("migrate"):
            _run(_compose(files, "exec", "-T", be["service"], "alembic", "upgrade", "head"),
                 env, step=f"migrate {j} DB → head")
        if be.get("seed"):
            _run(_compose(files, "exec", "-T", be["service"], *be["seed"]),
                 env, step=f"seed {j} catalogue")

    if _stage_specs(journeys, registry) == 0:
        sys.exit(f"[ci_stack] no spec files staged for: {', '.join(journeys)} — "
                 f"check each journey manifest's 'tests' dir")
    _write_env_file(state, journeys, registry)

    print(
        "\n\033[0;32m[ci_stack] stack up + seeded.\033[0m\n"
        f"  journeys   : {', '.join(journeys)}\n"
        f"  hub auth-UI: {AUTH_UI_URL}  (E2E_AUTH_UI_URL)\n"
        f"  login as   : {LOGIN_USERNAME} / {LOGIN_PASSWORD}\n"
        "  run tests  : make e2e   (or: cd e2e && npm test)\n"
        "  tear down  : make e2e-ci-down\n"
    )


def cmd_stage(raw_journeys: str, all_journeys: bool = False) -> None:
    """Stage specs only (no docker, no state, no .env write). Two uses:
      * the delegated local stack (`make e2e-up` + `make e2e`) stages ONE journey
        to run it (E2E_* come from the Makefile / the dev's own e2e/.env);
      * `make e2e-typecheck` stages EVERY discovered journey (--all, app + non-app)
        so tsc can type-check all the tenant specs the engine runs.
    --all tolerates an empty set (a bare cicd checkout with no sibling journeys is
    fine — tsc then just checks playwright.config.ts); an explicit --journey does not."""
    registry = discover()
    journeys = sorted(registry) if all_journeys else resolve_journeys(raw_journeys, registry)
    if _stage_specs(journeys, registry) == 0 and not all_journeys:
        sys.exit(f"[ci_stack] no spec files staged for: {', '.join(journeys)}")


def _interp_env(registry: dict[str, Journey]) -> dict:
    """Env for compose commands that only PARSE the merged files (down/logs) across
    ALL discovered journeys. Every ${VAR:?} ref must resolve or interpolation errors;
    the values are never used to build/run, so harmless placeholders suffice — and
    we never generate/persist secrets just to tear down."""
    env = dict(os.environ)
    env["E2E_WORKSPACE"] = WORKSPACE.as_posix()
    for var in ("POSTGRES_PASSWORD", "AUTH_PRIVATE_KEY", "AUTH_PUBLIC_KEY",
                "OIDC_SESSION_SECRET", "GH_PACKAGES_PAT"):
        env.setdefault(var, "placeholder")
    for j in registry.values():
        env.setdefault(j.oidc_client["id_env"], "placeholder")
        env.setdefault(j.oidc_client["secret_env"], "placeholder")
    return env


def cmd_down() -> None:
    registry = discover()
    files = _compose_files(sorted(registry), registry)
    _run(_compose(files, "down", "-v", "--remove-orphans"),
         _interp_env(registry), step="down + clean")


def cmd_logs(service: str | None) -> None:
    registry = discover()
    files = _compose_files(sorted(registry), registry)
    tail = ["--tail", "200"]
    svc = [service] if service else []
    subprocess.run(_compose(files, "logs", *tail, *svc), env=_interp_env(registry))


def main() -> None:
    # Windows consoles default to cp1252; force UTF-8 so status lines never crash
    # the run on a stray non-ASCII char (the `make bump-patch` ✅ failure class).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Self-contained E2E stack driver (data-driven)")
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("up", help="build + up + migrate + seed + stage specs")
    up.add_argument("--journey", default="all",
                    help="comma-separated journeys to bring up, or 'all' (app journeys). "
                         "Discovered from e2e/manifest.json files.")
    up.add_argument("--regen", action="store_true",
                    help="regenerate secrets (default: reuse e2e/.e2e-ci.json)")
    st = sub.add_parser("stage", help="stage specs only (no docker)")
    st.add_argument("--journey", default="all", help="journeys to stage, or 'all' (app journeys)")
    st.add_argument("--all", action="store_true",
                    help="stage EVERY discovered journey (app + non-app) — for typecheck")
    sub.add_parser("down", help="stop + remove containers, volumes, network")
    lg = sub.add_parser("logs", help="tail compose logs")
    lg.add_argument("service", nargs="?", help="one service, or all if omitted")
    args = parser.parse_args()

    if args.command == "up":
        cmd_up(args.journey, args.regen)
    elif args.command == "stage":
        cmd_stage(args.journey, args.all)
    elif args.command == "down":
        cmd_down()
    elif args.command == "logs":
        cmd_logs(args.service)


if __name__ == "__main__":
    main()
