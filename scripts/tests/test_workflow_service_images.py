"""
Every image a workflow of this repo starts, held to one source and one exact image (D-064, D-077, D-080).

A service container's image is pulled by the runner before the job's first step. Pulled from Docker Hub without a
login, it met the anonymous limit every tenant of a runner's address shares, and the job failed before a test ran
(D-064). AWS ECR Public's gallery, which came next, met a data limit counted by address too (D-077). So every Postgres
lane names one image, the lanes' constant below, pinned by its index digest, which no registry can change, and that
digest one the copier keeps. A tag, a bare name or another host is refused, since a host misspelled to Docker Hub's
would pull the same digest from Docker Hub and pass unseen.

YAML writes an image many ways, a service's key, a job's container, a flow mapping, a quoted or escaped key, a step's
``docker://`` action, and a script can run ``docker`` itself. Two reviews of this test found a reading of the values
missing one more form each time, so the rule is on the text. A workflow line that is not a comment and names
``image``, ``container`` or ``docker``, in any case, must be a service's ``image:`` line with the pinned reference
and nothing else, and no line may hold a ``\\x``, ``\\u`` or ``\\U`` escape, which can spell a key. A new use of an
image, a job's container for one, changes this test with it.

The copier, ``mirror-ci-images.yml``, copies every image CI pulls to the owner's mirror on GitHub's registry and
proves each public (D-077, D-080). It names ``docker://`` and ``skopeo`` by design, so it is read by a strict rule of
its own, ``copier_rule.py``, and ``test_mirror_ci_images.py`` holds the cases that rule refuses and runs the copier's
two scripts under stubs. And no workflow names a ``credentials`` key, or declares a grant that can write a package but
the copier's copy job.

It catches a mistake, not a workflow written to hide a pull. Whoever can edit a workflow can run any code in it, and
a word split by a YAML line continuation, or a pull built in a script from a line that reads as a comment, passes
this reading, as a third review showed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.copier_rule import (
    COMMENT,
    COPIER,
    ESCAPE,
    KEPT_ENTRY,
    MIRROR,
    block,
    blocks,
    copier_judged,
    kept_digests,
    kept_entries,
)

# ======================================================================================================================
# Constants
# ======================================================================================================================

WORKFLOWS: Path = Path(__file__).resolve().parents[2] / ".github" / "workflows"

# the one shape an E2E image may take on ECR Public, Docker's official gallery by an index digest, D-065's rule below
PINNED_IMAGE: str = r"public\.ecr\.aws/docker/library/[a-z0-9][a-z0-9._-]*@sha256:[0-9a-f]{64}"

# the gallery the lanes named before the copier's mirror
ECR_PUBLIC: str = "public.ecr.aws/docker/library/postgres"

# the one image every Postgres lane names (D-077), ECR Public's gallery until the copier's run proved the mirror, then
# the mirror. A way back is the lanes' lines and this constant, which stands apart from PINNED_IMAGE, D-065's
LANE_IMAGE:  str = MIRROR
LANE_PINNED: re.Pattern[str] = re.compile(rf"^{re.escape(LANE_IMAGE)}@sha256:[0-9a-f]{{64}}$")

# the one line that may name an image in a lane, a service's block key and the pinned reference, nothing after it
IMAGE_LINE: re.Pattern[str] = re.compile(rf"^\s+image: (?P<image>{re.escape(LANE_IMAGE)}@sha256:[0-9a-f]{{64}})\s*$")

# the words that name an image or pull one, read in any case
NAMING: re.Pattern[str] = re.compile(r"image|container|docker", re.IGNORECASE)

# the workflows that start a Postgres service, each once, the copier's verify job and the three reusable lanes
WITH_POSTGRES: tuple[str, ...] = (
    COPIER,
    "ci-python-integration.yml",
    "ci-python-mutation.yml",
    "ci-python-system.yml",
)

# a job's key, two spaces in
JOB_KEY: re.Pattern[str] = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")

# a grant that can write a package, a packages key whose value is not read or none, or every scope at once
PACKAGES_KEY: re.Pattern[str] = re.compile(
    r"""(?<![\w-])["']?packages["']?\s*:\s*["']?(?P<value>[a-z-]*)""",
    re.IGNORECASE,
)
WRITE_ALL:    re.Pattern[str] = re.compile(r"write-all", re.IGNORECASE)

# a key that names credentials, a service's or a container's login, in any case or quoting, its colon followed by a
# space, the line's end or a flow mapping's mark. persist-credentials, a checkout's input, is not one
CREDENTIALS: re.Pattern[str] = re.compile(
    r"""(?<![\w-])(?:credentials\s*:(?=[\s,\[\]{}]|$)|["']credentials["']\s*:)""",
    re.IGNORECASE,
)

# the E2E stack every release's journey starts on a runner (D-065), and the one line that may name an image there,
# from the official gallery on ECR Public or a publisher's own GitHub registry, by digest
SHARED_COMPOSE: Path = Path(__file__).resolve().parents[2] / "e2e" / "docker-compose.shared.yml"
COMPOSE_IMAGE:  re.Pattern[str] = re.compile(
    rf"^\s+image: (?:{PINNED_IMAGE}|ghcr\.io/[a-z0-9-]+/[a-z0-9._-]+@sha256:[0-9a-f]{{64}})\s*$",
)

# a pinned reference, and Docker Hub's image, for the forms the cases write
GOOD: str = f"{LANE_IMAGE}@sha256:" + "a" * 64
HUB:  str = "postgres:16"

# two kept digests, the older first, for the cases of a bump's stages
OLDER:  str = "sha256:" + "a" * 64
NEWEST: str = "sha256:" + "b" * 64

# the lanes' own proof in ci.yml (D-077), held whole, since a test command that never queried Postgres passed a
# reading of its number alone (Codex's read). The integration lane called by a local reference, waiting for the scan
# and taking its skip (D-075), installing and migrating nothing, and its test a psql read of the service by host and
# port, an SQL error or another number failing it, held to the version of the kept entry the lanes' digest names
LANE_PROOF:     str = "postgres-lane-proof"
LANE_PROOF_JOB: tuple[str, ...] = (
    "  postgres-lane-proof:",
    "    needs: [secret-scan]",
    "    if: ${{ !cancelled() }}",
    "    uses: ./.github/workflows/ci-python-integration.yml",
    "    with:",
    "      install_command: echo nothing to install",
    "      migrate_command: echo nothing to migrate",
    '      seed_command: ""',
    "      test_command: >-",
    '        number="$(PGPASSWORD=kdf psql -X -w -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 5432 -U kdf -d kdf_test -At',
    "        -c 'show server_version_num')\" && echo \"the lane's service reports server_version_num $number\" &&",
    '        test "$number" = {version}',
    "      skip: ${{ needs.secret-scan.result == 'success' && needs.secret-scan.outputs.docs_only == 'true' }}",
)

# ======================================================================================================================
# Helpers
# ======================================================================================================================

def judged(text: str) -> tuple[list[str], list[str]]:
    """
    A workflow's text judged line by line.

    Args:
        text: A workflow file's text

    Returns:
        tuple[list[str], list[str]]: The pinned images its service lines name, and every other line that names an
            image, a container or docker, or holds an escape, each refused
    """
    images, refused = [], []
    for line in text.splitlines():
        if COMMENT.match(line):
            continue
        if ESCAPE.search(line):
            refused.append(line.strip())
            continue
        if not NAMING.search(line):
            continue
        matched = IMAGE_LINE.match(line)
        if matched:
            images.append(matched.group("image"))
        else:
            refused.append(line.strip())
    return images, refused


def _text(name: str) -> str:
    """
    One workflow's text, its line ends the runner's.
    """
    return (WORKFLOWS / name).read_text(encoding = "utf-8").replace("\r\n", "\n")


def _names() -> list[str]:
    """
    Every workflow of this repo, by its file name.
    """
    return [workflow.name for workflow in sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])]


