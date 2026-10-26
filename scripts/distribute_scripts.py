"""
Check and distribute the ecosystem dev scripts (bump_version.py / check_version.py /
version_targets.py) from the canonical source in kriegerdataforge-cicd/scripts/common/
to every consumer repo's scripts/kdf_scripts/ vendor directory — plus the config edits
that wire them into `make ci` and keep them OUT of tenant lint/style scope.

This is the script-sync sibling of distribute_kit.py (ADR D-013 mirrors the kit's
ADR D-001; the vendored layout is ADR D-014): ONE source of truth (scripts/common/),
ONE registry (scripts_registry.json), owner-gated PRs, built on the shared engine in
common/repo_sync.py. The vendor directory exists because the shipped scripts are only
guaranteed clean under CICD's kdf-fmt/ruff configs — tenant configs vary, so tenants
exclude scripts/kdf_scripts/ and cicd alone governs the style of what it ships.

Synced items (per repo, from the registry):
  - files[]:   the three scripts, vendored byte-identical to scripts/kdf_scripts/.
  - deletes[]: the superseded flat scripts/ copies, removed in the same PR.
  - Makefile ("makefile_patch"): every scripts/<name>.py reference is rewritten to
    scripts/kdf_scripts/<name>.py (covers the `_BUMP :=` line and comments), then the
    `ci-version-check:` recipe block is re-asserted to the canonical thin call, and the
    managed `scan` block of the local code scan (D-085) is written between its two marker
    lines, inserted when absent and replaced whole but for the repo's own SCAN_EXCLUDE and
    SCAN_LIMIT lines, naming the image common/SCAN_IMAGE pins and left alone while it pins
    none. Idempotent; a Makefile without the target, with two scan blocks or with a `scan`
    target outside the block raises PatchError -> NEEDS MANUAL ATTENTION.
  - .github/workflows/kdf-scan-gate.yml: the gate's caller, common/kdf-scan-gate-caller.yml
    whole, once an image is pinned, so a change to it comes only from cicd (design 5.3).
  - kdf-fmt.toml ("kdf_fmt_patch"): appends "scripts/kdf_scripts/" to the top-level
    `exclude` list (creating the key before the first TOML table when absent). A repo
    entry with "skip_kdf_fmt": true has no style lane and carries no kdf-fmt.toml, so the
    patch is not built for it (a missing file would otherwise fail the whole repo).
  - ruff config (per-repo "ruff_config": ruff.toml | pyproject.toml): same exclusion,
    into ruff.toml's `exclude` list or [tool.ruff]'s `extend-exclude`.

Modes:
  check       Read-only drift report. Exits non-zero if any repo is out of sync. OPENS NOTHING.
  distribute  Opens one review-gated PR per drifted repo ("chore(scripts): sync ecosystem
              dev scripts <SCRIPTS_VERSION>"). NEVER auto-merges. When every change in a repo is
              a copy whose registry entry is "pretested": true, each commit carries [skip ci] and
              the PR runs no CI. A patch, a delete or the mutation engine lets CI run (D-047).

IMPORTANT — version-check: scripts-sync PRs do not bump VERSION. The central
scripts/common/check_version.py exempts PRs touching only the registry dest+delete paths
(plus Makefile / kdf-fmt.toml / ruff.toml / pyproject.toml, on chore/scripts-sync-*
branches only), so the sync PRs pass the gate.

Requirements:
    pip install requests

Environment variables:
  GH_TOKEN    GitHub token with contents:read (check) or contents + pull-requests:write
              (distribute) on all target repos. Use the CICD_PAT value.

Usage:
    GH_TOKEN=... python distribute_scripts.py check
    GH_TOKEN=... python distribute_scripts.py check --only check_version.py
    GH_TOKEN=... python distribute_scripts.py distribute
    # Target a subset of repos (comma-separated exact names); blank = all:
    GH_TOKEN=... python distribute_scripts.py distribute --repos kriegerdataforge,tiffanys-space
"""

from __future__ import annotations

# standard imports
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

# third party imports
# local imports — the shared sync engine (transport, retry session, fan-out loops), and the scan's markers and pins
from common.kdf_scan import BLOCK_CLOSE, BLOCK_OPEN, CALLER_PATH, RULES_REPO, Refusal, parse_scan_image
from common.repo_sync import PatchError, SyncItem, _select_repos, run_check, run_distribute

# ======================================================================================================================
# Configuration
# ======================================================================================================================

