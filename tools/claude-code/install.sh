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
# The new guard is staged beside the live one and smoke tested there, so a copy that fails never goes live, and the
# live copy is kept as kdf-guard.prev.js to go back to (D-059). Both keep the .js ending, which node needs, and the
# staged name carries this run's process id, so two installs at once never test one copy and place the other.
staged="$hooks/kdf-guard.staged.$$.js"
cp "$here/kdf-guard.js" "$staged"
node --check "$staged" || { rm -f "$staged"; die "the new guard does not parse, the installed one is unchanged"; }

# The smoke test feeds the staged copy three calls and input it cannot read, and reads the exit code, 2 is a refusal.
call() { printf '{"tool_name":"Bash","tool_input":{"command":"%s"},"cwd":"."}' "$1"; }
exit_of() {
	set +e
	printf '%s' "$2" | KDF_ROLE="$1" node "$staged" >/dev/null 2>&1
	printf '%s' "$?"
}
expect() {
	local want=$1 role=$2 input=$3 named=$4 got
	got=$(exit_of "$role" "$input")
	if [ "$got" -ne "$want" ]; then
		rm -f "$staged"
		die "smoke test failed, $named as '${role:-owner}' exited $got, wanted $want, the installed guard is unchanged"
	fi
}
expect 2 "" "$(call "git push origin main")" "'git push origin main'"
expect 2 "reviewer" "$(call "git add .")" "'git add .'"
expect 0 "" "$(call "git status")" "'git status'"
expect 2 "" "not json" "input that is not JSON"
if [ -f "$hooks/kdf-guard.js" ]; then
	cp "$hooks/kdf-guard.js" "$hooks/kdf-guard.prev.js"
fi
mv -f "$staged" "$hooks/kdf-guard.js"
chmod +x "$hooks/kdf-guard.js"
say "Installed $hooks/kdf-guard.js, the previous copy kept as kdf-guard.prev.js."
say "Smoke test passed, a push to main, a reviewer git add and input that is not JSON are refused, git status runs."

# The compaction hook (D-058), beside the guard. It refuses nothing, so its smoke test is that input it cannot read
# prints nothing and exits 0.
if [ -f "$here/kdf-compact.js" ]; then
	node --check "$here/kdf-compact.js"
	cp "$here/kdf-compact.js" "$hooks/kdf-compact.js"
	set +e
	printed=$(printf 'not json' | node "$hooks/kdf-compact.js" session-start 2>/dev/null)
	got=$?
	set -e
	if [ "$got" -ne 0 ] || [ -n "$printed" ]; then
		die "smoke test failed, the compaction hook exited $got or printed on input it cannot read"
	fi
	say "Installed $hooks/kdf-compact.js, wired by hand as the README's compaction hook section says."
fi
say ""
node "$here/check-wiring.js" --home "$home" --print
say ""
say "Then run  bash tools/claude-code/install.sh --check  and restart every session and every claude rc server."
