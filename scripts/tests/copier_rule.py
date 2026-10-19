"""
The copier's strict rule, and the reading of a workflow's text it is built on (D-064, D-077, D-080).

The copier, ``mirror-ci-images.yml``, copies every image CI pulls to the owner's mirror on GitHub's registry and
proves each public. It names ``docker://`` and ``skopeo`` by design, so it is read by a rule of its own. Its triggers
with their one schedule, its concurrency, its ``main`` guard, each job's declared permissions and condition, its
``needs``, the copy job's outputs, its service and its target are each held whole, a key's line and every line below
it, no action at all. Its sources, kept, pinned, followed and watched entries are each held to their exact shape, every
source on a known host and path, every destination tag unique. Its every other line that names an image or a pull is
one this rule knows, its blob comparison and its tamper check are present as written, and none of its names is set in
a step's env or by a script's assignment.

``test_workflow_service_images.py`` holds every workflow to its rule, the copier to this one, and
``test_mirror_ci_images.py`` holds the cases this rule refuses and runs the copier's two scripts under stubs. A module
of its own, so neither test passes the house style's length.
"""

from __future__ import annotations

import re
import textwrap

# ======================================================================================================================
# Constants
# ======================================================================================================================

# a YAML escape that can spell a letter of a key, or an explicit key, `?`, which puts a key's value on another line
ESCAPE: re.Pattern[str] = re.compile(r"\\[xuU]|^\s*\?(\s|$)")

# a whole line comment
COMMENT: re.Pattern[str] = re.compile(r"^\s*#")

# the keys that call an action or check a repository out, in any quoting
USES: re.Pattern[str] = re.compile(r"""(?<![\w-])["']?uses["']?\s*:|actions/checkout""", re.IGNORECASE)

# the copier of D-077 and D-080, the namespace it writes and the lanes' package on it
COPIER:    str = "mirror-ci-images.yml"
NAMESPACE: str = "ghcr.io/needless2say"
MIRROR:    str = f"{NAMESPACE}/postgres"

# the copier's words, the lanes' and skopeo's, and the one line beside its known ones that may name an image there,
# its verify job's service on the mirror by a digest
COPIER_NAMING: re.Pattern[str] = re.compile(r"image|container|docker|skopeo", re.IGNORECASE)
COPIER_IMAGE:  re.Pattern[str] = re.compile(rf"^\s+image: (?P<image>{re.escape(MIRROR)}@sha256:[0-9a-f]{{64}})\s*$")

# the seven hosts and paths a source may name, each followed by its entry's package. Docker's official images on ECR
# Public's gallery, Docker Hub and Google's mirror, and Mailpit's and Checkov's publishers on GitHub's registry and on
# Docker Hub. A mirror serves bytes by a digest already chosen, and never answers for a tag or a watched line
SOURCE_PATHS: tuple[str, ...] = (
    "public.ecr.aws/docker/library",
    "docker.io/library",
    "mirror.gcr.io/library",
    "ghcr.io/axllent",
    "docker.io/axllent",
    "ghcr.io/bridgecrewio",
    "docker.io/bridgecrew",
)
MIRRORS:      tuple[str, ...] = ("public.ecr.aws/", "mirror.gcr.io/")
OFFICIAL:     str = "docker.io/library"

