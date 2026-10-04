#!/usr/bin/env bash
# kdf-codex-install.sh, the Install script of a Codex cloud environment that reviews a KDF Python repo, the KDF Code
# Review Process section 11, cicd ADR D-048. The owner sets `repo` below to the reviewed repo's folder name and pastes
# the file whole into the environment's Install script field.
#
# It needs no token and no secret. A development package installed from one of the owner's private repos, a line
# `name @ git+https://github.com/Needless2Say/...` in requirements-dev.in, is left out, since only the style lane uses
# one, kdf-fmt, and a review read does not run it. A repo whose runtime lockfile names a private package, a backend
# that installs kdf-sdk, stops here, since its install would need a token and this script never holds one.
#
# Python. The image's python3.14 when it has one, otherwise uv installs 3.14 under the workspace, which the published
# environment keeps. A .venv that runs is kept, one whose interpreter is gone is made again.
#
# KDF_CODEX_WORKSPACE moves the workspace for the tests alone, Codex's is /workspace.
#
# Exit codes. 0 installed, and pip check passed. 1 a private runtime package, no requirements file, or an install that
# failed.
set -euo pipefail

repo=kriegerdataforge-sdk

say() { printf 'kdf-codex-install: %s\n' "$*" >&2; }

workspace="${KDF_CODEX_WORKSPACE:-/workspace}"
private='@ git+https://github.com/Needless2Say/'

cd "$workspace/$repo"
for file in requirements.txt requirements-dev.in; do
	[ -f "$file" ] || { say "no $file in $repo, so this script cannot install it"; exit 1; }
done
if grep -qF "$private" requirements.txt; then
	say "requirements.txt installs a private package, which needs a token. Section 11 covers only a repo without one"
	exit 1
fi

export UV_PYTHON_INSTALL_DIR="$workspace/.local/share/uv/python"
command -v python3.14 >/dev/null || uv python install 3.14
python="$(command -v python3.14 || uv python find 3.14)"
.venv/bin/python -c '' 2>/dev/null || "$python" -m venv --clear .venv

.venv/bin/python -m pip install -r requirements.txt
grep -vF "$private" requirements-dev.in | .venv/bin/python -m pip install -r /dev/stdin
.venv/bin/python -m pip install -e . --no-deps
.venv/bin/python -m pip check
say "installed $repo without its private development packages"