def _workflows() -> dict[str, tuple[list[str], list[str]]]:
    """
    Every workflow of this repo judged, by its file name, the copier by its own rule.
    """
    return {name: copier_judged(_text(name)) if name == COPIER else judged(_text(name)) for name in _names()}


def digest(image: str) -> str:
    """
    An image's digest, its ``sha256:`` part, by which D-077 compares a lane with the copier's kept entries.
    """
    return image.split("@", 1)[1]


def stage_faults(images: dict[str, list[str]], kept: list[str]) -> list[str]:
    """
    Where the Postgres services break D-077's order, at every stage of a move or a bump.

    Args:
        images: The images each workflow's service lines name, by its file name
        kept: The copier's kept digests, the newest last

    Returns:
        list[str]: Each fault. The copier and the three lanes alone start a service, each names one Postgres image,
            the lanes one digest among the kept ones, and the copier's verify job the newest on the mirror
    """
    faults  = []
    started = sorted(name for name, found in images.items() if found)
    if started != sorted(WITH_POSTGRES):
        faults.append(f"the workflows that start a service are {started}")
    for name in WITH_POSTGRES:
        if len(images.get(name, [])) != 1 or "/postgres@sha256:" not in images[name][0]:
            faults.append(f"{name} names other than one Postgres image")
    lanes = {digest(image) for name in WITH_POSTGRES if name != COPIER for image in images.get(name, [])}
    if len(lanes) != 1:
        faults.append(f"the lanes name {len(lanes)} digests, not one")
    faults.extend(f"a lane names {found}, which the copier does not keep" for found in sorted(lanes - set(kept)))
    if not kept or images.get(COPIER) != [f"{MIRROR}@{kept[-1]}"]:
        faults.append("the copier's verify job does not name the newest kept digest on the mirror")
    return faults