# each entry's exact shape (D-080). A kept entry, its index digest, its tag and its server_version_num. A source line,
# its package and its sources. A pinned entry, its package, its index digest and its tag. A followed tag, its package,
# its tag and a held digest while a hold stands. A watched line, a kept or pinned image's package and tag, its
# publisher, its line's upstream tag and the level a newer version is reported at
KEPT_ENTRY:     re.Pattern[str] = re.compile(
    r"^    (?P<digest>sha256:[0-9a-f]{64}) (?P<tag>[0-9][0-9.]*) (?P<version>[0-9]{6})$",
)
SOURCE_ENTRY:   re.Pattern[str] = re.compile(r"^    (?P<name>[a-z0-9-]+)(?P<sources>(?: [a-z0-9./-]+)+)$")
PINNED_ENTRY:   re.Pattern[str] = re.compile(
    r"^    (?P<name>[a-z0-9-]+) (?P<digest>sha256:[0-9a-f]{64}) (?P<tag>[0-9a-z][0-9a-z.-]*)$",
)
FOLLOWED_ENTRY: re.Pattern[str] = re.compile(
    r"^    (?P<name>[a-z0-9-]+) (?P<tag>[0-9][0-9a-z.-]*)(?: (?P<hold>sha256:[0-9a-f]{64}))?$",
)
WATCH_SHAPE:    str = (
    r"^    (?P<name>[a-z0-9-]+) (?P<tag>[0-9a-z][0-9a-z.-]*) (?P<publisher>[a-z0-9./-]+)"
    r" (?P<upstream>[0-9a-z][0-9a-z.-]*) (?P<level>patch|minor)$"
)
WATCH_ENTRY:    re.Pattern[str] = re.compile(WATCH_SHAPE)

# Docker Hub's anonymous pull token and its HEAD for a tag or a digest, held as written in both scripts, since a host
#   changed to a mirror's would name none of the words the rule below looks for
TOKEN_LINE: str = (
    "token=\"$(curl -fsS --max-time 30 \"https://auth.docker.io/token?service=registry.docker.io&scope=repository:"
    "library/$name:pull\" | jq -r '.token // empty')\" || token=\"\""
)
HEAD_LINE:  str = (
    "code=\"$(curl -sS --max-time 30 --head -o /dev/null -D \"$raw.head\" -w '%{http_code}' -H \"Authorization: Bearer"
    " $token\" -H \"Accept: $index_types\" \"https://registry-1.docker.io/v2/library/$name/manifests/$reference\")\" ||"
    " true"
)

# the blob comparison's two anonymous fetches with no blob, the run's own commit and main's, each into a ref of its own
FETCH_RUN:  str = (
    '&& git -C "$work" -c credential.helper= fetch -q --depth 1 --filter=blob:none --no-tags "$origin"'
    ' "+$GITHUB_SHA:refs/kdf/run" \\'
)
FETCH_MAIN: str = (
    '&& git -C "$work" -c credential.helper= fetch -q --depth 1 --filter=blob:none --no-tags "$origin"'
    ' "+refs/heads/main:refs/kdf/main"; then'
)

