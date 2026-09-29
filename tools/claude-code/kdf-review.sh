#!/usr/bin/env bash
# kdf-review.sh, launch one fresh Claude reviewer the KDF Code Review Process way.
#
#   bash tools/claude-code/kdf-review.sh --repo <repo root> --brief <brief file> --report <report file> \
#        [--model <model>] [--effort <level>] [--timeout <seconds>] [--codex-report <file>] [--dry-run]
#
# What it does, in order.
#   1. Checks the arguments. The report must be a new file under docs/security.
#   2. Refuses to start unless the guard is installed and wired, node check-wiring.js says so.
#   3. Snapshots the repo's git state, HEAD, branch, refs, stash, index, and the hash of every changed or untracked file.
#   4. Runs claude -p in the repo with KDF_ROLE=reviewer, and without the owner's self edit switch.
#   5. Snapshots again. Anything other than new files under docs/security is contamination, exit 3.
#
# Exit codes. 0 clean review. 2 bad arguments. 3 the reviewer changed something it must not. 4 no report was written.
# 5 the guard is not installed or wired. 6 claude itself failed.
#
# The reviewer writes its report, the owner or the orchestrator reads it. Nothing here reverts a change, it reports.
set -uo pipefail
export LC_ALL=C

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
home="${KDF_HOME:-$HOME}"
claude_bin="${KDF_CLAUDE_BIN:-claude}"

die() { local code=$1; shift; printf 'kdf-review: %s\n' "$*" >&2; exit "$code"; }
usage() { sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

repo="" brief="" report="" model="" effort="" codex_report="" timeout_s=7200 dry=0
while [ $# -gt 0 ]; do
	case "$1" in
		--repo) repo="${2:-}"; shift 2 || die 2 "--repo needs a value" ;;
		--brief) brief="${2:-}"; shift 2 || die 2 "--brief needs a value" ;;
		--report) report="${2:-}"; shift 2 || die 2 "--report needs a value" ;;
		--model) model="${2:-}"; shift 2 || die 2 "--model needs a value" ;;
		--effort) effort="${2:-}"; shift 2 || die 2 "--effort needs a value" ;;
		--timeout) timeout_s="${2:-}"; shift 2 || die 2 "--timeout needs a value" ;;
		--codex-report) codex_report="${2:-}"; shift 2 || die 2 "--codex-report needs a value" ;;
		--dry-run) dry=1; shift ;;
		-h|--help) usage; exit 0 ;;
		*) die 2 "unknown argument $1" ;;
	esac
done
[ -n "$repo" ] && [ -n "$brief" ] && [ -n "$report" ] || die 2 "--repo, --brief and --report are required. See --help."

# ---- 1. the arguments
repo="$(cd "$repo" 2>/dev/null && pwd)" || die 2 "--repo is not a directory"
top="$(git -C "$repo" rev-parse --show-toplevel 2>/dev/null)" || die 2 "$repo is not a git repository"
[ "$(cd "$top" && pwd)" = "$repo" ] || die 2 "start from the repo root, $top, so the guard's project directory is the repo"