def package_grants(text: str) -> list[tuple[str, str]]:
    """
    Every declared grant in a workflow's text that can write a package, with the scope it sits in.

    A workflow that declares no permissions takes the repository's default token, which the text cannot show, so the
    owner holds cicd's default workflow permission read only (D-077).

    Args:
        text: A workflow file's text

    Returns:
        list[tuple[str, str]]: Each grant's scope, ``workflow`` or a job's id, and its line. A ``packages`` key whose
            value is not ``read`` or ``none``, its value on the next line among them, ``write-all`` in any case, or a
            line with an escape, which can spell either
    """
    grants, scope, in_jobs = [], "workflow", False
    for line in text.splitlines():
        if COMMENT.match(line):
            continue
        if line.rstrip() == "jobs:":
            in_jobs = True
            continue
        job = JOB_KEY.match(line)
        if in_jobs and job:
            scope = job.group(1)
            continue
        key = PACKAGES_KEY.search(line)
        if ESCAPE.search(line) or WRITE_ALL.search(line) or (
            key and key.group("value").lower() not in ("read", "none")
        ):
            grants.append((scope, line.strip()))
    return grants


def credentials_keys(text: str) -> list[str]:
    """
    Every line of a workflow's text that is not a comment and names a ``credentials`` key.
    """
    return [line.strip() for line in text.splitlines() if not COMMENT.match(line) and CREDENTIALS.search(line)]

# ======================================================================================================================
# Tests
# ======================================================================================================================

def test_no_workflow_names_an_image_but_by_the_pinned_service_line():
    """
    The copier by its own rule, every other workflow by D-064's.
    """
    refused = sorted((name, line) for name, (_, lines) in _workflows().items() for line in lines)

    assert refused == []


def compose_judged(text: str) -> tuple[int, list[str]]:
    """
    A compose file's text judged line by line, the rule of the workflows narrowed to an ``image`` key, since a stack
    also names the variable ``E2E_IMAGE_TARGET``.

    Args:
        text: A compose file's text

    Returns:
        tuple[int, list[str]]: How many pinned image lines it holds, and every other line that names an image key,
            in any quoting or inside a flow mapping, or holds an escape, each refused
    """
    pinned, refused = 0, []
    for line in text.splitlines():
        if COMMENT.match(line):
            continue
        if ESCAPE.search(line):
            refused.append(line.strip())
        elif re.search(r"""["']?\bimage\b["']?\s*:""", line, re.IGNORECASE):
            if COMPOSE_IMAGE.match(line):
                pinned += 1
            else:
                refused.append(line.strip())
    return pinned, refused


def test_the_e2e_stack_pulls_every_image_by_digest_and_none_from_docker_hub():
    """
    A release's E2E journey pulls these on a runner, the postgres, both caddy edges and mailpit (D-065).
    """
    assert compose_judged(SHARED_COMPOSE.read_text(encoding = "utf-8")) == (4, [])


@pytest.mark.parametrize(
    "line",
    [
        "    image: postgres:16-alpine",
        "    'image': postgres:16-alpine",
        '    "image": postgres:16-alpine',
        "    Image: postgres:16-alpine",
        "  db: {image: postgres:16-alpine}",
        f"    image: {GOOD} # postgres",
        '    "\\x69mage": postgres:16-alpine',
        "    ? image\n    : postgres:16-alpine",
    ],
)
def test_the_e2e_stack_refuses_a_docker_hub_image_in_any_quoting(line):
    """
    A review of D-065 found a quoted key passing a reading of ``image:`` alone.
    """
    assert compose_judged(f"services:\n{line}\n")[1] != []