# the copier's every other line that names an image or a pull, each read whole, its sources and watched lines judged
# by their shapes instead. Another source, a digest written in, another target or a followed tag read from a mirror is
# a line this set does not hold, so a change to any of them changes this rule with it
COPIER_KNOWN: frozenset[str] = frozenset({
    "name: Mirror CI images",
    "paths: [.github/workflows/mirror-ci-images.yml]",
    "group: mirror-ci-images-copy",
    "COPIER: .github/workflows/mirror-ci-images.yml",
    "verify-images:",
    "name: Prove every image public and present",
    "run: printf '%s' \"$REGISTRY_TOKEN\" | skopeo login --username \"$GITHUB_ACTOR\" --password-stdin ghcr.io",
    "index_types='application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json'",
    "application/vnd.oci.image.index.v1+json | application/vnd.docker.distribution.manifest.list.v2+json) ;;",
    'skopeo inspect --raw "docker://$ref@$digest" > "$raw.index" || return 1',
    'skopeo inspect --raw "docker://$ref@$listed" > "$raw.one" || return 1',
    'timeout 900 skopeo copy "docker://$ref@$digest" "dir:$pull" > /dev/null || return 1',
    'skopeo inspect --raw "docker://$1:$2" > "$raw.tag" || return 1',
    "when=\"$(skopeo inspect --format '{{.Created}}' \"docker://$1@$2\" 2> /dev/null)\" || when=\"\"",
    TOKEN_LINE,
    HEAD_LINE,
    "answer=\"$(tr -d '\\r' < \"$raw.head\" | grep -i '^docker-content-digest:' | tail -n 1 | cut -d ' ' -f 2-)\"",
    'if timeout 900 skopeo copy --all --preserve-digests --src-no-creds "docker://$source@$digest"'
    ' "docker://$TARGET/$name:$tag"; then',
    'if ! timeout 900 skopeo copy --all --preserve-digests --src-no-creds "docker://$ref@$hold" "docker://$ref:$tag"'
    ' || ! placed "$ref" "$tag" "$hold"; then',
    'echo "::warning::$ref:$tag is held on $hold while Docker Hub names $answer"',
    "echo \"::warning::$ref:$tag is held on $hold, and Docker Hub's digest for it was not read, answer $code\"",
    "failed refused \"Docker Hub did not name $name:$tag's index, answer $code, so $ref:$tag is left as it is\"",
    'echo "Docker Hub names $name:$tag $wanted"',
    'if skopeo inspect --raw "docker://$ref:$tag" > "$raw.tag" 2> /dev/null; then',
    'echo "$ref:$tag held $mirrored, a digest Docker Hub serves for $name, and moves to $wanted"',
    'echo "$ref:$tag held $mirrored, which Docker Hub does not serve for $name, recorded here"',
    "echo \"::warning::$ref:$tag held $mirrored, and Docker Hub's answer for it decides nothing, answer $code\"",
    'elif ! skopeo inspect --raw "docker://$ref@$wanted" > "$raw.index" \\',
    "|| [[ ! \"$(jq -r '.mediaType // empty' \"$raw.index\")\" =~"
    " ^application/vnd\\.(oci\\.image\\.index\\.v1|docker\\.distribution\\.manifest\\.list\\.v2)\\+json$ ]]; then",
    "failed tamper \"a possible tamper or a digest Docker Hub no longer serves, $ref:$tag held $tampered. Read the"
    " recorded digest and the package's access\"",
    'skopeo inspect --raw --no-creds "docker://$ref@$digest" > "$raw.index" || return 1',
    'skopeo inspect --raw --no-creds "docker://$ref@$listed" > "$raw.one" || return 1',
    'timeout 900 skopeo copy --src-no-creds "docker://$1@$2" "dir:$pull" > /dev/null || return 1',
    'if ! skopeo inspect --raw --no-creds "docker://$ref:$tag" > "$raw.tag"; then',
    'echo "$ref:$tag is on $found, a digest Docker Hub serves for $name"',
    "failed tamper \"a possible tamper or a digest Docker Hub no longer serves, $ref:$tag is on $found. Read the"
    " recorded digest and the package's access\"",
    "echo \"::warning::$ref:$tag is on $found, and Docker Hub's answer for it decides nothing, answer $code\"",
})

# The lines each script holds as written, which name none of the words the rule above looks for. The copy step's blob
#   comparison, its gate on holds and follows, its tamper check and its outputs, and the proof's gate, its hold and
#   its tamper check, so a step without one of them is refused (D-080)
COPY_STEP:      str = "Copy, hold and follow every entry"
COPY_REQUIRED:  tuple[str, ...] = (
    'if git init -q "$work" \\',
    FETCH_RUN,
    FETCH_MAIN,
    'run_blob="$(git -C "$work" rev-parse --verify --quiet "refs/kdf/run:$COPIER")" || run_blob=""',
    'main_blob="$(git -C "$work" rev-parse --verify --quiet "refs/kdf/main:$COPIER")" || main_blob=""',
    'if [[ ! "$run_blob" =~ ^[0-9a-f]{40}$ ]] || [[ ! "$main_blob" =~ ^[0-9a-f]{40}$ ]]; then',
    'elif [ "$run_blob" = "$main_blob" ]; then',
    'if [[ ! "${GITHUB_RUN_ATTEMPT:-}" =~ ^1$ ]]; then',
    'if [ -z "$name" ] || [ -z "${hold:-}" ] || [ "$gate" != current ]; then continue; fi',
    'if [ -z "$name" ] || [ -n "${hold:-}" ] || [ "$gate" != current ]; then continue; fi',
    'if hub_head "$name" "$mirrored" && [ "$answer" = "$mirrored" ]; then',
    'elif [ "$code" = 404 ]; then',
    TOKEN_LINE,
    HEAD_LINE,
    'tampered="$mirrored"',
    'if [ -n "$tampered" ]; then',
    'echo "gate=$gate" >> "$GITHUB_OUTPUT"',
    'echo "chosen=${chosen# }" >> "$GITHUB_OUTPUT"',
)
PROOF_STEP:     str = "Read and pull every entry with no credentials"
PROOF_REQUIRED: tuple[str, ...] = (
    'if [ "$GATE" = current ]; then',
    '[ -n "$decide" ] || continue',
    'elif [ -n "${hold:-}" ]; then',
    'elif hub_head "$name" "$found" && [ "$answer" = "$found" ]; then',
    'elif [ "$code" = 404 ]; then',
    TOKEN_LINE,
    HEAD_LINE,
)

