"""
The copier, ``mirror-ci-images.yml``, held to its rule by the cases it refuses, and its two scripts run (D-077, D-080).

``copier_rule.py`` holds the copier's text to a strict rule. Each case here changes one thing in the real text and
expects a refusal, the cases D-077 refused carried to the new text and the cases of D-080, among them the two Codex's
read ran on the rule D-077 left, a target set in a step's env and a script reassigning its sources.

A rule on the text cannot prove behaviour, as Codex's revision read showed with a rule passing an exit turned to
success. So the copy step's script and the proof's script are taken from the workflow's text as written and run under
bash, with stub ``skopeo``, ``curl``, ``git`` and ``timeout`` first on the path, a registry of folders and files the
stubs read and write, and Docker Hub's answers as files. ``jq`` is the real one where the machine has it, as GitHub's
runner does, and otherwise a stand in that answers the script's three filters alone, so no test touches a network.
Each kind of red and green the design names is a case here, and the shared E2E stack's images are held to the
copier's pinned entries, each a package and its digest together.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from tests.copier_rule import (
    COPIER,
    COPY_STEP,
    NAMESPACE,
    PROOF_STEP,
    copier_judged,
    env_entries,
    kept_digests,
    kept_entries,
    pinned_pairs,
    step_script,
)

# ======================================================================================================================
# Constants
# ======================================================================================================================

ROOT:     Path = Path(__file__).resolve().parents[2]
WORKFLOW: Path = ROOT / ".github" / "workflows" / COPIER
STACK:    Path = ROOT / "e2e" / "docker-compose.shared.yml"
BASH:     str | None = os.environ.get("KDF_TEST_BASH") or shutil.which("bash")
JQ:       str | None = shutil.which("jq")

# a stack's image line, its host and path, its package and its digest
STACK_IMAGE: re.Pattern[str] = re.compile(
    r"^\s+image: (?P<path>\S+)/(?P<name>[a-z0-9-]+)@(?P<digest>sha256:[0-9a-f]{64})\s*$",
)

# the three filters the copier's scripts give jq, the only ones the stand in answers
JQ_FILTERS: frozenset[str] = frozenset({".manifests[]?.digest", ".mediaType // empty", ".token // empty"})
JQ_CALL:    re.Pattern[str] = re.compile(r"jq -r '([^']*)'")

INDEX:    str = "application/vnd.oci.image.index.v1+json"
MANIFEST: str = "application/vnd.oci.image.manifest.v1+json"

# two blobs of the copier's file and main's commit, for the blob gate's cases
BLOB:   str = "1" * 40
OTHER:  str = "2" * 40
COMMIT: str = "3" * 40

# the proof jobs' condition as written, and a digest no entry holds, for the cases the rule refuses
PROOF_IF: str = (
    "    if: >-\n"
    "      !cancelled() && github.ref == 'refs/heads/main' &&\n"
    "      (needs.copy.result == 'success' || needs.copy.result == 'failure')\n"
)
D:        str = "d" * 64

# lines the refused cases write, each too long to sit in its case
STEP_TARGET: str = (
    "          REGISTRY_AUTH_FILE: ${{ runner.temp }}/kdf-registry-auth.json\n          TARGET: ghcr.io/someone\n"
    "        run: |\n"
)
RAW_LINE:    str = '          raw="$RUNNER_TEMP/kdf-manifest"\n'
HUB_WATCH:   str = "    postgres 16.15 docker.io/library/postgres 16 patch\n"

# skopeo. A registry of folders under STUB_REG, each repository's digests and tags, and the manifests by their hash
# under _blobs with the digests each lists beside it. A copy marks the digest and every one it lists present in its
# destination and writes the tag. STUB_SKOPEO_FAIL names words a failing call holds, STUB_PRIVATE a mirror that
# refuses a read with no credentials
SKOPEO = r"""#!/usr/bin/env bash
echo "skopeo $*" >> "$STUB_LOG"
for pattern in ${STUB_SKOPEO_FAIL:-}; do
	case "$*" in *"$pattern"*) exit 1 ;; esac
done
verb="$1"
shift
no_creds=""
format=""
refs=()
while [ "$#" -gt 0 ]; do
	case "$1" in
		--no-creds | --src-no-creds) no_creds="yes" ;;
		--raw | --all | --preserve-digests) ;;
		--format) format="$2"; shift ;;
		*) refs+=("$1") ;;
	esac
	shift