SCRIPTS_DIR          = Path(__file__).parent
REPO_ROOT            = SCRIPTS_DIR.parent
REGISTRY_FILE        = SCRIPTS_DIR / "scripts_registry.json"
SCRIPTS_VERSION_FILE = SCRIPTS_DIR / "SCRIPTS_VERSION"

MAKEFILE_DEST     = "Makefile"
KDF_FMT_DEST      = "kdf-fmt.toml"
REQUIREMENTS_DEST = "requirements-dev.in"
CI_YAML_DEST      = ".github/workflows/ci.yml"
VENDOR_DIR        = "scripts/kdf_scripts/"

# Header written above the pins when a repo has no requirements-dev.in at all. Every
# repo carries the vendored scripts, so every repo needs somewhere to declare the
# Python toolchain that lints and formats them -- including the JS repos, which get
# this file and nothing else Python-shaped. Deliberately NOT compiled to a
# requirements.txt there: with no application dependencies there is nothing to lock,
# and a lockfile would add a compile-requirements target to six Makefiles for no gain.
_REQUIREMENTS_HEADER = (
    "# Managed by kriegerdataforge-cicd (distribute_scripts.py, ADR D-013).\n"
    "# Declares the Python toolchain that operates on the vendored scripts/kdf_scripts/\n"
    "# copies. The scripts themselves are stdlib-only and need nothing to RUN.\n"
    "#\n"
    "# kdf-fmt tracks main (cicd D-054), and this line is its one declaration. The reusable\n"
    "# style lane reads its ref from here, and `make ci-style` reinstalls from it before\n"
    "# each check, so the local check and CI run the same formatter.\n"
)

# `name @ git+https://...` and plain `name==x.y.z` both start with the distribution
# name, which is all we need to decide "is this package already declared here".
_REQ_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:@|==|>=|<=|~=|!=|<|>|\[|$)")

# A ci.yml may still pass the reusable style job an override ref, which must match the canonical one (D-054).
_KDF_FMT_REF_RE = re.compile(r"^(\s*kdf_fmt_ref\s*:\s*)(\S+)\s*$", re.MULTILINE)

# The canonical `ci-version-check` recipe every repo converges on: a thin call of the
# vendored checker, which owns ALL the logic (consistency + strict increment +
# skip-when-base-unfetchable). `$(if ...)` covers repos that define no BASE_BRANCH;
# PYTHONUTF8=1 matches the `_BUMP` convention (cp1252 Windows consoles).
CANONICAL_RECIPE = (
    "ci-version-check: _ensure-venv ## CI: version consistency + strict +1 increment"
    " vs origin/main (vendored scripts/kdf_scripts/check_version.py)\n"
    '\t@printf "$(GREEN)CI: version check...$(NC)\\n"\n'
    '\t@PYTHONUTF8=1 $(PYTHON) scripts/kdf_scripts/check_version.py'
    ' --base-branch "$(if $(BASE_BRANCH),$(BASE_BRANCH),main)"\n'
)

# A make recipe block: the target line plus the maximal run of tab-prefixed lines.
_RECIPE_RE = re.compile(r"^ci-version-check:[^\n]*\n(?:\t[^\n]*\n)*", re.MULTILINE)

# Old flat script paths -> vendor-dir paths, everywhere in the Makefile (the `_BUMP :=`
# line, the recipe, comments). The negative lookbehind is LOAD-BEARING for idempotency:
# "kdf_scripts/bump_version.py" itself ENDS WITH the substring "scripts/bump_version.py",
# so a naive replace would double-nest the path on every re-run.
_PATH_REWRITE_RE = re.compile(r"(?<!kdf_)scripts/(check_version|bump_version|version_targets)\.py")