# the copier's names, which only its workflow's env sets. A step's env key or a script's assignment that sets one is
# refused, which Codex's read of D-080 found the rule of D-077 passed, but for the one line that reads the sources
OWN_NAMES:      str = "TARGET|COPIER|SOURCES|KEPT|PINNED|FOLLOWED|WATCH|sources"
SET_IN_ENV:     re.Pattern[str] = re.compile(rf"""^\s+["']?(?:{OWN_NAMES})["']?\s*:""")
ASSIGNING:      str = (
    rf"(?<![\w$])(?:(?:export|declare|local|readonly|typeset)\s+(?:-\w+\s+)*)?(?:{OWN_NAMES})(?:\[[^\]]*\])?\+?="
    rf"|\bread\b[^<]*\b(?:{OWN_NAMES})\b|\b(?:for|printf\s+-v)\s+(?:{OWN_NAMES})\b"
)
ASSIGNED:       re.Pattern[str] = re.compile(ASSIGNING)
ASSIGNED_KNOWN: frozenset[str] = frozenset({'[ -n "$name" ] && sources[$name]="$list"'})

# the copier's blocks the rule holds whole, each a key's line and every line below it indented deeper, so a line
# continued or a key added below a blank line changes its block, as Codex's read of D-077 found a substring did not,
# its top level in order, its triggers, a push to main that changes this file, a dispatch with no input and one daily
# schedule, its workflow's permissions, its one concurrency group for a whole run, its env's keys in order, its target
COPIER_TOP:      tuple[str, ...] = (
    "name: Mirror CI images",
    "on:",
    "permissions: {}",
    "concurrency:",
    "env:",
    "jobs:",
)
COPIER_WORKFLOW: dict[str, tuple[str, ...]] = {
    "on": (
        "on:",
        "  push:",
        "    branches: [main]",
        "    paths: [.github/workflows/mirror-ci-images.yml]",
        "  workflow_dispatch:",
        "  schedule:",
        "    - cron: '23 6 * * *'",
    ),
    "permissions": ("permissions: {}",),
    "concurrency": ("concurrency:", "  group: mirror-ci-images-copy", "  cancel-in-progress: false"),
}
COPIER_ENV_KEYS: tuple[str, ...] = ("TARGET", "COPIER", "SOURCES", "KEPT", "PINNED", "FOLLOWED", "WATCH")
COPIER_ENV:      dict[str, tuple[str, ...]] = {
    "TARGET": (f"  TARGET: {NAMESPACE}",),
    "COPIER": ("  COPIER: .github/workflows/mirror-ci-images.yml",),
}

# the copy job's guard, its one grant and its outputs, and each proof job's needs, its condition and no permissions.
# The condition names !cancelled(), since without a status function GitHub adds success() and skips a proof after a
# failed copy (Codex's revision read), and main, so a dispatch on another branch runs neither
COPIER_JOBS:  tuple[str, ...] = ("copy", "verify", "verify-images")
COPIER_COPY:  dict[str, tuple[str, ...]] = {
    "if": ("    if: github.ref == 'refs/heads/main'",),
    "permissions": ("    permissions:", "      packages: write"),
    "outputs": (
        "    outputs:",
        "      gate: ${{ steps.copy.outputs.gate }}",
        "      chosen: ${{ steps.copy.outputs.chosen }}",
    ),
}
COPIER_PROOF: dict[str, tuple[str, ...]] = {
    "needs": ("    needs: copy",),
    "if": (
        "    if: >-",
        "      !cancelled() && github.ref == 'refs/heads/main' &&",
        "      (needs.copy.result == 'success' || needs.copy.result == 'failure')",
    ),
    "permissions": ("    permissions: {}",),
}

