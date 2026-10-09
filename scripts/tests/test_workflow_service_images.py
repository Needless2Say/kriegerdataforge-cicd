"""
Every image a workflow of this repo starts, held to one source and one exact image (D-064).

A service container's image is pulled by the runner before the job's first step. Pulled from Docker Hub without a
login, it met the anonymous limit every tenant of a runner's address shares, and the job failed before a test ran. So
each is Docker's official image from AWS ECR Public's gallery, pinned by its index digest, which no registry can
change. A tag, a bare name or another host is refused, since a host misspelled to Docker Hub's would pull the same
digest from Docker Hub and pass unseen.

YAML writes an image many ways, a service's key, a job's container, a flow mapping, a quoted or escaped key, a step's
``docker://`` action, and a script can run ``docker`` itself. Two reviews of this test found a reading of the values
missing one more form each time, so the rule is on the text. A workflow line that is not a comment and names
``image``, ``container`` or ``docker``, in any case, must be a service's ``image:`` line with the pinned reference
and nothing else, and no line may hold a ``\\x``, ``\\u`` or ``\\U`` escape, which can spell a key. A new use of an
image, a job's container for one, changes this test with it.

It catches a mistake, not a workflow written to hide a pull. Whoever can edit a workflow can run any code in it, and
a word split by a YAML line continuation, or a pull built in a script from a line that reads as a comment, passes
this reading, as a third review showed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ======================================================================================================================
# Constants
# ======================================================================================================================

WORKFLOWS: Path = Path(__file__).resolve().parents[2] / ".github" / "workflows"

# the one shape an image may take, Docker's official gallery on ECR Public, by an index digest
PINNED_IMAGE: str = r"public\.ecr\.aws/docker/library/[a-z0-9][a-z0-9._-]*@sha256:[0-9a-f]{64}"
PINNED:       re.Pattern[str] = re.compile(rf"^{PINNED_IMAGE}$")

# the one line that may name an image, a service's block key and the pinned reference, nothing after it
IMAGE_LINE: re.Pattern[str] = re.compile(rf"^\s+image: (?P<image>{PINNED_IMAGE})\s*$")

# the words that name an image or pull one, read in any case
NAMING: re.Pattern[str] = re.compile(r"image|container|docker", re.IGNORECASE)

# a YAML escape that can spell a letter of a key
ESCAPE: re.Pattern[str] = re.compile(r"\\[xuU]")

# a whole line comment
COMMENT: re.Pattern[str] = re.compile(r"^\s*#")

# the reusable workflows that start a Postgres service, each once
WITH_POSTGRES: tuple[str, ...] = ("ci-python-integration.yml", "ci-python-mutation.yml", "ci-python-system.yml")

# a pinned reference, and Docker Hub's image, for the forms the cases write
GOOD: str = "public.ecr.aws/docker/library/postgres@sha256:" + "a" * 64
HUB:  str = "postgres:16"

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


def _workflows() -> dict[str, tuple[list[str], list[str]]]:
    """
    Every workflow of this repo judged, by its file name.
    """
    return {
        workflow.name: judged(workflow.read_text(encoding = "utf-8"))
        for workflow in sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])
    }

# ======================================================================================================================
# Tests
# ======================================================================================================================

def test_no_workflow_names_an_image_but_by_the_pinned_service_line():
    refused = sorted((name, line) for name, (_, lines) in _workflows().items() for line in lines)

    assert refused == []


def test_the_postgres_services_name_one_image_each_and_the_same_one():
    images = {name: found for name, (found, _) in _workflows().items() if found}

    assert sorted(images) == sorted(WITH_POSTGRES)
    assert all(len(images[name]) == 1 and "/postgres@sha256:" in images[name][0] for name in WITH_POSTGRES)
    assert len({images[name][0] for name in WITH_POSTGRES}) == 1


@pytest.mark.parametrize(
    "image",
    [
        "postgres:16",
        "postgres@sha256:" + "a" * 64,
        "docker.io/library/postgres@sha256:" + "a" * 64,
        "mirror.gcr.io/library/postgres@sha256:" + "a" * 64,
        "public.ecr.aws/docker/library/postgres:16",
        "public.ecr.aws/docker/library/postgres:16@sha256:" + "a" * 64,
        "public.ecr.aws/someone/postgres@sha256:" + "a" * 64,
        "public.ecr.aws/docker/library/postgres@sha256:" + "A" * 64,
        "public.ecr.aws/docker/library/postgres@sha256:" + "a" * 63,
    ],
)
def test_a_tag_a_bare_name_or_another_host_is_refused(image):
    assert not PINNED.match(image)


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
