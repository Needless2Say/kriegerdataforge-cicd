"""
Tests for e2e/ci_stack.py, the self-contained stack driver, and e2e/docker-compose.shared.yml.

The engine declares the deployed shape since Phase C of the auth UI review (D-016): the third state
`local`, an https issuer behind a Caddy edge under a per run authority, a mail sink the hub reaches over
STARTTLS and a login, the service key gate on, every published port on the loopback interface, and a
`--target runner` for the production image round. No Docker here, the certificates are made for real.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import ci_stack  # e2e/ is on the path, conftest.py
import pytest

ROOT = Path(__file__).resolve().parents[2]

COMPOSE = (ROOT / "e2e" / "docker-compose.shared.yml").read_text(encoding = "utf-8")
ACTION  = (ROOT / ".github" / "actions" / "run-e2e" / "action.yml").read_text(encoding = "utf-8")

# the settings the hub no longer reads, the engine carried them for months (auth UI register row 5)
DEAD_SETTINGS = (
    "AUTH_ACCESS_TOKEN_EXPIRE_MINUTES",
    "AUTH_JWT_ISSUER",
    "AUTH_JWT_AUDIENCE",
    "OIDC_REQUIRE_SESSION_SECRET",
    "MINIO_",
)


def _leaf_names(cert_pem: Path) -> str:
    """
    The subject alternative names of a certificate, as openssl prints them.
    """
    out = subprocess.run(
        ["openssl", "x509", "-in", str(cert_pem), "-noout", "-ext", "subjectAltName"],
        check = True,
        capture_output = True,
        text = True,
    ).stdout
    return " ".join(out.split())


def _ext(cert_pem: Path, name: str) -> str:
    """
    One extension of a certificate, as openssl prints it, empty when absent.
    """
    out = subprocess.run(
        ["openssl", "x509", "-in", str(cert_pem), "-noout", "-ext", name],
        capture_output = True,
        text = True,
    )
    return out.stdout


def _verify(ca: Path, leaf: Path) -> bool:
    return subprocess.run(["openssl", "verify", "-CAfile", str(ca), str(leaf)], capture_output = True).returncode == 0


# ── the certificates ─────────────────────────────────────────────────────────
@pytest.mark.skipif(shutil.which("openssl") is None, reason = "openssl CLI verifies the chain here")
@pytest.mark.parametrize("maker", ["make_certs", "_make_certs_openssl"])
def test_the_run_authority_signs_one_leaf_per_service_and_keeps_its_own_key_off_disk(tmp_path, monkeypatch, maker):
    if maker == "make_certs":
        pytest.importorskip("cryptography")
    certs = tmp_path / "certs"
    monkeypatch.setattr(ci_stack, "CERTS", certs)
    if maker == "make_certs":
        ci_stack.make_certs(regen = True)
    else:
        certs.mkdir()
        ci_stack._make_certs_openssl()

    assert sorted(p.name for p in certs.iterdir()) == sorted(ci_stack._CERT_FILES)
    assert not (certs / "ca-key.pem").exists(), "the authority's key must not survive the run"
    assert "Subject Key Identifier" in _ext(certs / "ca.pem", "subjectKeyIdentifier")
    for name, sans in ci_stack._LEAVES.items():
        assert _verify(certs / "ca.pem", certs / f"{name}.pem"), name
        # Python 3.13+ verifies in OpenSSL's strict mode and refuses a leaf without these
        assert "Authority Key Identifier" in _ext(certs / f"{name}.pem", "authorityKeyIdentifier"), name
        assert "Subject Key Identifier" in _ext(certs / f"{name}.pem", "subjectKeyIdentifier"), name
        printed = _leaf_names(certs / f"{name}.pem")
        for san in sans:
            assert san.replace("::1", "0:0:0:0:0:0:0:1") in printed, (name, san, printed)


def test_make_certs_reuses_a_complete_set_and_regenerates_a_partial_one(tmp_path, monkeypatch):
    pytest.importorskip("cryptography")
    certs = tmp_path / "certs"
    monkeypatch.setattr(ci_stack, "CERTS", certs)
    ci_stack.make_certs(regen = False)
    first = (certs / "ca.pem").read_bytes()

    ci_stack.make_certs(regen = False)
    assert (certs / "ca.pem").read_bytes() == first, "a complete set is reused, like the keypair"

    (certs / "mail.pem").unlink()
    ci_stack.make_certs(regen = False)
    assert (certs / "mail.pem").exists()
    assert (certs / "ca.pem").read_bytes() != first, "a missing file regenerates the whole set"


# ── the environment the compose reads ────────────────────────────────────────
def test_every_required_compose_variable_is_set_by_the_driver_and_by_the_parse_only_env(monkeypatch):
    monkeypatch.setattr(ci_stack, "_resolve_gh_pat", lambda: "pat")
    monkeypatch.setattr(ci_stack, "_resolve_gh_npm_token", lambda: "npm")
    state    = {"shared": {key: "v" for key in ("auth_private_key", "auth_public_key", *ci_stack._SHARED_RANDOMS)}}
    required = set(re.findall(r"\$\{([A-Z0-9_]+):\?", COMPOSE))
    assert required, "the compose declares its required variables with :?"

    env = ci_stack._base_env(state)
    assert required <= set(env), required - set(env)
    parse_only = ci_stack._interp_env({})
    assert required <= set(parse_only), required - set(parse_only)


def test_the_runner_target_puts_the_hub_behind_its_edge_and_the_dev_target_does_not():
    dev    = ci_stack._target_env("dev")
    runner = ci_stack._target_env("runner")
    assert (dev["E2E_IMAGE_TARGET"], dev["E2E_NODE_ENV"], dev["E2E_HUB_INTERNAL_URL"], dev["COMPOSE_PROFILES"]) == (
        "dev",
        "development",
        "http://kdf-api:8000",
        "",
    )
    assert (runner["E2E_IMAGE_TARGET"], runner["E2E_NODE_ENV"], runner["COMPOSE_PROFILES"]) == (
        "runner",
        "production",
        "runner",
    )
    assert runner["E2E_HUB_INTERNAL_URL"].startswith("https://kdf-api-tls:")
    assert "kdf-api-tls" in ci_stack._LEAVES["hub"], "the hub edge's certificate names the service"


def test_the_browser_facing_url_is_https_on_the_edge_port(monkeypatch):
    assert ci_stack.AUTH_UI_URL == f"https://localhost:{ci_stack.EDGE_PORT}"
    assert ci_stack.MAIL_API_URL == f"http://localhost:{ci_stack.MAIL_PORT}"


# ── the staging ───────────────────────────────────────────────────────────────
def test_a_journey_is_staged_whole_in_its_own_folder(tmp_path, monkeypatch):
    tests = tmp_path / "repo" / "e2e" / "tests"
    tests.mkdir(parents = True)
    (tests / "auth.spec.ts").write_text("import { x } from './support';\n", encoding = "utf-8")
    (tests / "flow.spec.ts").write_text("", encoding = "utf-8")
    (tests / "support.ts").write_text("export const x = 1;\n", encoding = "utf-8")
    staged = tmp_path / "staged"
    monkeypatch.setattr(ci_stack, "STAGED", staged)
    journey = ci_stack.Journey(
        name = "auth",
        app = False,
        repos = [],
        compose = None,
        tests_dir = tests,
        backend = None,
        oidc_client = {},
        env = {},
        source = "test",
    )

    assert ci_stack._stage_specs(["auth"], {"auth": journey}) == 2
    assert sorted(p.name for p in (staged / "auth").iterdir()) == ["auth.spec.ts", "flow.spec.ts", "support.ts"]


# ── the compose file itself ───────────────────────────────────────────────────
def test_every_published_port_binds_the_loopback_interface_alone():
    published = re.findall(r'^\s+- "([^"]+)"\s*(?:#.*)?$', COMPOSE, flags = re.MULTILINE)
    ports     = [p for p in published if re.search(r":\d+$", p) and ("->" in p or p.count(":") >= 2 or p[0].isdigit())]
    ports     = [p for p in ports if not p.startswith("--")]
    assert ports, "the compose publishes ports"
    for port in ports:
        assert port.startswith("127.0.0.1:"), port


def test_the_stack_declares_the_deployed_shape():
    assert COMPOSE.count("ENVIRONMENT: local") == 2, "the hub and the auth UI"
    assert "development" not in re.sub(r"#.*", "", COMPOSE).replace("E2E_NODE_ENV:-development", "")
    assert "OIDC_ISSUER: https://localhost:${E2E_EDGE_PORT:-3002}" in COMPOSE
    assert "FORWARDED_CLIENT_IP_HEADER: kdf-client-ip" in COMPOSE
    assert "SERVICE_API_KEYS: auth-ui=${AUTH_UI_SERVICE_KEY:?" in COMPOSE
    assert "KDF_SERVICE_KEY: ${AUTH_UI_SERVICE_KEY:?" in COMPOSE
    assert "SSL_CERT_FILE: /certs/ca.pem" in COMPOSE
    for dead in DEAD_SETTINGS:
        assert dead not in COMPOSE, dead


def test_the_sink_requires_starttls_under_the_run_certificate_and_is_pinned():
    assert "--smtp-require-starttls" in COMPOSE
    assert "--smtp-tls-cert=/certs/mail.pem" in COMPOSE
    assert "--smtp-auth-accept-any" in COMPOSE
    for image in re.findall(r"image: (\S+)", COMPOSE):
        assert ":" in image and not image.endswith(":latest"), image


# ── the action ────────────────────────────────────────────────────────────────
def test_the_action_reads_the_journey_and_the_token_reach_from_the_right_manifests():
    assert "manifest.json?ref=${DEFAULT}" in ACTION, "the token's reach comes from the default branch"
    assert "JOURNEY=$(jq -r '.journey // empty' \"$MF\")" in ACTION, "the journey comes from the caller's manifest"
    assert 'JOURNEY: ${{ steps.resolve.outputs.journey }}' in ACTION
    assert "git ls-remote --exit-code --heads" in ACTION, "a sibling at the caller's branch name when it has one"
    assert ACTION.count("persist-credentials: false") == 1, "cicd's checkout keeps no credential"
    assert "jq -S '{about, answers}'" in ACTION, "the two copies of the hub contract are held to each other"
    journey_input = ACTION.split("inputs:\n  journey:\n", 1)[1].split("\n  sibling-ref:\n", 1)[0]
    assert "required: false" in journey_input, journey_input


def test_the_action_head_is_literal_text():
    # an expression written into an input's description is evaluated at load too, and a composite action has
    #  no `secrets` context, so the hub's E2E dispatch of 2026-09-25 failed to load the action on two descriptions
    head = ACTION.split("\nruns:", 1)[0]
    assert "${{" not in head, "nothing above runs: is an expression"
    assert "secrets." not in ACTION, "a composite action reads no secret, the caller passes them as inputs"