relative_inside() {
	# prints the path relative to the repo, and fails when it points outside the repo
	local given=$1 abs
	case "$given" in
		/*|[A-Za-z]:*) abs="$given" ;;
		*) abs="$repo/$given" ;;
	esac
	abs="$(realpath -m "$abs")"
	case "$abs" in
		"$repo"/*) printf '%s' "${abs#"$repo"/}" ;;
		*) return 1 ;;
	esac
}
brief_rel="$(relative_inside "$brief")" || die 2 "the brief must be a file inside the repo"
[ -f "$repo/$brief_rel" ] || die 2 "the brief $brief_rel does not exist"
report_rel="$(relative_inside "$report")" || die 2 "the report must be a path inside the repo"
case "$report_rel" in
	docs/security/*) ;;
	*) die 2 "the report must be under docs/security, not $report_rel" ;;
esac
[ ! -e "$repo/$report_rel" ] || die 2 "the report $report_rel already exists, a review never overwrites one"
codex_rel=""
if [ -n "$codex_report" ]; then
	codex_rel="$(relative_inside "$codex_report")" || die 2 "the Codex report must be a path inside the repo"
	case "$codex_rel" in
		docs/security/*) ;;
		*) die 2 "the Codex report must be under docs/security, not $codex_rel" ;;
	esac
fi

prompt="Read $brief_rel and run the review, write your report to $report_rel, edit nothing else."
codex_line=""
[ -n "$codex_rel" ] && codex_line="Read $brief_rel and run the review, write your report to $codex_rel, edit nothing else."

if [ "$dry" -eq 1 ]; then
	printf 'Claude prompt, %s\n' "$prompt"
	[ -n "$codex_line" ] && printf 'Codex prompt, %s\n' "$codex_line"
	exit 0
fi

# ---- 2. the guard must be installed and wired, or nothing starts
command -v node >/dev/null 2>&1 || die 5 "node is not on PATH, the guard is a Node script"
node "$here/check-wiring.js" --home "$home" --quiet >&2 || die 5 "the guard is not wired. Run node tools/claude-code/check-wiring.js and follow it."
canary() {
	local want=$1 role=$2 command=$3 got
	printf '{"tool_name":"Bash","tool_input":{"command":"%s"},"cwd":"%s"}' "$command" "$repo" \
		| KDF_ROLE="$role" node "$home/.claude/hooks/kdf-guard.js" >/dev/null 2>&1
	got=$?
	[ "$got" -eq "$want" ] || die 5 "the installed guard failed its canary, '$command' as '${role:-owner}' exited $got, wanted $want"
}
canary 2 reviewer "git add ."
canary 2 "" "git push origin main"

# ---- 3. the snapshot
snapshot() {
	{
		printf 'HEAD|%s\n' "$(git -C "$repo" rev-parse HEAD 2>/dev/null || echo none)"
		printf 'BRANCH|%s\n' "$(git -C "$repo" symbolic-ref -q --short HEAD 2>/dev/null || echo detached)"
		printf 'REFS|%s\n' "$(git -C "$repo" for-each-ref --format='%(refname) %(objectname)' | git hash-object --stdin)"
		printf 'STASH|%s\n' "$(git -C "$repo" stash list | wc -l | tr -d ' ')"
		printf 'INDEX|%s\n' "$(git -C "$repo" diff --cached --name-status | git hash-object --stdin)"
		git -C "$repo" ls-files -z -m -o --exclude-standard | while IFS= read -r -d '' f; do
			if [ -f "$repo/$f" ]; then
				printf 'FILE|%s|%s\n' "$f" "$(git -C "$repo" hash-object -- "$f")"
			else
				printf 'FILE|%s|gone\n' "$f"
			fi
		done
	} | LC_ALL=C sort
}
work="$(mktemp -d "${TMPDIR:-/tmp}/kdf-review.XXXXXX")"
snapshot >"$work/before"

# ---- 4. the run
log="$work/claude.log"
args=(-p "$prompt" --output-format text)
[ -n "$model" ] && args+=(--model "$model")
[ -n "$effort" ] && args+=(--effort "$effort")
runner=()
if command -v timeout >/dev/null 2>&1 && timeout --version 2>/dev/null | grep -q coreutils; then
	runner=(timeout "$timeout_s")
fi
printf 'kdf-review: starting the reviewer in %s, log %s\n' "$repo" "$log"
(cd "$repo" && env -u KDF_GUARD_ALLOW_SELF_EDIT KDF_ROLE=reviewer "${runner[@]}" "$claude_bin" "${args[@]}") >"$log" 2>&1
rc=$?

# ---- 5. the comparison
snapshot >"$work/after"
violations=()
while IFS= read -r line; do
	case "$line" in
		FILE\|*) ;;
		*) violations+=("git state changed, ${line%%|*}") ;;
	esac
done < <(comm -3 "$work/before" "$work/after" | sed 's/^[[:space:]]*//' | grep -v '^FILE|' | sort -u)
while IFS= read -r line; do
	f="${line#FILE|}"
	f="${f%|*}"
	if grep -q "^FILE|$f|" "$work/before"; then
		violations+=("changed, $f")
	else
		case "$f" in
			docs/security/*) ;;
			*) violations+=("new file outside docs/security, $f") ;;
		esac
	fi
done < <(comm -13 "$work/before" "$work/after" | grep '^FILE|')
while IFS= read -r line; do
	f="${line#FILE|}"
	f="${f%|*}"
	grep -q "^FILE|$f|" "$work/after" || violations+=("removed or reverted, $f")
done < <(comm -23 "$work/before" "$work/after" | grep '^FILE|')

if [ "${#violations[@]}" -gt 0 ]; then
	printf 'kdf-review: CONTAMINATION. The reviewer changed what it must not. Nothing was reverted.\n' >&2
	printf '  %s\n' "${violations[@]}" | sort -u >&2
	printf 'kdf-review: log %s\n' "$log" >&2
	exit 3
fi
if [ "$rc" -ne 0 ]; then
	printf 'kdf-review: claude exited %s, last lines of %s\n' "$rc" "$log" >&2
	tail -n 15 "$log" >&2
	exit 6
fi
[ -s "$repo/$report_rel" ] || die 4 "the reviewer wrote no report at $report_rel, see $log"

printf 'kdf-review: clean. Report %s, %s lines, log %s\n' "$report_rel" "$(wc -l <"$repo/$report_rel" | tr -d ' ')" "$log"
[ -n "$codex_line" ] && printf 'kdf-review: for Codex, %s\n' "$codex_line"
exit 0