# the verify job's one service, the lanes' own with the newest kept entry on the mirror and no credentials
VERIFY_SERVICE: tuple[str, ...] = (
    "    services:",
    "      postgres:",
    "        image: {image}",
    "        env:",
    "          POSTGRES_USER: kdf",
    "          POSTGRES_PASSWORD: kdf",
    "          POSTGRES_DB: kdf_test",
    "        ports:",
    "          - 5432:5432",
    "        options: >-",
    '          --health-cmd "pg_isready -U kdf -d kdf_test"',
    "          --health-interval 5s",
    "          --health-timeout 5s",
    "          --health-retries 15",
)

# ======================================================================================================================
# A workflow's text
# ======================================================================================================================

def blocks(lines: list[str], indent: int) -> list[tuple[str, list[str]]]:
    """
    A mapping written at one indent, each key with its own lines.

    Args:
        lines: The mapping's lines
        indent: How many spaces its keys sit in

    Returns:
        list[tuple[str, list[str]]]: Each key in order, its quotes taken off, with its line and every line below it
            indented deeper, a comment among them, so a line continued or a key added below a blank line stays in its
            block. A blank line is left out, and so is a comment at the indent itself, which sits above a key
    """
    found: list[tuple[str, list[str]]] = []
    for line in lines:
        if not line.strip():
            continue
        depth = len(line) - len(line.lstrip(" "))
        if depth > indent and found:
            found[-1][1].append(line)
        elif depth == indent and not COMMENT.match(line):
            found.append((line.split(":", 1)[0].strip().strip("\"'"), [line]))
    return found


def block(found: list[tuple[str, list[str]]], key: str) -> list[str]:
    """
    One key's lines in a mapping, the first block it opens, or none.
    """
    return next((lines for name, lines in found if name == key), [])


def held(where: str, found: list[tuple[str, list[str]]], expected: dict[str, tuple[str, ...]]) -> list[str]:
    """
    Where a mapping writes a key twice, or a block the rule holds whole is not the one it holds.
    """
    keys   = [key for key, _ in found]
    faults = [f"{where} writes {key} more than once" for key in sorted(set(keys)) if keys.count(key) > 1]
    faults += [
        f"{where}'s {key} is {block(found, key)}, not {list(lines)}"
        for key, lines in expected.items()
        if tuple(block(found, key)) != lines
    ]
    return faults


def env_entries(text: str, key: str) -> list[str]:
    """
    One of the copier's env blocks, each line below its key as written, or none when the key opens no block.
    """
    env   = blocks(block(blocks(text.splitlines(), 0), "env")[1:], 2)
    found = block(env, key)
    return found[1:] if found[:1] == [f"  {key}: |"] else []


def kept_entries(text: str) -> list[str]:
    """
    The copier's kept entries, each line of its KEPT block below the key as written, the newest last.
    """
    return env_entries(text, "KEPT")


def kept_digests(text: str) -> list[str]:
    """
    The copier's kept digests, the newest last, each entry that holds its digest, its tag and its server_version_num.
    """
    return [entry.group("digest") for entry in map(KEPT_ENTRY.match, kept_entries(text)) if entry]


def pinned_pairs(text: str) -> set[tuple[str, str]]:
    """
    The copier's pinned entries, each its package and its digest.
    """
    return {(entry["name"], entry["digest"]) for entry in map(PINNED_ENTRY.match, env_entries(text, "PINNED")) if entry}