done
resolve() {
	local ref="${1#docker://}"
	if [[ "$ref" == *@* ]]; then
		repo="${ref%@*}"
		digest="${ref#*@}"
	else
		repo="${ref%:*}"
		digest="$(cat "$STUB_REG/$repo/tags/${ref##*:}" 2> /dev/null)" || return 1
	fi
	if [ -n "$no_creds" ] && [ -n "${STUB_PRIVATE:-}" ] && [[ "$repo" == ghcr.io/needless2say/* ]]; then return 1; fi
	[ -f "$STUB_REG/$repo/digests/${digest#sha256:}" ]
}
case "$verb" in
	inspect)
		resolve "${refs[0]}" || exit 1
		if [ -n "$format" ]; then
			echo "2026-09-17 21:31:24.32976807 +0000 UTC"
		else
			cat "$STUB_REG/_blobs/${digest#sha256:}"
		fi
		;;
	copy)
		resolve "${refs[0]}" || exit 1
		case "${refs[1]}" in dir:*) exit 0 ;; esac
		target="${refs[1]#docker://}"
		into="$STUB_REG/${target%:*}"
		mkdir -p "$into/digests" "$into/tags"
		: > "$into/digests/${digest#sha256:}"
		while read -r listed; do
			[ -n "$listed" ] && : > "$into/digests/${listed#sha256:}"
		done < "$STUB_REG/_blobs/${digest#sha256:}.listed"
		printf '%s' "$digest" > "$into/tags/${target##*:}"
		;;
	*) exit 2 ;;
esac
"""

# curl. A token for any scope, and Docker Hub's HEAD answered from STUB_HUB/<name>/<reference>, a line of status, type
# and digest, or a 404. STUB_TOKEN_DOWN fails the token
CURL = r"""#!/usr/bin/env bash
url="${*: -1}"
head_file=""
previous=""
for arg in "$@"; do
	[ "$previous" = "-D" ] && head_file="$arg"
	previous="$arg"
done
case "$url" in
	https://auth.docker.io/token*)
		echo "curl token" >> "$STUB_LOG"
		[ -z "${STUB_TOKEN_DOWN:-}" ] || exit 22
		printf '{"token":"tok.en-1"}'
		;;
	https://registry-1.docker.io/v2/library/*/manifests/*)
		rest="${url#https://registry-1.docker.io/v2/library/}"
		name="${rest%%/*}"
		reference="${rest##*/}"
		echo "curl head $name $reference" >> "$STUB_LOG"
		answer="$STUB_HUB/$name/${reference//:/_}"
		status=404
		type=application/json
		digest=""
		[ -f "$answer" ] && read -r status type digest < "$answer"
		{
			printf 'HTTP/2 %s\r\n' "$status"
			printf 'content-type: %s\r\n' "$type"
			[ -z "$digest" ] || printf 'docker-content-digest: %s\r\n' "$digest"
			printf '\r\n'
		} > "$head_file"
		printf '%s' "$status"
		;;
	*)
		echo "curl other $url" >> "$STUB_LOG"
		exit 2
		;;
esac
"""

# git. A fresh folder at init, a fetch that fails on STUB_FETCH_FAIL, and each rev-parse answered from STUB_RUN_BLOB,
# STUB_MAIN_BLOB and STUB_MAIN_COMMIT, an empty one failing as a missing file does
GIT = r"""#!/usr/bin/env bash
echo "git $*" >> "$STUB_LOG"
case "$*" in
	"init -q "*) mkdir -p "${@: -1}" ;;
	*" fetch "*) [ -z "${STUB_FETCH_FAIL:-}" ] || exit 128 ;;
	*"rev-parse --verify --quiet refs/kdf/run:"*) [ -n "${STUB_RUN_BLOB:-}" ] || exit 1; echo "$STUB_RUN_BLOB" ;;
	*"rev-parse --verify --quiet refs/kdf/main:"*) [ -n "${STUB_MAIN_BLOB:-}" ] || exit 1; echo "$STUB_MAIN_BLOB" ;;
	*"rev-parse --verify --quiet refs/kdf/main^{commit}"*) echo "${STUB_MAIN_COMMIT:-}" ;;
	*) exit 2 ;;
esac
"""

# timeout, which runs its command, its bound logged
TIMEOUT = r"""#!/usr/bin/env bash
echo "timeout $1" >> "$STUB_LOG"
shift
exec "$@"
"""

# jq's stand in, the script's three filters and no other, its lines ended as bash reads them
JQ_STAND_IN = r"""
import json
import sys

sys.stdout.reconfigure(newline = "\n")
args = [arg for arg in sys.argv[1:] if arg != "-r"]
if not args or args[0] not in (".manifests[]?.digest", ".mediaType // empty", ".token // empty"):
    sys.exit(3)
with (open(args[1], encoding = "utf-8") if len(args) > 1 else sys.stdin) as source:
    doc = json.load(source)
if args[0] == ".manifests[]?.digest":
    for entry in doc.get("manifests") or []:
        print(entry["digest"])
elif doc.get(args[0][1:].split(" ")[0]):
    print(doc[args[0][1:].split(" ")[0]])