# cicd's active scan image, the set an activating pull request names (design 5.1), and the gate's caller, one text for
# every repo, which this Distribute writes beside the block once an image is pinned (design 5.3)
SCAN_IMAGE_FILE = SCRIPTS_DIR / "common" / "SCAN_IMAGE"
CALLER_SOURCE   = SCRIPTS_DIR / "common" / "kdf-scan-gate-caller.yml"
# the managed scan block every repo's Makefile holds between its two markers (D-085, design 5.5). Its recipe runs
# cicd's image by its digest with the network off, the root read only, no capability and a user that is not root, the
# working tree, its git folders and the rules' cache mounted read only, each path as git itself names it, so Git Bash
# gives a native one. A repo's own SCAN_EXCLUDE and SCAN_LIMIT lines sit between the head and the tail, the wrapper
# reading them from the block itself, and the digest moves with each activation by this Distribute.
SCAN_BLOCK_HEAD = (
    f"{BLOCK_OPEN}\n"
    "# The local code scan, Opengrep and zizmor in cicd's image by its digest, a check against accidents and branch\n"
    "# edits, never the gate, which runs from main (cicd D-085).\n"
    "SCAN_EXCLUDE ?=\n"
)
SCAN_BLOCK_TAIL = """\
KDF_SCAN_IMAGE := {image}@{digest}
KDF_SCAN_RULES_COMMIT := {rules_commit}
KDF_SCAN_CALLER_SHA := {caller_sha}
KDF_SCAN_ENGINE ?= docker
KDF_SCAN_RULES ?= $(HOME)/.cache/kdf-scan/semgrep-rules.git
kdf_scan_native = $$(cd "$(1)" && (pwd -W 2>/dev/null || pwd))
KDF_SCAN_RUN = MSYS_NO_PATHCONV=1 $(KDF_SCAN_ENGINE) run --rm --pull never --network none --read-only \\
  --tmpfs /run/kdf-scan:exec,size=1g,uid=65532,gid=65532 --cap-drop ALL --security-opt no-new-privileges \\
  --user 65532:65532
.PHONY: scan scan-setup scan-pr
scan: ## Local code scan in cicd's image, before every pull request, never the gate
\t@own="$$(git rev-parse --path-format=absolute --git-dir)"; \\
\t  common="$$(git rev-parse --path-format=absolute --git-common-dir)"; \\
\t  $(KDF_SCAN_RUN) -v "$$(git rev-parse --show-toplevel):/src:ro" -v "$$common:/git:ro" \\
\t  -v "$(call kdf_scan_native,$(KDF_SCAN_RULES)):/rules:ro" $(KDF_SCAN_IMAGE) scan \\
\t  --git-dir "/git$${{own#"$$common"}}" --autocrlf "$$(git config core.autocrlf)" --pinned "{digest}" \\
\t  --cicd-digest "$$(git -C ../kriegerdataforge-cicd show origin/main:scripts/common/SCAN_IMAGE 2>/dev/null \\
\t  | sed -n 's/^digest=//p')"
scan-setup: ## Pull cicd's scan image and fetch Semgrep's rules into the cache, the one step that uses the network
\t@$(KDF_SCAN_ENGINE) pull $(KDF_SCAN_IMAGE)
\t@[ -d "$(KDF_SCAN_RULES)" ] || git init -q --bare "$(KDF_SCAN_RULES)"
\t@git -C "$(KDF_SCAN_RULES)" fetch -q --no-tags --depth 1 {rules_repo} $(KDF_SCAN_RULES_COMMIT)
scan-pr: ## The local scan before a merge, PR=<number>, the weaker answer when Actions is down
\t@set -e; [ -n "$(PR)" ] || {{ echo "kdf-scan  make scan-pr PR=<number>"; exit 2; }}; \\
\t  repo=$$(gh repo view --json nameWithOwner -q .nameWithOwner); \\
\t  head=$$(gh api "repos/$$repo/pulls/$(PR)" -q .head.sha); base=$$(gh api "repos/$$repo/pulls/$(PR)" -q .base.ref); \\
\t  [ "$$base" = main ] || {{ echo "kdf-scan  refused, the base is $$base, the scan reads main's"; exit 2; }}; \\
\t  main=$$(gh api "repos/$$repo/commits/main" -q .sha); \\
\t  merged=$$(gh api "repos/$$repo/compare/$$main...$$head" -q .merge_base_commit.sha); \\
\t  dir=$$(mktemp -d); git init -q --bare "$$dir/repo.git"; \\
\t  git -C "$$dir/repo.git" -c credential.helper= -c 'credential.helper=!gh auth git-credential' fetch -q --no-tags \\
\t  "https://github.com/$$repo.git" "+refs/pull/$(PR)/head:refs/kdf/head" "+refs/heads/main:refs/kdf/main"; \\
\t  $(KDF_SCAN_RUN) -v "$(call kdf_scan_native,$$dir/repo.git):/repo:ro" \\
\t  -v "$(call kdf_scan_native,$(KDF_SCAN_RULES)):/rules:ro" $(KDF_SCAN_IMAGE) pr-tree --head "$$head" \\
\t  --main "$$main" --merge-base "$$merged" --caller-sha "$(KDF_SCAN_CALLER_SHA)" || code=$$?; \\
\t  rm -rf "$$dir"; exit $${{code:-0}}
"""
# a rule whose targets name scan, alone or among others, after any spaces make allows before a rule, and not a recipe
# line, which a tab opens, scan-local, scan-fixtures or a variable, grouped targets' &: read as a rule too
_SCAN_TARGET_RE = re.compile(r"^(?!\t)[ \t]*(?:[^\s#:=][^:=#]*\s+)?scan(?:\s+[^:=#&]*)?\s*&?::?(?!=)")
# the lines of a repo's own the block keeps whole, which the wrapper itself judges
_SCAN_OWN_LINES = ("SCAN_EXCLUDE +=", "SCAN_LIMIT")