def step_script(text: str, job: str, step: str) -> str:
    """
    One step's ``run: |`` script in a workflow's text, its lines below the key with their indent taken off, or none.
    """
    jobs  = blocks(block(blocks(text.splitlines(), 0), "jobs")[1:], 2)
    lines = block(jobs, job)
    start = next((index for index, line in enumerate(lines) if line.strip() == f"- name: {step}"), None)
    if start is None:
        return ""
    run = next((index for index in range(start, len(lines)) if lines[index].strip() == "run: |"), None)
    if run is None:
        return ""
    depth = len(lines[run]) - len(lines[run].lstrip(" "))
    body  = []
    for line in lines[run + 1:]:
        if len(line) - len(line.lstrip(" ")) <= depth:
            break
        body.append(line)
    return textwrap.dedent("\n".join(body)) + "\n"

# ======================================================================================================================
# The copier's rule
# ======================================================================================================================

def sources_of(text: str) -> tuple[dict[str, list[str]], list[str]]:
    """
    The copier's sources by package, and every source line out of its shape, its package written twice, or a source
    that is not one of the seven known hosts and paths followed by its own package.
    """
    sources, faults = {}, []
    for line in env_entries(text, "SOURCES"):
        matched = SOURCE_ENTRY.match(line)
        listed  = matched["sources"].split() if matched else []
        allowed = {f"{path}/{matched['name']}" for path in SOURCE_PATHS} if matched else set()
        if not matched or matched["name"] in sources or len(set(listed)) != len(listed) or set(listed) - allowed:
            faults.append(f"a source line out of its shape or outside the seven known hosts and paths, {line.strip()}")
            continue
        sources[matched["name"]] = listed
    if not sources:
        faults.append("the copier names no sources")
    return sources, faults


def entries_faults(text: str) -> list[str]:
    """
    Where the copier's entries leave their shapes (D-080).

    Args:
        text: The copier's text

    Returns:
        list[str]: Each fault. A source out of its shape or on an unknown host or path, a pinned, followed or watched
            entry out of its shape or naming a package with no sources, a followed tag that is not Docker's official
            image, a destination tag two entries hold, and a watched line that names no kept or pinned image, asks a
            mirror or another publisher, or leaves a kept or pinned image unwatched
    """
    sources, faults = sources_of(text)
    kept     = [("postgres", entry["tag"]) for entry in map(KEPT_ENTRY.match, kept_entries(text)) if entry]
    pinned   = [PINNED_ENTRY.match(line) for line in env_entries(text, "PINNED")]
    followed = [FOLLOWED_ENTRY.match(line) for line in env_entries(text, "FOLLOWED")]
    watched  = [WATCH_ENTRY.match(line) for line in env_entries(text, "WATCH")]
    for key, matched in (("PINNED", pinned), ("FOLLOWED", followed), ("WATCH", watched)):
        if not matched or not all(matched):
            faults.append(f"{key} holds no entry, or one out of its exact shape")
    pinned, followed, watched = (list(filter(None, found)) for found in (pinned, followed, watched))

    faults += [f"{entry['name']} has no sources" for entry in pinned if entry["name"] not in sources]
    faults += [
        f"{entry['name']} {entry['tag']} is not Docker's official image on Docker Hub, which alone names a tag"
        for entry in followed if f"{OFFICIAL}/{entry['name']}" not in sources.get(entry["name"], [])
    ]
    destinations = [*kept, *((entry["name"], entry["tag"]) for entry in (*pinned, *followed))]
    faults += [
        f"the destination tag {name}:{tag} is held by more than one entry"
        for name, tag in sorted(set(destinations)) if destinations.count((name, tag)) > 1
    ]

    keepers = {*kept, *((entry["name"], entry["tag"]) for entry in pinned)}
    seen    = set()
    for entry in watched:
        pair = (entry["name"], entry["tag"])
        if pair not in keepers or pair in seen or entry["publisher"] not in sources.get(entry["name"], []) or (
            entry["publisher"].startswith(MIRRORS)
        ):
            faults.append(
                f"a watched line names no kept or pinned image once, or asks other than its publisher, {pair}",
            )
        seen.add(pair)
    faults += [f"{name}:{tag} has no watched line" for name, tag in sorted(keepers - seen)]
    return faults