def test_the_postgres_services_name_one_image_each_and_the_same_one():
    """
    Every lane names the same digest, one the copier keeps, and the copier's verify job the newest (D-077).
    """
    images = {name: found for name, (found, _) in _workflows().items() if found}

    assert stage_faults(images, kept_digests(_text(COPIER))) == []


def proof_held(ci: str, version: str) -> bool:
    """
    Whether a ci.yml holds the lanes' proof whole, expecting this ``server_version_num``.
    """
    jobs = blocks(block(blocks(ci.splitlines(), 0), "jobs")[1:], 2)
    return block(jobs, LANE_PROOF) == [line.replace("{version}", version) for line in LANE_PROOF_JOB]


def _lanes_version() -> str:
    """
    The ``server_version_num`` of the kept entry the lanes' one digest names, or none.
    """
    lanes   = {digest(image) for name, (found, _) in _workflows().items() if name != COPIER for image in found}
    matched = [KEPT_ENTRY.match(entry) for entry in kept_entries(_text(COPIER))]
    entries = {entry["digest"]: entry["version"] for entry in matched if entry}
    return entries.get(next(iter(lanes)), "") if len(lanes) == 1 else ""


def test_the_lane_proof_calls_the_integration_lane_and_expects_the_version_of_the_lanes_digest():
    """
    The lane is proven on cicd's own pull request before any caller meets it (D-077). A bump moves each lane's digest
    and the version the proof expects together, so a lane moved to an entry the copier has not copied fails its own
    pull request's proof, on the missing image. It waits for the scan as a lane's caller does and names no secret, so
    it runs for a fork's pull request too.
    """
    version = _lanes_version()

    assert version and proof_held(_text("ci.yml"), version)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # from Codex's read, a test command that never queries Postgres, and its connection or failure chain loosened
        ("        number=\"$(PGPASSWORD=kdf psql", "        number=160015 && true \"$(PGPASSWORD=kdf psql"),
        (" -h 127.0.0.1 -p 5432 ", " "),
        (" -v ON_ERROR_STOP=1 ", " "),
        ("$number\" &&\n        test", "$number\" ;\n        test"),
        # another version, an install that runs code, a secret, or no wait for the scan
        ('        test "$number" = ', '        test "$number" = 1'),
        ("      install_command: echo nothing to install\n", "      install_command: pip install -r requirements.in\n"),
        (
            "    uses: ./.github/workflows/ci-python-integration.yml\n",
            "    uses: ./.github/workflows/ci-python-integration.yml\n    secrets: inherit\n",
        ),
        (
            "    if: ${{ !cancelled() }}\n    uses: ./.github/workflows/ci-python-integration",
            "    uses: ./.github/workflows/ci-python-integration",
        ),
    ],
)
def test_a_lane_proof_out_of_its_shape_is_refused(old, new):
    text = _text("ci.yml")
    assert old in text, "each case changes a line the proof holds"

    assert not proof_held(text.replace(old, new, 1), _lanes_version())


@pytest.mark.parametrize(
    ("lanes", "verify"),
    [
        # every lane on a digest the copier does not keep, a lane moved before its copy
        ((f"sha256:{'c' * 64}",) * 3, NEWEST),
        # the lanes on two digests
        ((OLDER, OLDER, NEWEST), NEWEST),
        # the verify job on an older entry than the newest
        ((OLDER,) * 3, OLDER),
        # a lane with no service, or with two
        ((OLDER, OLDER), NEWEST),
    ],
)
def test_a_lane_digest_not_kept_or_a_verify_job_not_on_the_newest_is_refused(lanes, verify):
    names  = [name for name in WITH_POSTGRES if name != COPIER]
    images = {name: [f"{LANE_IMAGE}@{found}"] for name, found in zip(names, lanes)}
    images[COPIER] = [f"{MIRROR}@{verify}"]

    assert stage_faults(images, [OLDER, NEWEST]) != []


@pytest.mark.parametrize("lanes", [OLDER, NEWEST])
def test_a_bumps_stages_pass_the_lanes_on_any_kept_entry_and_verify_on_the_newest(lanes):
    """
    A bump appends an entry and moves verify to it first, the lanes on the older one until their own pull request.
    """
    images = {name: [f"{LANE_IMAGE}@{lanes}"] for name in WITH_POSTGRES if name != COPIER}
    images[COPIER] = [f"{MIRROR}@{NEWEST}"]

    assert stage_faults(images, [OLDER, NEWEST]) == []


