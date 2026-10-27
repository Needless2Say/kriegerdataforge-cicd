#!/usr/bin/env bash
# kdf-tickets.sh, the tickets tool, a repo's tickets kept as one YAML file per GitHub issue in its docs/tickets/.
#
#   bash kdf-tickets.sh check | fmt | plan | pull | find | prompt <id> | scan --root <a worktree of the repo> [options]
#   bash kdf-tickets.sh ages --workspace <the folder holding the clones>
#
# This release is the read side. Nothing in it writes an issue or a board, and every command that reaches GitHub reads
# on the login's scopes and refuses a repo GitHub calls public before any other read. Its --help says the rest.
#
# It refuses a session in the reviewer role first (KDF_ROLE=reviewer), before help, then finds cicd's own venv
# interpreter beside this checkout, checks that it starts and is Python 3.12 or newer, and only then runs the package
# kdf_tickets beside this file with -I and -B, --help among the arguments. It never builds a venv. Exit 4 here names
# make venv in this checkout, which needs no token. Every other exit is the package's, its --help says which.
set -uo pipefail

if [ "${KDF_ROLE:-}" = reviewer ]; then
	printf 'kdf-tickets: a session in the reviewer role never runs the tickets tool\n' >&2
	exit 3
fi
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
checkout="$(cd "$here/../.." && pwd)"
python=""
for candidate in "$checkout/.venv/Scripts/python.exe" "$checkout/.venv/bin/python"; do
	if [ -x "$candidate" ]; then python="$candidate"; break; fi
done
# the interpreter itself, never its folder, so a venv whose base Python is gone counts as missing
if [ -z "$python" ] || ! "$python" -I -B -c 'import sys; sys.exit(sys.version_info < (3, 12))' >/dev/null 2>&1; then
	printf 'kdf-tickets: no usable Python 3.12 or newer in %s/.venv. Run make venv there once\n' "$checkout" >&2
	exit 4
fi
exec "$python" -I -B "$here/kdf_tickets" "$@"