def _shaped(lines: list[str]) -> set[int]:
    """
    The indexes of the copier's source and watched lines, each judged by its shape rather than by the known set.
    """
    shaped, inside = set(), False
    for index, line in enumerate(lines):
        if line in ("  SOURCES: |", "  WATCH: |"):
            inside = True
        elif inside and line.startswith("    "):
            shaped.add(index)
        elif line.strip():
            inside = False
    return shaped


def _scripts_faults(text: str, lines: list[str]) -> list[str]:
    """
    Where the copier's jobs set one of its own names, in a step's env or by a script's assignment, or where a script
    lacks a line it holds as written.
    """
    start  = lines.index("jobs:") if "jobs:" in lines else len(lines)
    faults = [
        f"a job sets one of the copier's own names, {line.strip()}"
        for line in lines[start:]
        if not COMMENT.match(line) and line.strip() not in ASSIGNED_KNOWN and (
            SET_IN_ENV.match(line) or ASSIGNED.search(line)
        )
    ]
    for job, step, required in (("copy", COPY_STEP, COPY_REQUIRED), ("verify-images", PROOF_STEP, PROOF_REQUIRED)):
        script = {line.strip() for line in step_script(text, job, step).splitlines()}
        faults += [f"the {job} job's script lacks {line}" for line in required if line not in script]
    return faults


def copier_judged(text: str) -> tuple[list[str], list[str]]:
    """
    The copier's text judged by its own rule (D-077, D-080).

    Args:
        text: The copier's text

    Returns:
        tuple[list[str], list[str]]: The images its service line names, and every fault, a line that names an image
            or a pull and is not known, an escape, an entry out of its shape, a name set outside the workflow's env,
            a line a script must hold and lacks, or a part of its shape that is not the rule's
    """
    images, refused = [], []
    lines  = text.splitlines()
    shaped = _shaped(lines)
    for index, line in enumerate(lines):
        if COMMENT.match(line):
            continue
        if ESCAPE.search(line) or USES.search(line):
            refused.append(line.strip())
            continue
        if index in shaped or not COPIER_NAMING.search(line) or line.strip() in COPIER_KNOWN:
            continue
        matched = COPIER_IMAGE.match(line)
        if matched:
            images.append(matched.group("image"))
        else:
            refused.append(line.strip())

    top = blocks(lines, 0)
    env = blocks(block(top, "env")[1:], 2)
    if [found[0] for _, found in top] != list(COPIER_TOP):
        refused.append(f"the top level is {[found[0] for _, found in top]}")
    if [key for key, _ in env] != list(COPIER_ENV_KEYS):
        refused.append(f"the env's keys are {[key for key, _ in env]}")
    refused += held("the workflow", top, COPIER_WORKFLOW)
    refused += held("its env", env, COPIER_ENV)
    refused += entries_faults(text)
    refused += _scripts_faults(text, lines)

    entries = kept_entries(text)
    digests = kept_digests(text)
    if not entries or len(digests) != len(entries) or len(set(digests)) != len(digests):
        refused.append(f"the kept entries are not each a digest, a tag and a server_version_num, once {entries}")
    newest = f"{MIRROR}@{digests[-1]}" if digests else ""

    jobs = blocks(block(top, "jobs")[1:], 2)
    if [key for key, _ in jobs] != list(COPIER_JOBS):
        refused.append(f"the jobs are {[key for key, _ in jobs]}")
    service = tuple(line.replace("{image}", newest) for line in VERIFY_SERVICE)
    proof   = blocks(block(jobs, "verify-images")[1:], 4)
    refused += held("the copy job", blocks(block(jobs, "copy")[1:], 4), COPIER_COPY)
    refused += held("the verify job", blocks(block(jobs, "verify")[1:], 4), {**COPIER_PROOF, "services": service})
    refused += held("the verify-images job", proof, COPIER_PROOF)
    if block(proof, "services"):
        refused.append("the verify-images job starts a service")
    if not newest or images != [newest]:
        refused.append(f"the copier's one service is not the newest kept entry on the mirror, {images}")
    return images, refused