@pytest.mark.parametrize(
    "image",
    [
        "postgres:16",
        "postgres@sha256:" + "a" * 64,
        "docker.io/library/postgres@sha256:" + "a" * 64,
        "mirror.gcr.io/library/postgres@sha256:" + "a" * 64,
        "public.ecr.aws/someone/postgres@sha256:" + "a" * 64,
        "ghcr.io/someone/postgres@sha256:" + "a" * 64,
        f"{LANE_IMAGE}:16",
        f"{LANE_IMAGE}:16@sha256:" + "a" * 64,
        f"{LANE_IMAGE}@sha256:" + "A" * 64,
        f"{LANE_IMAGE}@sha256:" + "a" * 63,
        # the other of the two images the lanes move between, the mirror while the constant names ECR Public
        *(f"{image}@sha256:" + "a" * 64 for image in (ECR_PUBLIC, MIRROR) if image != LANE_IMAGE),
    ],
)
def test_a_tag_a_bare_name_or_another_host_is_refused(image):
    assert not LANE_PINNED.match(image)


@pytest.mark.parametrize(
    "text",
    [
        f"    services:\n      postgres:\n        image: {HUB}\n",
        f"    services:\n      postgres:\n        image: {HUB} # the old source\n",
        f"    services:\n      postgres:\n        image: {GOOD} # postgres 16.15\n",
        f'    services:\n      postgres:\n        image: "{HUB}"\n',
        f"    services:\n      postgres:\n        'image': {HUB}\n",
        f'    services:\n      extra: {{image: "{HUB}"}}\n',
        f"    services:\n      extra: {{ports: [5432], image: {HUB}}}\n",
        f"    services:\n      postgres: {{env: {{image: {GOOD}}}, image: {HUB}}}\n",
        f"    container: {HUB}\n",
        f'    job: {{"container":"{HUB}"}}\n',
        f'    "\\u0063ontainer": {HUB}\n',
        f'    "\\x69mage": {HUB}\n',
        f"    container:\n      image: {HUB}\n",
        f"    container:\n      {HUB}\n",
        f"    services:\n      postgres:\n        image:\n          {HUB}\n",
        f"    services:\n      postgres:\n        image: >-\n          {HUB}\n",
        "    services:\n      postgres:\n        image: *pg\n",
        f"    services:\n      postgres:\n        Image: {HUB}\n",
        f"      - uses: docker://{HUB}\n",
        f"      - uses: 'docker://{GOOD}'\n",
        f"      - run: docker pull {HUB}\n",
        f"      - run: |\n          docker run --rm {HUB} pg_dump\n",
        f"    services:\n      postgres:\n        ? image\n        : {HUB}\n",
        # a lane on the other of the two images, the mirror while the constant names ECR Public (D-077)
        *(
            f"    services:\n      postgres:\n        image: {image}@sha256:{'a' * 64}\n"
            for image in (ECR_PUBLIC, MIRROR) if image != LANE_IMAGE
        ),
    ],
)
def test_every_other_way_of_naming_or_pulling_an_image_is_refused(text):
    """
    Each form a runner would pull from, or a form this rule does not know. Two reviews of D-064 found a reading of
    the values passing a comment after the image, a flow mapping, a job's container, a second key on one line, a
    key without a space after its colon and an escaped key, all on Docker Hub.
    """
    _, refused = judged(text)

    assert refused != []


@pytest.mark.parametrize(
    "text",
    [
        f"    services:\n      postgres:\n        image: {GOOD}\n",
        f"    services:\n      postgres:\n        image: {GOOD}  \n        env:\n          POSTGRES_USER: kdf\n",
        f"    # the official image, not a key\n    services:\n      postgres:\n        image: {GOOD}\n",
    ],
)
def test_the_pinned_service_line_passes(text):
    images, refused = judged(text)

    assert (images, refused) == ([GOOD], [])

# ======================================================================================================================
# The copier (D-077, D-080)
# ======================================================================================================================

def test_the_copier_holds_its_own_rule():
    """
    Its triggers, its main guard, each job's declared permissions and condition, its needs, no action, its target,
    its entries in their shapes, its scripts' held lines, its every line that names an image or a pull, and its verify
    job on the newest kept entry. The cases it refuses are in test_mirror_ci_images.py.
    """
    text = _text(COPIER)

    assert copier_judged(text) == ([f"{MIRROR}@{kept_digests(text)[-1]}"], [])