# The exclusion appended to tenant style/lint configs (trailing slash = directory).
_VENDOR_EXCLUDE_ENTRY  = f'"{VENDOR_DIR}"'
_KDF_FMT_EXCLUDE_BLOCK = (
    "\n# distributed ecosystem scripts are vendored -- their style is governed in kriegerdataforge-cicd\n"
    f"exclude = [{_VENDOR_EXCLUDE_ENTRY}]\n"
)

_CLI_EPILOG = """Examples:
  GH_TOKEN=... python distribute_scripts.py check
  GH_TOKEN=... python distribute_scripts.py distribute --repos kriegerdataforge,tiffanys-space
  GH_TOKEN=... python distribute_scripts.py distribute --only check_version.py"""

_REPOS_HELP = """Only operate on these repos (comma-separated EXACT names, e.g.
'kriegerdataforge,tiffanys-space'). Matches the full owner/repo or the short name
exactly (not a substring). Blank = all repos in the registry."""

_PR_BODY_TEMPLATE = """Automated sync of the ecosystem dev scripts to **{version}** from
`kriegerdataforge-cicd/scripts/common/` (ADR D-013 / vendored layout ADR D-014).

Items updated: {items}

The version tooling now lives in the **`scripts/kdf_scripts/` vendor directory**: the old
flat `scripts/` copies are deleted in this PR, every Makefile reference (including
`_BUMP :=` and the `ci-version-check` recipe) points at the new paths, and the directory
is excluded from this repo's `kdf-fmt.toml` (and ruff config, where present) — the style
of vendored scripts is governed in kriegerdataforge-cicd, so tenant formatting configs
can never fail a sync PR again.

No VERSION bump: scripts-sync PRs are exempt from the version gate (see check_version.py /
ADR D-013). Please review and merge."""

# ======================================================================================================================
# Helpers
# ======================================================================================================================

def _load_registry() -> dict:
    """
    Load scripts_registry.json from beside this script.

    Returns:
        dict: the parsed registry
    """
    if not REGISTRY_FILE.is_file():
        sys.exit(f"Error: registry file not found: {REGISTRY_FILE}")
    return json.loads(REGISTRY_FILE.read_text(encoding = "utf-8"))


def _scripts_version() -> str:
    """
    Read the SCRIPTS_VERSION sync marker.

    Returns:
        str: the marker value, or "unknown" when the file is missing
    """
    if SCRIPTS_VERSION_FILE.is_file():
        return SCRIPTS_VERSION_FILE.read_text(encoding = "utf-8").strip()
    return "unknown"

# ======================================================================================================================
# Patchers (all idempotent; PatchError -> repo reported NEEDS MANUAL ATTENTION)
# ======================================================================================================================

def patch_makefile(text: str | None) -> str:
    """
    Point every script reference at the vendor dir and re-assert the canonical recipe.

    Step 1 rewrites all `scripts/<name>.py` references to `scripts/kdf_scripts/<name>.py`
    (the lookbehind in _PATH_REWRITE_RE keeps already-rewritten paths untouched). Step 2
    replaces the `ci-version-check:` recipe block with CANONICAL_RECIPE. Idempotent by
    construction: the canonical block matches the recipe regex and maps to itself.

    Args:
        text: the target repo's current Makefile content, or None when absent

    Returns:
        str: the patched Makefile content (LF endings)

    Raises:
        PatchError: when the Makefile is missing or has no `ci-version-check` target
    """
    if text is None:
        raise PatchError("Makefile not found in the target repo")
    normalized = text.replace("\r\n", "\n")
    if not _RECIPE_RE.search(normalized):
        raise PatchError("Makefile has no `ci-version-check:` recipe to rewrite")
    rewritten = _PATH_REWRITE_RE.sub(r"scripts/kdf_scripts/\1.py", normalized)
    # function replacement -> inserted literally (no \-escape processing of the recipe)
    return patch_scan_block(_RECIPE_RE.sub(lambda _match: CANONICAL_RECIPE, rewritten, count = 1))


