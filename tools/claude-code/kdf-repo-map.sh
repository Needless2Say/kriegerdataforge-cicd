#!/usr/bin/env bash
# kdf-repo-map.sh, the repo map, a read only lookup over named Python clones read from git's objects (D-082).
#
#   bash kdf-repo-map.sh defs <name> | imports <dotted> | callers <dotted> | callees <dotted> | test-importers <dotted>
#                        --repo <name> [--repo <name>]... [--at <repo>=<rev>]... [--skip <dir>]... [--tests] [--full]
#                        [--package-root <dir>]...
#
# callees adds a fourth group, Attributes written, and test-importers one, Test candidates that use it (D-084). Its
# --help prints a worker's brief, the words a session hands a worker it briefs to use the map.
#
# It refuses a session in the reviewer role first (KDF_ROLE=reviewer), before help, then finds cicd's own venv
# interpreter beside this checkout, checks that it starts and is Python 3.14 or newer, since ast parses the grammar of
# the Python that runs it, and only then runs kdf_repo_map.py with -I and -B, --help among the arguments. So a help
# that answers means a query can run. It never builds a venv. Exit 3 here names make venv in this checkout, which
# removes .venv first, so it runs only while the interpreter is missing and no query uses it. Every other exit is the
# module's, its --help says which.
set -uo pipefail

if [ "${KDF_ROLE:-}" = reviewer ]; then
	printf 'kdf-repo-map: a session in the reviewer role never runs the repo map, it reads code whole\n' >&2
	exit 2
fi
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
checkout="$(cd "$here/../.." && pwd)"
python=""
for candidate in "$checkout/.venv/Scripts/python.exe" "$checkout/.venv/bin/python"; do
	if [ -x "$candidate" ]; then python="$candidate"; break; fi
done
# the interpreter itself, never its folder, so a venv whose base Python is gone counts as missing
if [ -z "$python" ] || ! "$python" -I -B -c 'import sys; sys.exit(sys.version_info < (3, 14))' >/dev/null 2>&1; then
	printf 'kdf-repo-map: no usable Python 3.14 in %s/.venv. Run make venv there once, while no query runs\n' \
		"$checkout" >&2
	exit 3
fi
exec "$python" -I -B "$here/kdf_repo_map.py" "$@"