# ======================================================================================================================
# Credentials and the grant to write a package (D-077)
# ======================================================================================================================

def test_no_workflow_names_a_credentials_key():
    """
    A hosted runner already logs in to GitHub's registry with the job's own token, and a credential named in a lane
    would sit in a job that runs a pull request's code (D-035).
    """
    named = sorted((name, line) for name in _names() for line in credentials_keys(_text(name)))

    assert named == []


@pytest.mark.parametrize(
    "text",
    [
        "        credentials:\n          username: ${{ github.actor }}\n",
        '        "credentials": {username: a}\n',
        "        'Credentials':\n",
        "      postgres: {image: x, credentials: {username: a}}\n",
        "      postgres: {image: x, credentials:{username: a}}\n",
        "        CREDENTIALS:\n",
    ],
)
def test_a_credentials_key_in_any_quoting_is_refused(text):
    assert credentials_keys(text) != []


@pytest.mark.parametrize(
    "text",
    [
        "        with:\n          persist-credentials: false\n",
        '              echo "The weekly expiry monitor flagged these credentials:"\n',
        "      # a login's credentials: none here\n",
    ],
)
def test_a_checkouts_input_or_a_word_in_a_message_is_not_a_credentials_key(text):
    assert credentials_keys(text) == []


def test_no_workflow_declares_a_grant_that_can_write_a_package_but_the_copiers_copy_job():
    """
    The one declared grant, the copier's copy job's own, which checks out nothing and runs no action.
    """
    grants = sorted((name, scope, line) for name in _names() for scope, line in package_grants(_text(name)))

    assert grants == [(COPIER, "copy", "packages: write")]


@pytest.mark.parametrize(
    "text",
    [
        # at the workflow's scope
        "permissions:\n  packages: write\njobs:\n  copy:\n    runs-on: ubuntu-latest\n",
        "permissions: write-all\njobs:\n  copy:\n    runs-on: ubuntu-latest\n",
        # at a job's, in each form YAML allows
        "jobs:\n  lane:\n    permissions:\n      packages: write\n",
        "jobs:\n  lane:\n    permissions: write-all\n",
        'jobs:\n  lane:\n    permissions: "write-all"\n',
        "jobs:\n  lane:\n    permissions: Write-All\n",
        "jobs:\n  lane:\n    permissions: {packages: write}\n",
        "jobs:\n  lane:\n    permissions: {contents: read, packages: write}\n",
        'jobs:\n  lane:\n    permissions:\n      "packages": write\n',
        "jobs:\n  lane:\n    permissions:\n      'packages': 'write'\n",
        "jobs:\n  lane:\n    permissions:\n      Packages: WRITE\n",
        "jobs:\n  lane:\n    permissions:\n      packages:\n        write\n",
        'jobs:\n  lane:\n    permissions:\n      "\\x70ackages": write\n',
        "jobs:\n  lane:\n    permissions:\n      ? packages\n      : write\n",
    ],
)
def test_a_grant_that_can_write_a_package_in_any_form_is_found(text):
    assert package_grants(text) != []


def test_the_copiers_grant_is_refused_in_a_proof_job_or_at_its_workflows_scope():
    """
    The first job permissions of none is the verify job's, and the workflow's sits above its concurrency group.
    """
    text = _text(COPIER)
    top  = "permissions: {}\n\n# a whole run holds it"
    assert "    permissions: {}\n" in text and top in text

    in_verify   = package_grants(text.replace("    permissions: {}\n", "    permissions:\n      packages: write\n", 1))
    in_workflow = package_grants(text.replace(top, "permissions:\n  packages: write\n\n# a whole run holds it", 1))

    assert ("verify", "packages: write") in in_verify
    assert ("workflow", "packages: write") in in_workflow


@pytest.mark.parametrize(
    "text",
    [
        "jobs:\n  lane:\n    permissions:\n      packages: read\n",
        "jobs:\n  lane:\n    permissions: {contents: read, packages: none}\n",
        "jobs:\n  lane:\n    permissions:\n      contents: write\n",
        "jobs:\n  lane:\n    steps:\n      - uses: ./.github/workflows/fetch-private-packages.yml\n",
    ],
)
def test_a_grant_that_cannot_write_a_package_is_not_found(text):
    assert package_grants(text) == []