def active_scan_image() -> dict[str, str]:
    """
    cicd's active scan image as SCAN_IMAGE names it, empty before the first activation.

    Returns:
        dict[str, str]: the active set, empty while unpinned

    Raises:
        PatchError: when SCAN_IMAGE is missing or malformed
    """
    try:
        return parse_scan_image(SCAN_IMAGE_FILE.read_text(encoding = "utf-8"))
    except (OSError, Refusal) as error:
        raise PatchError(f"cicd's SCAN_IMAGE cannot be read, {error}") from error


def caller_text() -> str:
    """
    The gate's caller as cicd keeps it, the one text every repo holds.

    Returns:
        str: the caller
    """
    return CALLER_SOURCE.read_text(encoding = "utf-8").replace("\r\n", "\n")


def scan_block_tail(active: dict[str, str]) -> str:
    """
    The block's tail for the active set, its digest, the rules' commit and the canonical caller's SHA-256.

    Args:
        active: the active set

    Returns:
        str: the tail
    """
    return SCAN_BLOCK_TAIL.format(
        image = active["image"],
        digest = active["digest"],
        rules_commit = active["rules_commit"],
        rules_repo = RULES_REPO,
        caller_sha = hashlib.sha256(caller_text().encode("utf-8")).hexdigest(),
    ) + f"{BLOCK_CLOSE}\n"


def patch_scan_block(text: str, active: dict[str, str] | None = None) -> str:
    """
    Write the managed scan block, inserted at the end when absent and replaced whole when present, the repo's own
    SCAN_EXCLUDE and SCAN_LIMIT lines kept as they stand (D-085, design 5.5), and leave the Makefile as it stands while
    cicd pins no image. Idempotent, since the block it writes is the block it reads.

    Args:
        text: a Makefile's content with LF endings
        active: the active set, cicd's SCAN_IMAGE when None

    Returns:
        str: the content with the canonical block

    Raises:
        PatchError: when the Makefile holds two blocks, an unclosed one, a stray close, or a scan target outside it
    """
    active = active_scan_image() if active is None else active
    if not active:
        return text
    lines  = text.split("\n")
    opened = [index for index, line in enumerate(lines) if line.rstrip() == BLOCK_OPEN]
    closed = [index for index, line in enumerate(lines) if line.rstrip() == BLOCK_CLOSE]
    if len(opened) > 1 or len(closed) > 1:
        raise PatchError("the Makefile holds two managed scan blocks, so the sync cannot tell which to keep")
    if len(opened) != len(closed) or (opened and closed[0] < opened[0]):
        raise PatchError("the Makefile's managed scan block is unclosed or its close stands alone")
    inside  = lines[opened[0] + 1:closed[0]] if opened else []
    outside = lines[:opened[0]] + lines[closed[0] + 1:] if opened else lines
    if any(_SCAN_TARGET_RE.match(line) for line in outside):
        raise PatchError("the Makefile holds a scan target outside the managed block, which the block would shadow")
    own   = "".join(f"{line.rstrip()}\n" for line in inside if line.startswith(_SCAN_OWN_LINES))
    block = SCAN_BLOCK_HEAD + own + scan_block_tail(active)
    if not opened:
        body = text.rstrip("\n")
        return f"{body}\n\n{block}" if body else block
    return "\n".join(lines[:opened[0]]) + "\n" + block + "\n".join(lines[closed[0] + 1:])


def patch_kdf_fmt_toml(text: str | None) -> str:
    """
    Append the vendor-dir exclusion to a tenant's kdf-fmt.toml.

    No-op when the path is already excluded. When a top-level `exclude = [` list exists,
    the entry is inserted after the opening bracket; otherwise the key is created before
    the first TOML table header (top-level keys must precede tables).

    Args:
        text: the repo's current kdf-fmt.toml content, or None when absent

    Returns:
        str: the patched config (LF endings)

    Raises:
        PatchError: when kdf-fmt.toml is missing from the repo
    """
    if text is None:
        raise PatchError("kdf-fmt.toml not found in the target repo")
    normalized = text.replace("\r\n", "\n")
    if VENDOR_DIR in normalized:
        return normalized
    match = re.search(r"^(exclude\s*=\s*\[)", normalized, re.MULTILINE)
    if match:
        return normalized[: match.end()] + _VENDOR_EXCLUDE_ENTRY + ", " + normalized[match.end():]
    table = re.search(r"^\[", normalized, re.MULTILINE)
    if table:
        return normalized[: table.start()] + _KDF_FMT_EXCLUDE_BLOCK + "\n" + normalized[table.start():]
    return normalized.rstrip("\n") + "\n" + _KDF_FMT_EXCLUDE_BLOCK


