"""
The rules fire, design 5.9's first part. A deliberately vulnerable file for each rule family the policy of 5.6 keeps,
written fresh for cicd and never copied from the test files of Semgrep's licensed rules, each expected result naming a
rule id alone, row L25. Then the policy itself on the real rules, a Python LOW finding and the replaced logger rule
dropped, a TypeScript LOW one kept, and the two tooling rules dropped under scripts/ and kept under src/. Last, KDF's
own rule against its test cases in Opengrep's test form, each line under a ruleid comment matched and none under an ok
comment, read by a plain scan with the wrapper's own flags, plan step 2.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from scanfix import installed, lines, make_repo, pin, scan

SECRET = '"a-fixture-secret"'
# each family's file, its fresh vulnerable lines, and the rule ids that must fail there
FAMILIES   = {
    "python/lang": (
        "src/run_command.py",
        lines("import subprocess", "", "", "def run(command):", "    return subprocess.run(command, shell=True)"),
        {"subprocess-shell-true"},
    ),
    "python/lang md5": (
        "src/digest.py",
        lines("import hashlib", "", "", "def fingerprint(data):", "    return hashlib.md5(data).hexdigest()"),
        {"insecure-hash-algorithm-md5"},
    ),
    "python/lang yaml": (
        "src/config_load.py",
        lines("import yaml", "", "", "def load(text):", "    return yaml.unsafe_load(text)"),
        {"avoid-pyyaml-load"},
    ),
    "python/fastapi": (
        "src/app.py",
        lines(
            "from fastapi import FastAPI",
            "from fastapi.middleware.cors import CORSMiddleware",
            "",
            "app = FastAPI()",
            'app.add_middleware(CORSMiddleware, allow_origins=["*"])',
        ),
        {"wildcard-cors"},
    ),
    "python/sqlalchemy": (
        "src/query.py",
        lines(
            "import sqlalchemy",
            "",
            "",
            "def find(connection, name):",
            "    statement = sqlalchemy.text(f\"SELECT id FROM people WHERE name = '{name}'\")",
            "    return connection.execute(statement)",
        ),
        {"avoid-sqlalchemy-text"},
    ),
    "python/jwt": (
        "src/tokens.py",
        lines(
            "import jwt",
            "",
            "",
            "def issue(claims):",
            f'    return jwt.encode(claims, {SECRET}, algorithm="HS256")',
            "",
            "",
            "def read(token):",
            '    return jwt.decode(token, options={"verify_signature": False})',
        ),
        {"jwt-python-hardcoded-secret", "unverified-jwt-decode"},
    ),
    "python/cryptography": (
        "src/keys.py",
        lines(
            "from cryptography.hazmat.primitives.asymmetric import rsa",
            "",
            "",
            "def weak_key():",
            "    return rsa.generate_private_key(public_exponent=65537, key_size=1024)",
        ),
        {"insufficient-rsa-key-size"},
    ),
    "python/jinja2": (
        "src/render.py",
        lines("import jinja2", "", "", "def environment():", "    return jinja2.Environment(autoescape=False)"),
        {"incorrect-autoescape-disabled"},
    ),
    "javascript/lang": (
        "src/hmac.js",
        lines(
            'const crypto = require("crypto");',
            "",
            "function sign(body) {",
            '  return crypto.createHmac("sha256", "a-fixture-key").update(body).digest("hex");',
            "}",
            "",
            "module.exports = { sign };",
        ),
        {"hardcoded-hmac-key"},
    ),
    "javascript/node-crypto": (
        "src/cipher.js",
        lines(
            'const crypto = require("crypto");',
            "",
            "function seal(key, text) {",
            '  const cipher = crypto.createCipher("aes-256-cbc", key);',
            '  return cipher.update(text, "utf8", "hex") + cipher.final("hex");',
            "}",
            "",
            "module.exports = { seal };",
        ),
        {"create-de-cipher-no-iv"},
    ),
    "javascript/browser": (
        "src/frame.js",
        lines("function announce(data) {", '  window.parent.postMessage(data, "*");', "}", "", "export { announce };"),
        {"wildcard-postmessage-configuration"},
    ),
    "javascript/jsonwebtoken": (
        "src/session.js",
        lines(
            'const jwt = require("jsonwebtoken");',
            "",
            "function issue(claims) {",
            f"  return jwt.sign(claims, {SECRET});",
            "}",
            "",
            "module.exports = { issue };",
        ),
        {"hardcoded-jwt-secret"},
    ),
    "javascript/jose": (
        "src/jose_session.js",
        lines(
            'const jose = require("jose");',
            "const { JWT } = jose;",
            "",
            "function issue(claims) {",
            f"  return JWT.sign(claims, {SECRET});",
            "}",
            "",
            "module.exports = { issue };",
        ),
        {"hardcoded-jwt-secret"},
    ),
    "typescript/lang": (
        "src/cors.ts",
        lines("export const corsOrigins = [/app.example.com/];"),
        {"cors-regex-wildcard"},
    ),
    "typescript/react": (
        "src/View.tsx",
        lines(
            "export function View({ html }: { html: string }) {",
            "  return <div dangerouslySetInnerHTML={{ __html: html }} />;",
            "}",
        ),
        {"react-dangerouslysetinnerhtml"},
    ),
    "kdf": (
        "src/audit.py",
        lines(
            "import logging",
            "",
            "logger = logging.getLogger(__name__)",
            "",
            "",
            "def record(access_token):",
            '    logger.info("issued %s", access_token)',
        ),
        {"kdf-python-logger-secret-value"},
    ),
}
DROPPED    = {
    "src/fetch.py": lines("import requests", "", "", "def get(url):", "    return requests.get(url, verify=False)"),
    "src/calc.py": lines("def evaluate(expression):", "    return eval(expression)"),
    "src/notes.py": lines(
        "import logging",
        "",
        "",
        "def note(user):",
        '    logging.info("password reset for %s", user)',
    ),
}
HELPER     = lines(
    'const fs = require("fs");',
    'const path = require("path");',
    "",
    "function read(base, name) {",
    "  return fs.readFileSync(path.join(base, name));",
    "}",
    "",
    "module.exports = { read };",
)
PATH_RULES = {"detect-non-literal-fs-filename", "path-join-resolve-traversal"}


@pytest.fixture(scope = "module")
def every_family(tmp_path_factory: pytest.TempPathFactory) -> tuple:
    """
    One repo holding every family's file, scanned once, since each run of Opengrep costs some seconds.
    """
    files = {path: text for path, text, _rules in FAMILIES.values()}
    repo  = make_repo(tmp_path_factory.mktemp("families") / "repo", files)
    return scan(installed(), repo), repo


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_each_kept_rule_family_fires_on_its_fresh_vulnerable_file(every_family: tuple, family: str) -> None:
    result, _repo = every_family
    path, _text, rules = FAMILIES[family]
    failing = {rule for where, rule in result.fails() if where == path}
    assert rules <= failing, (family, failing, result.text)
    assert result.result == "FINDINGS", result.text


def test_the_scan_reads_every_inventory_file_and_ends_with_findings_alone(every_family: tuple) -> None:
    result, _repo = every_family
    assert f"opengrep  {len(FAMILIES)} of {len(FAMILIES)} inventory files read" in result.text, result.text
    assert result.last["code"] == "1" and "INCOMPLETE" not in result.last["result"], result.text


def test_a_python_low_finding_and_the_replaced_logger_rule_are_dropped(tmp_path: Path) -> None:
    result = scan(installed(), make_repo(tmp_path / "repo", DROPPED))
    assert result.result == "CLEAN", result.text
    assert not result.fails()


def test_a_typescript_low_finding_is_kept(tmp_path: Path) -> None:
    result = scan(installed(), make_repo(tmp_path / "repo", {"src/cors.ts": FAMILIES["typescript/lang"][1]}))
    assert ("src/cors.ts", "cors-regex-wildcard") in result.fails(), result.text


def test_the_two_path_rules_drop_under_tooling_folders_and_stay_under_src(tmp_path: Path) -> None:
    result  = scan(installed(), make_repo(tmp_path / "repo", {"scripts/read.js": HELPER, "src/read.js": HELPER}))
    tooling = {rule for where, rule in result.fails() if where == "scripts/read.js"}
    source  = {rule for where, rule in result.fails() if where == "src/read.js"}
    assert not tooling & PATH_RULES, result.text
    assert source & PATH_RULES, result.text


def test_kdfs_own_rule_matches_each_ruleid_line_of_its_test_cases_and_no_ok_line(tmp_path: Path) -> None:
    machine = installed()
    rules   = machine.root / "bundles" / machine.bundle / "scan_rules"
    rule_id = "kdf-python-logger-secret-value"
    work    = tmp_path / "work"
    (work / "rules").mkdir(parents = True)
    (work / "tree").mkdir()
    (work / "temp").mkdir()
    shutil.copy(rules / f"{rule_id}.yaml", work / "rules" / f"{rule_id}.yaml")
    shutil.copy(rules / f"{rule_id}.py", work / "tree" / "cases.py")
    text     = (work / "tree" / "cases.py").read_text(encoding = "utf-8").splitlines()
    expected = {number + 1 for number, line in enumerate(text, 1) if f"ruleid: {rule_id}" in line}
    allowed  = {number + 1 for number, line in enumerate(text, 1) if f"ok: {rule_id}" in line}
    assert expected and allowed, "the test cases name no ruleid or no ok line"
    opengrep = machine.root / "opengrep" / pin(machine, "OPENGREP_VERSION") / "opengrep.exe"
    command  = [
        str(opengrep),
        "scan",
        "--config",
        "rules",
        "--disable-version-check",
        "--json",
        "--output",
        "out.json",
        "tree",
    ]
    system   = os.environ.get("SYSTEMROOT", "C:\\Windows")
    done     = subprocess.run(
        command,
        cwd = work,
        capture_output = True,
        timeout = 600,
        check = False,
        env = {
            "SYSTEMROOT": system,
            "PATH": str(Path(system) / "System32"),
            "TEMP": str(work / "temp"),
            "TMP": str(work / "temp"),
            "USERPROFILE": os.environ.get("USERPROFILE", str(work)),
        },
    )
    assert done.returncode == 0, done.stderr
    found = {int(item["start"]["line"]) for item in json.loads((work / "out.json").read_text("utf-8"))["results"]}
    assert expected <= found, sorted(expected - found)
    assert not found & allowed, sorted(found & allowed)
