#!/usr/bin/env bash
# install.sh, put the KDF guard on this machine and say what is left for the owner to do.
#
#   bash tools/claude-code/install.sh            copy the guard, smoke test it, print the settings block to add
#   bash tools/claude-code/install.sh --check    only check the wiring, change nothing
#
# The owner runs this in a terminal. It refuses to run inside a Claude Code session, because a session does not
# install or change its own guardrails. It never edits settings.json, the owner adds the printed block by hand.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
home="${KDF_HOME:-$HOME}"
say() { printf '%s\n' "$*"; }
die() { printf 'install: %s\n' "$*" >&2; exit 1; }

command -v node >/dev/null 2>&1 || die "node is not on PATH. The guard is a Node script."

if [ "${1:-}" = "--check" ]; then
	exec node "$here/check-wiring.js" --home "$home"
fi
[ $# -eq 0 ] || die "unknown argument $1. Use --check or no argument."
[ -z "${CLAUDECODE:-}" ] || die "a Claude Code session does not install its own guardrails. Run this yourself in a terminal."

hooks="$home/.claude/hooks"
mkdir -p "$hooks"
cp "$here/kdf-guard.js" "$hooks/kdf-guard.js"
chmod +x "$hooks/kdf-guard.js"
node --check "$hooks/kdf-guard.js"
say "Installed $hooks/kdf-guard.js"

# The smoke test feeds the installed copy three calls and reads the exit code, 2 is a refusal.
call() { printf '{"tool_name":"Bash","tool_input":{"command":"%s"},"cwd":"."}' "$1"; }
expect() {
	local want=$1 role=$2 command=$3 got
	set +e
	call "$command" | KDF_ROLE="$role" node "$hooks/kdf-guard.js" >/dev/null 2>&1
	got=$?
	set -e
	[ "$got" -eq "$want" ] || die "smoke test failed, '$command' as '${role:-owner}' exited $got, wanted $want"
}
expect 2 "" "git push origin main"
expect 2 "reviewer" "git add ."
expect 0 "" "git status"
say "Smoke test passed, a push to main and a reviewer git add are refused, git status is allowed."
say ""
node "$here/check-wiring.js" --home "$home" --print
say ""
say "Then run  bash tools/claude-code/install.sh --check  and restart every session and every claude rc server."