def patch_requirements(text: str | None, packages: list[dict]) -> str:
    """
    Merge the canonical toolchain pins into a repo's requirements-dev.in.

    Four cases per package, and only two of them write anything:
      absent            -> the pinned spec is appended
      present, same     -> untouched (idempotent; a re-run produces no diff)
      present, differs  -> PatchError, so the repo is reported NEEDS MANUAL ATTENTION
      file absent       -> created with the header, then the pins appended

    The third case is the point of the whole exercise. Silently rewriting a pin would
    move a repo onto a different kdf-fmt without anyone deciding to, and a kdf-fmt
    version change shifts style findings against the baselines -- so divergence is
    surfaced for a human instead of resolved by a tool.

    Args:
        text: the repo's current requirements-dev.in content, or None when absent
        packages: canonical entries, each ``{"name": ..., "spec": ...}``

    Returns:
        str: the merged file content (LF endings)

    Raises:
        PatchError: when a package is already declared at a different version
    """
    normalized = (text or _REQUIREMENTS_HEADER).replace("\r\n", "\n")
    lines      = normalized.split("\n")

    declared: dict[str, tuple[int, str]] = {}
    for index, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _REQ_NAME_RE.match(line)
        if match:
            declared[match.group(1).lower().replace("_", "-")] = (index, line.strip())

    additions: list[str] = []
    for package in packages:
        key  = package["name"].lower().replace("_", "-")
        spec = package["spec"]
        if key not in declared:
            additions.append(spec)
            continue
        _index, existing = declared[key]
        if existing != spec:
            raise PatchError(
                f"{package['name']} is pinned as {existing!r} but the canonical pin is "
                f"{spec!r}. Reconcile it by hand -- the distributor will not move a pin "
                "for you, because changing kdf-fmt versions moves style baselines too."
            )

    if not additions:
        return normalized
    body = normalized.rstrip("\n")
    return (body + "\n" if body else "") + "\n".join(additions) + "\n"


def patch_ci_yaml(text: str | None, expected_ref: str) -> str:
    """
    Verify a ci.yml that overrides the formatter's ref names the canonical one.

    Since D-054 the reusable style lanes read kdf-fmt's ref from the caller's
    requirements-dev.in, and kdf_fmt_ref is only an override, which most callers leave
    out. A ci.yml that passes one must name the canonical ref, or local dev and CI would
    format with different kdf-fmt versions.

    Returns the content UNCHANGED when the two agree, which the engine treats as "no
    drift" and therefore never writes. That is deliberate: pushing a change to
    .github/workflows/ requires the `workflow` token scope, and no other distributor
    in this repo writes workflow files. Drift is reported instead of repaired.

    This is the check that would have caught kriegerdataforge-sdk, which pinned
    kdf-fmt v1.1.1 for local dev while its CI style job ran v1.1.0.

    Args:
        text: the repo's current ci.yml content, or None when absent
        expected_ref: the canonical git ref, e.g. ``main``

    Returns:
        str: the content exactly as received, when it passes no override or the canonical one

    Raises:
        PatchError: when ci.yml is missing or overrides the ref with another one
    """
    if text is None:
        raise PatchError(f"{CI_YAML_DEST} not found in the target repo")
    match = _KDF_FMT_REF_RE.search(text.replace("\r\n", "\n"))
    if match is None:
        # NOT drift. Since D-054 a caller with no kdf_fmt_ref still calls the reusable
        # style job, which reads the ref from its requirements-dev.in, the declaration the
        # requirements patch already checks. Before D-054 raising here failed the WHOLE
        # repo, the requirements pin and the three vendored scripts with it, for 8 of the
        # 17 registry repos, which is how this was found.
        return text
    found = match.group(2).strip().strip("\"'")
    if found != expected_ref:
        raise PatchError(
            f"{CI_YAML_DEST} pins kdf_fmt_ref {found} but the canonical pin is "
            f"{expected_ref}. Local dev and CI would format with different kdf-fmt "
            "versions. Update the workflow by hand (the distributor never writes "
            "workflow files)."
        )
    return text