"""

NEEDS_BASH = pytest.mark.skipif(BASH is None and not os.environ.get("CI"), reason = "bash is needed")

# ======================================================================================================================
# Helpers
# ======================================================================================================================

def _text() -> str:
    return WORKFLOW.read_text(encoding = "utf-8").replace("\r\n", "\n")


def _executable(path: Path, text: str) -> None:
    path.write_text(text, encoding = "utf-8", newline = "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@dataclass
class World:
    """
    A registry, Docker Hub's answers, the stubs and their log, and a runner's temp folder, all under one folder.
    """
    root: Path


    @property
    def registry(self) -> Path:
        return self.root / "registry"


    @property
    def log(self) -> Path:
        return self.root / "stub.log"


    def image(self, seed: str) -> str:
        """
        An index of two platforms, each manifest and the index written by its hash, the index's digest returned.
        """
        listed = [self._blob({"mediaType": MANIFEST, "seed": f"{seed} {arch}"}) for arch in ("amd64", "arm64")]
        found  = self._blob({"mediaType": INDEX, "manifests": [{"mediaType": MANIFEST, "digest": d} for d in listed]})
        (self.registry / "_blobs" / f"{found[7:]}.listed").write_text(
            "".join(f"{one}\n" for one in listed),
            encoding = "utf-8",
            newline = "\n",
        )
        return found


    def _blob(self, document: dict) -> str:
        body  = json.dumps(document).encode()
        found = "sha256:" + hashlib.sha256(body).hexdigest()
        (self.registry / "_blobs").mkdir(parents = True, exist_ok = True)
        (self.registry / "_blobs" / found[7:]).write_bytes(body)
        (self.registry / "_blobs" / f"{found[7:]}.listed").touch()
        return found


    def serve(self, repo: str, found: str) -> None:
        """
        A repository that serves a digest and every manifest it lists.
        """
        digests = self.registry / repo / "digests"
        digests.mkdir(parents = True, exist_ok = True)
        listed = (self.registry / "_blobs" / f"{found[7:]}.listed").read_text(encoding = "utf-8").split()
        for one in (found, *listed):
            (digests / one[7:]).touch()


    def tag(self, repo: str, tag: str, found: str) -> None:
        self.serve(repo, found)
        (self.registry / repo / "tags").mkdir(parents = True, exist_ok = True)
        (self.registry / repo / "tags" / tag).write_text(found, encoding = "utf-8", newline = "")


    def mirrored(self, name: str, tag: str) -> str:
        found = self.registry / NAMESPACE / name / "tags" / tag
        return found.read_text(encoding = "utf-8") if found.exists() else ""


    def answer(self, name: str, reference: str, status: int, found: str = "", kind: str = INDEX) -> None:
        """
        Docker Hub's answer to a HEAD for an official image's tag or digest.
        """
        (self.root / "hub" / name).mkdir(parents = True, exist_ok = True)
        (self.root / "hub" / name / reference.replace(":", "_")).write_text(
            f"{status} {kind} {found}\n",
            encoding = "utf-8",
            newline = "\n",
        )


    def calls(self) -> list[str]:
        return self.log.read_text(encoding = "utf-8").splitlines() if self.log.exists() else []


@dataclass
class Ran:
    """
    A script's exit, its output, and what it wrote to its outputs file.
    """
    code: int
    output: str
    outputs: dict[str, str]


    @property
    def close(self) -> str:
        """
        The script's last error line, which names every kind of red.
        """
        return next((line for line in reversed(self.output.splitlines()) if "ends red for" in line), "")


def _stubs(world: World) -> str:
    stubs = world.root / "stubs"
    stubs.mkdir(parents = True, exist_ok = True)
    for name, text in (("skopeo", SKOPEO), ("curl", CURL), ("git", GIT), ("timeout", TIMEOUT)):
        _executable(stubs / name, text)
    if JQ is None:
        (stubs / "jq_stand_in.py").write_text(JQ_STAND_IN, encoding = "utf-8")
        python, stand_in = Path(sys.executable).as_posix(), (stubs / "jq_stand_in.py").as_posix()
        _executable(stubs / "jq", f'#!/usr/bin/env bash\nexec "{python}" "{stand_in}" "$@"\n')
    return os.pathsep.join([stubs.as_posix(), os.environ.get("PATH", "")])


def _run(world: World, job: str, step: str, env: dict[str, str]) -> Ran:
    """
    One of the copier's scripts as its workflow writes it, run under bash with the stubs first on the path.
    """
    script = world.root / f"{job}.sh"
    script.write_text(step_script(_text(), job, step), encoding = "utf-8", newline = "\n")
    temp = world.root / "runner-temp"
    temp.mkdir(exist_ok = True)
    output = world.root / f"{job}.output"
    output.write_text("", encoding = "utf-8")
    environment = {
        **os.environ,
        "PATH": _stubs(world),
        "TARGET": NAMESPACE,
        "COPIER": f".github/workflows/{COPIER}",
        "RUNNER_TEMP": temp.as_posix(),
        "GITHUB_OUTPUT": output.as_posix(),
        "STUB_REG": world.registry.as_posix(),
        "STUB_HUB": (world.root / "hub").as_posix(),
        "STUB_LOG": world.log.as_posix(),
        **env,
    }
    done        = subprocess.run([str(BASH), script.as_posix()], capture_output = True, text = True, env = environment)
    outputs     = dict(line.split("=", 1) for line in output.read_text(encoding = "utf-8").splitlines() if "=" in line)
    return Ran(code = done.returncode, output = done.stdout + done.stderr, outputs = outputs)


@dataclass
class Fixture:
    """
    The digests a world holds, the kept Postgres, the pinned Caddy, both followed tags' current digests and an older
    one for each, and a digest the mirror holds for a hold.
    """
    world: World
    kept: str
    pinned: str
    node: str
    python: str
    old_node: str
    held: str


@pytest.fixture()
def fixture(tmp_path: Path) -> Fixture:
    """
    The kept Postgres on Docker Hub alone, so a copy tries ECR Public first and moves on, the pinned Caddy and both
    base images on ECR Public, and Docker Hub naming each followed tag's current index.
    """
    world = World(tmp_path)
    found = Fixture(
        world = world,
        kept = world.image("postgres 16.15"),
        pinned = world.image("caddy 2.10.2-alpine"),
        node = world.image("node 24-alpine"),
        python = world.image("python 3.14-slim"),
        old_node = world.image("node 24-alpine, last week"),
        held = world.image("node 24-alpine, held"),
    )
    world.serve("docker.io/library/postgres", found.kept)
    world.serve("public.ecr.aws/docker/library/caddy", found.pinned)
    world.serve("public.ecr.aws/docker/library/node", found.node)
    world.serve("public.ecr.aws/docker/library/python", found.python)
    world.answer("node", "24-alpine", 200, found.node)
    world.answer("python", "3.14-slim", 200, found.python)
    return found


def _copy(found: Fixture, followed: str = "node 24-alpine\npython 3.14-slim\n", **stub: str) -> Ran:
    """
    The copy step's script, the copier's own sources, one kept, one pinned and two followed entries.
    """
    env = {
        "SOURCES": "\n".join(line.strip() for line in env_entries(_text(), "SOURCES")) + "\n",
        "KEPT": f"{found.kept} 16.15 160015\n",
        "PINNED": f"caddy {found.pinned} 2.10.2-alpine\n",
        "FOLLOWED": followed,
        "GITHUB_SHA": "a" * 40,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "Needless2Say/kriegerdataforge-cicd",
        "STUB_RUN_BLOB": BLOB,
        "STUB_MAIN_BLOB": BLOB,
        "STUB_MAIN_COMMIT": COMMIT,
    }
    return _run(found.world, "copy", COPY_STEP, {**env, **stub})


def _proof(found: Fixture, gate: str, chosen: str, followed: str = "node 24-alpine\n", **stub: str) -> Ran:
    """
    The proof's script after a copy, the mirror already holding the kept and pinned entries.
    """
    found.world.tag(f"{NAMESPACE}/postgres", "16.15", found.kept)
    found.world.tag(f"{NAMESPACE}/caddy", "2.10.2-alpine", found.pinned)
    env = {
        "KEPT": f"{found.kept} 16.15 160015\n",
        "PINNED": f"caddy {found.pinned} 2.10.2-alpine\n",
        "FOLLOWED": followed,
        "GATE": gate,
        "CHOSEN": chosen,
    }
    return _run(found.world, "verify-images", PROOF_STEP, {**env, **stub})


def _followed(found: Fixture) -> list[str]:
    """
    Every write and every Docker Hub read of a followed tag the stubs saw.
    """
    return [
        call for call in found.world.calls()
        if call.startswith("curl head") or (call.startswith("skopeo copy") and ("/node" in call or "/python" in call))
    ]

# ======================================================================================================================
# The cases the rule refuses
# ======================================================================================================================

@pytest.mark.parametrize(
    ("old", "new"),
    [
        # a dispatch that takes an input, so whoever dispatches chooses something, in either place below its key
        ("  workflow_dispatch:\n", "  workflow_dispatch:\n    inputs:\n      digest:\n        type: string\n"),
        ("  workflow_dispatch:\n  schedule:", "  workflow_dispatch:\n\n    inputs:\n      digest:\n  schedule:"),
        # a pull request's trigger, another schedule, a second one, or a push of any file or branch
        ("on:\n  push:\n", "on:\n  pull_request:\n  push:\n"),
        ("    - cron: '23 6 * * *'\n", "    - cron: '0 * * * *'\n"),
        ("    - cron: '23 6 * * *'\n", "    - cron: '23 6 * * *'\n    - cron: '0 4 * * 1'\n"),
        ("    paths: [.github/workflows/mirror-ci-images.yml]\n", ""),
        ("    branches: [main]\n", "    branches: [main, 'feature/**']\n"),
        # no main guard, another, or one continued
        ("    if: github.ref == 'refs/heads/main'\n", ""),
        ("    if: github.ref == 'refs/heads/main'\n", "    if: github.ref != ''\n"),
        (
            "    if: github.ref == 'refs/heads/main'\n",
            "    if: github.ref == 'refs/heads/main'\n      || github.event_name == 'workflow_dispatch'\n",
        ),
        # a checkout, or any action at all, in any quoting
        ("    steps:\n", "    steps:\n      - name: Checkout\n        uses: actions/checkout@v7\n"),
        ("    steps:\n", "    steps:\n      - name: Set up\n        uses: actions/setup-python@v6\n"),
        ("    steps:\n", "    steps:\n      - name: Set up\n        \"uses\": actions/setup-python@v6\n"),
        # the copy job's grant widened, below a blank line too, a proof job granted anything, or the workflow's scope
        ("      packages: write\n", "      packages: write\n      contents: write\n"),
        ("      packages: write\n\n", "      packages: write\n\n      contents: write\n"),
        ("    permissions: {}\n", "    permissions:\n      contents: read\n"),
        ("permissions: {}\n\n# a whole", "permissions: write-all\n\n# a whole"),
        # a proof before the copy, its needs written twice, a run cut short
        ("    needs: copy\n", ""),
        ("    needs: copy\n", "    needs: copy\n    needs: []\n"),
        ("  cancel-in-progress: false\n", "  cancel-in-progress: true\n"),
        # a source on another host, a source path not its package's, a source continued, or a digest written in
        ("docker.io/library/node mirror.gcr.io", "quay.io/library/node mirror.gcr.io"),
        ("    node public.ecr.aws/docker/library/node", "    node public.ecr.aws/docker/library/python"),
        (" mirror.gcr.io/library/postgres\n", " mirror.gcr.io/library/postgres\n      quay.io/library/postgres\n"),
        ('"docker://$source@$digest"', f'"docker://$source@sha256:{D}"'),
        # a target outside the mirror, in the target, continued, or in the copy's own line
        (f"  TARGET: {NAMESPACE}\n", "  TARGET: ghcr.io/someone\n"),
        (f"  TARGET: {NAMESPACE}\n", f"  TARGET: {NAMESPACE}\n    -elsewhere\n"),
        ('"docker://$TARGET/$name:$tag"', '"docker://ghcr.io/someone/$name:$tag"'),
        # the verify job's service not on the mirror, given credentials, or a second service
        ("        image: ghcr.io/needless2say/postgres@", "        image: public.ecr.aws/docker/library/postgres@"),
        ("        ports:\n", "        credentials:\n          username: ${{ github.actor }}\n        ports:\n"),
        ("    services:\n", "    services:\n      cache:\n        ports:\n          - 6379:6379\n"),
        # a kept entry without its server_version_num, or its digest, and an escape, which can spell a key
        (" 16.15 160015\n", " 16.15\n"),
        ("\n  KEPT: |\n    sha256:", "\n  KEPT: |\n    "),
        ("    runs-on: ubuntu-latest\n", '    "\\x72uns-on": ubuntu-latest\n'),
        # D-080. A followed tag read from ECR Public or Google's mirror
        (
            "https://registry-1.docker.io/v2/library/$name/manifests/$reference",
            "https://public.ecr.aws/v2/docker/library/$name/manifests/$reference",
        ),
        (
            "https://registry-1.docker.io/v2/library/$name/manifests/$reference",
            "https://mirror.gcr.io/v2/library/$name/manifests/$reference",
        ),
        ("https://auth.docker.io/token?service=registry.docker.io&", "https://mirror.gcr.io/token?"),
        # a pinned entry with no digest or no tag, or a package with no sources
        ("    caddy sha256:", "    caddy "),
        (" 2.10.2-alpine\n    mailpit", "\n    mailpit"),
        ("    checkov sha256:", "    trivy sha256:"),
        # a followed tag with no tag, a word after it, a hold out of its shape, or an image Docker Hub does not name
        ("    node 24-alpine\n", "    node\n"),
        ("    node 24-alpine\n", "    node 24-alpine latest\n"),
        ("    node 24-alpine\n", "    node 24-alpine sha256:abc\n"),
        ("    python 3.14-slim\n", "    python 3.14-slim\n    mailpit 1.31\n"),
        ("    python 3.14-slim\n", f"    python 3.14-slim\n    checkov 3.3 sha256:{D}\n"),
        # a destination tag two entries hold, a pinned tag on the lanes' own, or a followed tag written twice
        ("16.15-alpine\n    caddy", "16.15\n    caddy"),
        ("    node 24-alpine\n", f"    node 24-alpine\n    node 24-alpine sha256:{D}\n"),
        # a watched line naming no kept or pinned image, asking a mirror, at another level, or an image unwatched
        ("    caddy 2.10.2-alpine docker.io", "    caddy 2.11.0-alpine docker.io"),
        ("    postgres 16.15 docker.io/library/postgres", "    postgres 16.15 public.ecr.aws/docker/library/postgres"),
        (" latest minor\n", " latest major\n"),
        ("    checkov 3.3.6 ghcr.io/bridgecrewio/checkov latest minor\n", ""),
        # a copy step without its blob comparison or its tamper check
        ('if git init -q "$work" \\', 'if mkdir -p "$work" \\'),
        ('elif [ "$run_blob" = "$main_blob" ]; then', 'elif true; then'),
        ('                tampered="$mirrored"\n', ""),
        ('            if [ -n "$tampered" ]; then', '            if false; then'),
        # a proof whose condition lacks !cancelled(), is !cancelled() alone, or names no main
        (PROOF_IF, PROOF_IF.replace("!cancelled() && ", "")),
        (PROOF_IF, "    if: ${{ !cancelled() }}\n"),
        (PROOF_IF, PROOF_IF.replace("github.ref == 'refs/heads/main' &&", "&&")),
        (
            "    name: Prove every image public and present\n    needs: copy\n    if: >-\n      !cancelled() && ",
            "    name: Prove every image public and present\n    needs: copy\n    if: >-\n      ",
        ),
        # the proof of every image given a service, or without its gate or its tamper check
        ("    timeout-minutes: 45\n", "    timeout-minutes: 45\n    services:\n      cache:\n        ports:\n"),
        ('          if [ "$GATE" = current ]; then', '          if true; then'),
        ('            elif [ "$code" = 404 ]; then\n              failed tamper', "            elif false; then\n"),
        # a changed outputs block
        (
            "      chosen: ${{ steps.copy.outputs.chosen }}\n",
            "      chosen: ${{ steps.copy.outputs.chosen }}\n      extra: ${{ github.token }}\n",
        ),
        # from Codex's read of D-080, a target set in a step's env, and a script reassigning its sources or target
        ("          REGISTRY_AUTH_FILE: ${{ runner.temp }}/kdf-registry-auth.json\n        run: |\n", STEP_TARGET),
        (RAW_LINE, f'{RAW_LINE}          SOURCES="x y"\n'),
        ("          declare -A sources\n", '          declare -A sources\n          sources[postgres]="quay.io/x"\n'),
        (RAW_LINE, f"{RAW_LINE}          export TARGET=x\n"),
        (RAW_LINE, f"{RAW_LINE}          read -r TARGET <x\n"),
        # from Codex's review of D-080, a failure that ends green or a proof step skipped, each leaving both scripts
        # the same, and a script under another shell
        ("        id: copy\n", "        id: copy\n        continue-on-error: true\n"),
        ("    timeout-minutes: 45\n", "    timeout-minutes: 45\n    continue-on-error: true\n"),
        (f"      - name: {PROOF_STEP}\n", f"      - name: {PROOF_STEP}\n        if: false\n"),
        ("        id: copy\n", "        id: copy\n        'if': ${{ false }}\n"),
        ("        id: copy\n", "        id: copy\n        shell: bash {0}\n"),
        # a present check that takes one platform's manifest for an index
        ('            indexed "$raw.index" || return 1\n', ""),
    ],
)
def test_a_copier_out_of_its_rule_is_refused(old, new):
    text = _text()
    assert old in text, "each case changes a line the copier holds"

    assert copier_judged(text.replace(old, new, 1))[1] != []


def test_a_verify_job_not_on_the_newest_kept_entry_is_refused():
    """
    A bump appends an entry and its watched line and moves verify's service to it in the same pull request, and
    verify left on an older one, or on a digest the copier does not keep, would prove the wrong image.
    """
    text    = _text()
    entries = kept_entries(text)
    newest  = kept_digests(text)[-1]
    bumped  = text.replace(f"{entries[-1]}\n", f"{entries[-1]}\n    sha256:{'c' * 64} 16.16 160016\n", 1).replace(
        HUB_WATCH,
        HUB_WATCH + HUB_WATCH.replace("16.15", "16.16"),
        1,
    )
    unkept  = text.replace(
        f"        image: {NAMESPACE}/postgres@{newest}\n",
        f"        image: {NAMESPACE}/postgres@sha256:{'c' * 64}\n",
        1,
    )

    assert bumped != text and unkept != text
    # the bump's only faults are the verify job's service, its block and the newest entry it should name
    faults = copier_judged(bumped)[1]
    assert faults and all("the verify job's services" in fault or "newest kept entry" in fault for fault in faults)
    assert copier_judged(unkept)[1] != []

# ======================================================================================================================
# The shared stack's images, each a pinned pair (D-080)
# ======================================================================================================================

def stack_pairs(text: str) -> list[tuple[str, str]]:
    """
    Each image line of a stack, its package and its digest.
    """
    return [(found["name"], found["digest"]) for found in map(STACK_IMAGE.match, text.splitlines()) if found]


def test_each_stack_image_is_a_package_and_digest_the_copier_pins():
    """
    The stack still names its upstreams until cicd's second pull request moves it to the mirror, and each of its four
    lines is already a package and digest the copier pins, so that pull request flips the host alone.
    """
    pairs = stack_pairs(STACK.read_text(encoding = "utf-8"))

    assert len(pairs) == 4 and set(pairs) <= pinned_pairs(_text())


def test_a_stack_line_on_another_packages_digest_is_refused():
    """
    A digest the copier pins for Postgres, named on a Caddy line, is compared with its package and refused.
    """
    stack   = STACK.read_text(encoding = "utf-8")
    pins    = dict(pinned_pairs(_text()))
    swapped = stack.replace(pins["caddy"], pins["postgres"], 1)

    assert swapped != stack and not set(stack_pairs(swapped)) <= pinned_pairs(_text())


def test_the_scripts_give_jq_only_the_filters_the_stand_in_answers():
    """
    So the stand in on a machine with no jq runs the same scripts the runner's jq does.
    """
    text = _text()
    used = {found for step in ((("copy", COPY_STEP), ("verify-images", PROOF_STEP))) for found in JQ_CALL.findall(
        step_script(text, *step),
    )}

    assert used == JQ_FILTERS

# ======================================================================================================================
# The copy step's script, run
# ======================================================================================================================

@NEEDS_BASH
def test_a_current_run_copies_every_entry_follows_each_tag_and_reads_every_source_with_no_credentials(fixture):
    ran   = _copy(fixture)
    world = fixture.world

    assert ran.code == 0, ran.output
    assert world.mirrored("postgres", "16.15") == fixture.kept
    assert world.mirrored("caddy", "2.10.2-alpine") == fixture.pinned
    assert (
        world.mirrored("node", "24-alpine"),
        world.mirrored("python", "3.14-slim"),
    ) == (fixture.node, fixture.python)
    assert ran.outputs == {
        "gate": "current",
        "chosen": f"node:24-alpine@{fixture.node} python:3.14-slim@{fixture.python}",
    }
    copies = [call for call in world.calls() if call.startswith("skopeo copy --all")]
    assert len(copies) == 5 and all(" --src-no-creds docker://" in call for call in copies)
    # the kept Postgres tried ECR Public first, which does not serve it here, then Docker Hub
    assert [call.split(" ")[5].split("@")[0] for call in copies[:2]] == [
        "docker://public.ecr.aws/docker/library/postgres",
        "docker://docker.io/library/postgres",
    ]


@NEEDS_BASH
def test_an_early_entrys_failure_lets_every_later_entry_run_and_still_ends_red(fixture):
    """
    The kept Postgres, copied before the pinned and followed entries, served by no source.
    """
    (fixture.world.registry / "docker.io" / "library" / "postgres" / "digests" / fixture.kept[7:]).unlink()
    ran = _copy(fixture)

    assert ran.code == 1 and " copy" in ran.close
    assert fixture.world.mirrored("postgres", "16.15") == ""
    assert fixture.world.mirrored("caddy", "2.10.2-alpine") == fixture.pinned
    assert fixture.world.mirrored("node", "24-alpine") == fixture.node


@NEEDS_BASH
@pytest.mark.parametrize(
    ("status", "kind", "shape"),
    [
        (200, MANIFEST, "digest"),
        (200, INDEX, "short"),
        (200, INDEX, "none"),
        (429, INDEX, "digest"),
        (404, INDEX, "none"),
    ],
)
def test_a_docker_hub_answer_out_of_its_shape_moves_nothing_and_ends_red(fixture, status, kind, shape):
    """
    A 200 that is not an index, a digest of another shape or none, a refusal and a 404 each leave the tag as it is.
    """
    world = fixture.world
    world.tag(f"{NAMESPACE}/node", "24-alpine", fixture.old_node)
    world.answer("node", "24-alpine", status, {"digest": fixture.node, "short": "sha256:abc", "none": ""}[shape], kind)
    ran = _copy(fixture)

    assert ran.code == 1 and "refused" in ran.close
    assert world.mirrored("node", "24-alpine") == fixture.old_node
    assert world.mirrored("python", "3.14-slim") == fixture.python
    assert ran.outputs["chosen"] == f"python:3.14-slim@{fixture.python}"


@NEEDS_BASH
def test_a_failed_token_is_a_refusal_and_moves_nothing(fixture):
    ran = _copy(fixture, STUB_TOKEN_DOWN = "yes")

    assert ran.code == 1 and "refused" in ran.close
    assert fixture.world.mirrored("node", "24-alpine") == ""


@NEEDS_BASH
def test_another_blob_on_a_first_attempt_moves_nothing_followed_and_ends_green(fixture):
    ran = _copy(fixture, STUB_MAIN_BLOB = OTHER)

    assert ran.code == 0, ran.output
    assert _followed(fixture) == []
    assert fixture.world.mirrored("postgres", "16.15") == fixture.kept
    assert ran.outputs == {"gate": "stale", "chosen": ""}
    assert f"::notice::" in ran.output and COMMIT in ran.output


@NEEDS_BASH
def test_another_blob_on_a_rerun_moves_nothing_followed_and_ends_red(fixture):
    ran = _copy(fixture, STUB_MAIN_BLOB = OTHER, GITHUB_RUN_ATTEMPT = "2")

    assert ran.code == 1 and "stale-rerun" in ran.close
    assert "Dispatch the copier from main" in ran.output
    assert _followed(fixture) == []


@NEEDS_BASH
@pytest.mark.parametrize(
    "stub",
    [
        {"STUB_FETCH_FAIL": "yes"},
        {"STUB_RUN_BLOB": ""},
        # main's commit without the file reads empty, as its rev-parse fails
        {"STUB_MAIN_BLOB": ""},
        {"STUB_RUN_BLOB": "", "STUB_MAIN_BLOB": ""},
        {"STUB_RUN_BLOB": "not a blob", "STUB_MAIN_BLOB": "not a blob"},
    ],
)
def test_a_gate_that_cannot_read_both_blobs_moves_nothing_followed_and_ends_red(fixture, stub):
    """
    An empty read never counts as equal, and the kept and pinned entries are still copied.
    """
    ran = _copy(fixture, **stub)

    assert ran.code == 1 and "gate" in ran.close
    assert _followed(fixture) == []
    assert ran.outputs == {"gate": "unread", "chosen": ""}
    assert fixture.world.mirrored("caddy", "2.10.2-alpine") == fixture.pinned


@NEEDS_BASH
@pytest.mark.parametrize(
    ("status", "answered", "code", "warned"),
    [
        # Docker Hub serves the old digest, a move forward
        (200, "old", 0, False),
        # it does not, a possible tamper or a digest it no longer serves, recorded, repaired and red
        (404, "none", 1, False),
        # a refusal, or a 200 for another digest, decides nothing
        (429, "none", 0, True),
        (200, "new", 0, True),
    ],
)
def test_the_tamper_check_of_the_digest_the_mirrors_tag_holds(fixture, status, answered, code, warned):
    world = fixture.world
    world.tag(f"{NAMESPACE}/node", "24-alpine", fixture.old_node)
    world.answer("node", fixture.old_node, status, {"old": fixture.old_node, "new": fixture.node, "none": ""}[answered])
    ran = _copy(fixture)

    assert ran.code == code, ran.output
    assert world.mirrored("node", "24-alpine") == fixture.node
    assert ("tamper" in ran.close) == (code == 1)
    assert (fixture.old_node in ran.output) and (("decides nothing" in ran.output) == warned)


@NEEDS_BASH
def test_a_hold_is_set_from_the_mirrors_own_copy_and_its_digest_is_never_sent_to_docker_hub(fixture):
    world = fixture.world
    world.serve(f"{NAMESPACE}/node", fixture.held)
    ran = _copy(fixture, followed = f"node 24-alpine {fixture.held}\npython 3.14-slim\n")

    assert ran.code == 0, ran.output
    assert world.mirrored("node", "24-alpine") == fixture.held
    assert f"node:24-alpine@{fixture.held}" in ran.outputs["chosen"]
    assert not [call for call in world.calls() if fixture.held.replace(":", "_") in call or (
        call.startswith("curl head") and fixture.held in call
    )]
    assert not [call for call in world.calls() if "public.ecr.aws/docker/library/node" in call]
    assert f"is held on {fixture.held} while Docker Hub names {fixture.node}" in ran.output


@NEEDS_BASH
def test_a_hold_on_one_platforms_manifest_is_red_and_leaves_the_tag(fixture):
    """
    From Codex's review of D-080, a hold naming a child of an index the package holds, which would leave the tag one
    platform, is refused, since a present entry is an index by its own mediaType.
    """
    world = fixture.world
    world.serve(f"{NAMESPACE}/node", fixture.held)
    child = (world.registry / "_blobs" / f"{fixture.held[7:]}.listed").read_text(encoding = "utf-8").split()[0]
    ran   = _copy(fixture, followed = f"node 24-alpine {child}\npython 3.14-slim\n")

    assert ran.code == 1 and "hold" in ran.close
    assert world.mirrored("node", "24-alpine") == ""


@NEEDS_BASH
def test_a_followed_tag_already_placed_is_still_chosen_so_a_later_move_is_a_placement_red(fixture):
    """
    From Codex's review of D-080. A tag already on Docker Hub's digest is left as it is and still chosen, so a writer
    that moves it to an older digest Docker Hub still serves is caught by the proof's placement and not passed by its
    tamper check.
    """
    world = fixture.world
    world.tag(f"{NAMESPACE}/node", "24-alpine", fixture.node)
    ran = _copy(fixture)

    assert ran.code == 0, ran.output
    assert f"node:24-alpine@{fixture.node}" in ran.outputs["chosen"]
    assert not [call for call in world.calls() if call.startswith("skopeo copy --all") and "/node@" in call]
    world.tag(f"{NAMESPACE}/node", "24-alpine", fixture.old_node)
    world.answer("node", fixture.old_node, 200, fixture.old_node)
    proof = _proof(fixture, "current", ran.outputs["chosen"])

    assert proof.code == 1 and "placement" in proof.close


@NEEDS_BASH
def test_a_proof_of_a_tag_on_one_platforms_manifest_is_red(fixture):
    world = fixture.world
    world.serve(f"{NAMESPACE}/node", fixture.node)
    child = (world.registry / "_blobs" / f"{fixture.node[7:]}.listed").read_text(encoding = "utf-8").split()[0]
    world.tag(f"{NAMESPACE}/node", "24-alpine", child)
    ran = _proof(fixture, "current", "")

    assert ran.code == 1 and "private" in ran.close


@NEEDS_BASH
def test_a_hold_its_package_lacks_is_red_and_leaves_the_tag(fixture):
    ran = _copy(fixture, followed = f"node 24-alpine {fixture.held}\npython 3.14-slim\n")

    assert ran.code == 1 and "hold" in ran.close
    assert fixture.world.mirrored("node", "24-alpine") == ""


@NEEDS_BASH
def test_each_kind_of_red_is_recorded_apart_and_no_later_success_clears_one(fixture):
    """
    The kept entry unserved, a tamper on node and a refusal on python, each named at the close.
    """
    world = fixture.world
    (world.registry / "docker.io" / "library" / "postgres" / "digests" / fixture.kept[7:]).unlink()
    world.tag(f"{NAMESPACE}/node", "24-alpine", fixture.old_node)
    world.answer("python", "3.14-slim", 429)
    ran = _copy(fixture)

    assert ran.code == 1
    assert {"copy", "tamper", "refused"} <= set(ran.close.split("for:", 1)[1].split(",", 1)[0].split())
    assert world.mirrored("caddy", "2.10.2-alpine") == fixture.pinned

# ======================================================================================================================
# The proof's script, run
# ======================================================================================================================

@NEEDS_BASH
def test_a_current_proof_reads_and_pulls_every_entry_with_no_credentials_and_holds_the_chosen_digest(fixture):
    world = fixture.world
    world.tag(f"{NAMESPACE}/node", "24-alpine", fixture.node)
    ran = _proof(fixture, "current", f"node:24-alpine@{fixture.node}")

    assert ran.code == 0, ran.output
    reads = [call for call in world.calls() if call.startswith("skopeo inspect")]
    pulls = [call for call in world.calls() if call.startswith("skopeo copy")]
    assert reads and all("--no-creds" in call for call in reads)
    assert {f"docker://{NAMESPACE}/caddy@{fixture.pinned}", f"docker://{NAMESPACE}/node@{fixture.node}"} == {
        call.split(" ")[3] for call in pulls
    }
    assert all(call.startswith("skopeo copy --src-no-creds") for call in pulls)


@NEEDS_BASH
def test_a_current_proof_reds_a_tag_not_on_the_chosen_digest(fixture):
    fixture.world.tag(f"{NAMESPACE}/node", "24-alpine", fixture.old_node)
    ran = _proof(fixture, "current", f"node:24-alpine@{fixture.node}")

    assert ran.code == 1 and "placement" in ran.close


@NEEDS_BASH
def test_a_package_still_private_fails_the_proof_closed(fixture):
    fixture.world.tag(f"{NAMESPACE}/node", "24-alpine", fixture.node)
    ran = _proof(fixture, "current", f"node:24-alpine@{fixture.node}", STUB_PRIVATE = "yes")

    assert ran.code == 1 and "private" in ran.close


@NEEDS_BASH
@pytest.mark.parametrize(("gate", "code"), [("stale", 0), ("unread", 0), ("current", 1)])
def test_a_hold_its_text_lacks_is_judged_by_a_current_proof_alone(fixture, gate, code):
    """
    main applied a hold this old run's text lacks, the tag on a digest Docker Hub does not serve. A stale or unread
    gate makes no tamper decision and asks Docker Hub nothing, and a current run Docker Hub refused still makes it.
    """
    fixture.world.tag(f"{NAMESPACE}/node", "24-alpine", fixture.held)
    ran = _proof(fixture, gate, "")

    assert ran.code == code, ran.output
    assert ("tamper" in ran.close) == (code == 1)
    assert bool([call for call in fixture.world.calls() if call.startswith("curl head")]) == (gate == "current")


@NEEDS_BASH
@pytest.mark.parametrize(("gate", "code"), [("stale", 0), ("current", 1)])
def test_a_hold_main_has_removed_is_judged_by_a_current_proof_alone(fixture, gate, code):
    """
    This old run's text holds node on a digest main no longer holds it on, the tag followed since.
    """
    fixture.world.tag(f"{NAMESPACE}/node", "24-alpine", fixture.node)
    ran = _proof(fixture, gate, "", followed = f"node 24-alpine {fixture.held}\n")

    assert ran.code == code, ran.output
    assert ("placement" in ran.close) == (code == 1)


@NEEDS_BASH
def test_a_current_proof_of_a_digest_docker_hub_serves_is_green(fixture):
    world = fixture.world
    world.tag(f"{NAMESPACE}/node", "24-alpine", fixture.old_node)
    world.answer("node", fixture.old_node, 200, fixture.old_node)
    ran = _proof(fixture, "current", "")

    assert ran.code == 0, ran.output