def patch_ruff_toml(text: str | None) -> str:
    """
    Append the vendor-dir exclusion to a tenant's ruff.toml `exclude` list.

    Args:
        text: the repo's current ruff.toml content, or None when absent

    Returns:
        str: the patched config (LF endings)

    Raises:
        PatchError: when ruff.toml is missing or has no top-level `exclude` list
    """
    if text is None:
        raise PatchError("declared ruff.toml not found in the target repo")
    normalized = text.replace("\r\n", "\n")
    if VENDOR_DIR in normalized:
        return normalized
    match = re.search(r"^(exclude\s*=\s*\[)", normalized, re.MULTILINE)
    if not match:
        raise PatchError("ruff.toml has no top-level `exclude` list to extend")
    return normalized[: match.end()] + "\n    " + _VENDOR_EXCLUDE_ENTRY + "," + normalized[match.end():]


def patch_ruff_pyproject(text: str | None) -> str:
    """
    Append the vendor-dir exclusion to `[tool.ruff]` in a tenant's pyproject.toml.

    Inserts into an existing `extend-exclude = [` list, or adds the key directly under
    the `[tool.ruff]` header. Never touches anything else in the file (notably the
    project version line).

    Args:
        text: the repo's current pyproject.toml content, or None when absent

    Returns:
        str: the patched config (LF endings)

    Raises:
        PatchError: when pyproject.toml is missing or has no `[tool.ruff]` table
    """
    if text is None:
        raise PatchError("declared pyproject.toml not found in the target repo")
    normalized = text.replace("\r\n", "\n")
    if VENDOR_DIR in normalized:
        return normalized
    extend = re.search(r"^(extend-exclude\s*=\s*\[)", normalized, re.MULTILINE)
    if extend:
        return normalized[: extend.end()] + _VENDOR_EXCLUDE_ENTRY + ", " + normalized[extend.end():]
    header = re.search(r"^\[tool\.ruff\]\s*$", normalized, re.MULTILINE)
    if not header:
        raise PatchError("pyproject.toml has no [tool.ruff] table to extend")
    insert = (
        "\n# distributed ecosystem scripts are vendored -- linted in kriegerdataforge-cicd\n"
        f"extend-exclude = [{_VENDOR_EXCLUDE_ENTRY}]"
    )
    return normalized[: header.end()] + insert + normalized[header.end():]


def _build_items(registry: dict, only: str | None, entry: dict) -> list[SyncItem]:
    """
    Build the SyncItems for ONE registry repo entry.

    The registry's src->dest files (byte-identical), the deletes[] of superseded paths,
    the Makefile patch, the kdf-fmt.toml exclusion, and — when the entry declares a
    `ruff_config` — the matching ruff exclusion. Optionally narrowed by --only
    (dest substring).

    Args:
        registry: the parsed scripts registry
        only: dest-substring filter, or None for all items
        entry: the registry repo entry the items are built for

    Returns:
        list[SyncItem]: the items to check or distribute for this repo

    Raises:
        PatchError: when the entry declares an unknown ruff_config value
    """
    items: list[SyncItem] = []
    for file_entry in registry.get("files", []):
        # a file only some repos run, the mutation engine (D-040), names them, and no other repo is handed it
        scope = file_entry.get("repos")
        if scope is not None and entry.get("repo") not in scope:
            continue
        src, dest = file_entry["src"], file_entry["dest"]
        canonical = (REPO_ROOT / src).read_text(encoding = "utf-8")
        items.append(SyncItem(dest = dest, desired = lambda _remote, content = canonical: content))
    for stale in registry.get("deletes", []):
        items.append(SyncItem(dest = stale, desired = None))
    if registry.get("makefile_patch"):
        items.append(SyncItem(dest = MAKEFILE_DEST, desired = patch_makefile))
        # the gate's caller travels with the block once an image is pinned, replaced whole when it differs, so a change
        # to it comes only from cicd (design 5.3)
        if active_scan_image():
            items.append(SyncItem(dest = CALLER_PATH, desired = lambda _remote, content = caller_text(): content))
    # A repo that runs no kdf-fmt lane carries no kdf-fmt.toml. patch_kdf_fmt_toml raises on a
    # missing file, which would report the whole repo as NEEDS MANUAL ATTENTION, so such an
    # entry opts out. Its vendored scripts are still styled here, in the repo that ships them.
    if registry.get("kdf_fmt_patch") and not entry.get("skip_kdf_fmt"):
        items.append(SyncItem(dest = KDF_FMT_DEST, desired = patch_kdf_fmt_toml))
    # A repo that PROVIDES one of the canonical packages must not pin it: kdf-fmt's own
    # repo would end up depending on itself, and it carries no kdf_fmt_ref in ci.yml
    # because it is the formatter rather than a consumer of one.
    requirements = registry.get("requirements_patch")
    if requirements and not entry.get("skip_requirements"):
        packages = requirements.get("packages", [])
        items.append(SyncItem(
            dest = requirements.get("target", REQUIREMENTS_DEST),
            desired = lambda text, pkgs = packages: patch_requirements(text, pkgs),
        ))
        # Read-only companion: proves the workflow pins the same ref, writes nothing.
        toolchain_ref = requirements.get("kdf_fmt_ref")
        if toolchain_ref:
            items.append(SyncItem(
                dest = CI_YAML_DEST,
                desired = lambda text, ref = toolchain_ref: patch_ci_yaml(text, ref),
            ))
    ruff_config = entry.get("ruff_config")
    if ruff_config:
        ruff_patchers = {"ruff.toml": patch_ruff_toml, "pyproject.toml": patch_ruff_pyproject}
        patcher       = ruff_patchers.get(ruff_config)
        if patcher is None:
            raise PatchError(f"unknown ruff_config {ruff_config!r} (use 'ruff.toml' or 'pyproject.toml')")
        items.append(SyncItem(dest = ruff_config, desired = patcher))
    if only:
        items = [item for item in items if only in item.dest]
        if not items:
            sys.exit(f"Error: --only '{only}' matched no synced items for this run.")
    return items


def pretested_dests(registry: dict, entry: dict) -> set[str]:
    """
    The exact paths a scripts sync may change in this repo without running its CI (ADR D-047). Only whole file copies
    whose registry entry opts in with "pretested": true and that this repo receives. Every patch of the repo's own files
    (Makefile, requirements-dev.in, kdf-fmt.toml, ruff.toml, pyproject.toml) and every delete stays off, and so does the
    mutation engine, which cicd tests but never against the repo's own tables.

    Args:
        registry: the parsed scripts registry
        entry: the registry repo entry

    Returns:
        set[str]: the allowlist
    """
    dests: set[str] = set()
    for file_entry in registry.get("files", []):
        scope = file_entry.get("repos")
        if scope is not None and entry.get("repo") not in scope:
            continue
        if file_entry.get("pretested") is True:
            dests.add(file_entry["dest"])
    return dests

# ======================================================================================================================
# CLI
# ======================================================================================================================

def parse_cli_args() -> argparse.Namespace:
    """
    Parse the CLI arguments.

    Returns:
        argparse.Namespace: mode, only, repos
    """
    parser = argparse.ArgumentParser(
        description = "Check or distribute the ecosystem dev scripts across all repos.",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = _CLI_EPILOG,
    )
    parser.add_argument(
        "mode",
        choices = ["check", "distribute"],
        help = "'check' reports drift (opens nothing). 'distribute' opens one PR per drifted repo.",
    )
    parser.add_argument(
        "--only",
        default = None,
        help = "Only operate on synced items whose DEST path contains this substring (e.g. 'check_version.py').",
    )
    parser.add_argument(
        "--repos",
        default = None,
        help = _REPOS_HELP,
    )
    return parser.parse_args()


def main() -> None:
    """
    Run the selected mode (check or distribute) and exit with its status code.

    Returns:
        None
    """
    args     = parse_cli_args()
    registry = _load_registry()
    token    = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        sys.exit("Error: GH_TOKEN environment variable not set.")

    version = _scripts_version()
    repos   = _select_repos(registry, args.repos)


    def items_for(entry: dict) -> list[SyncItem]:
        """
        Build this repo entry's items (closure over the registry and --only filter).

        Args:
            entry: the registry repo entry

        Returns:
            list[SyncItem]: the items for this repo
        """
        return _build_items(registry, args.only, entry)


    if args.mode == "check":
        banner = f"Checking ecosystem dev scripts {version} across {len(repos)} repo(s):"
        sys.exit(run_check(token, repos, items_for, banner))
    else:
        print(f"Distributing ecosystem dev scripts {version} to {len(repos)} repo(s):")
        sys.exit(
            run_distribute(
                token,
                repos,
                items_for,
                sync_branch = f"chore/scripts-sync-{version}",
                pr_title = f"chore(scripts): sync ecosystem dev scripts {version}",
                pr_body_fn = lambda drift: _PR_BODY_TEMPLATE.format(
                    version = version,
                    items = ", ".join(item.dest for item in drift),
                ),
                commit_msg_fn = lambda item: (
                    f"chore(scripts): remove superseded {item.dest} ({version})"
                    if item.desired is None
                    else f"chore(scripts): sync {item.dest} to {version}"
                ),
                pretested = lambda entry: pretested_dests(registry, entry),
            )
        )


if __name__ == "__main__":
    main()
