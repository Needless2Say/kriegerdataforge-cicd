#!/usr/bin/env bash
# kdf-review.sh, run one fresh reviewer the KDF Code Review Process way.
#
#   Claude, in the repo
#     bash kdf-review.sh --repo <root> --brief <file> --report <file> [--model <m>] [--effort <e>] [--timeout <s>]
#                        [--codex-report <file>] [--dry-run]
#   Claude, in its own copy of the repo at a pinned commit
#     bash kdf-review.sh --repo <root> --brief <file> --report <file> --at <commit> [--setup "<command>"] [...]
#   A reviewer the owner starts by hand, Codex, in its own copy at a pinned commit
#     bash kdf-review.sh --repo <root> --brief <file> --report <file> --at <commit> --prepare [--setup "<command>"]
#     bash kdf-review.sh --repo <root> --report <file> --collect <copy>
#
# In the repo. The launcher checks the arguments and the guard, snapshots git, runs claude -p with KDF_ROLE=reviewer
# and without the owner's self edit switch, snapshots again, and fails the run when anything but a new file under
# docs/security changed.
#
# At a pinned commit. The launcher makes a git worktree of the repo at the commit, in a .kdf-review folder beside the
# repo, runs the setup command there when one is given (KDF_MAIN_REPO names the repo, the setup installs what the
# reviewer needs without the owner's tokens), and snapshots it. Then it runs Claude there, or with --prepare leaves the
# copy for the owner and prints the one line prompt and the collect command. Collect checks the copy the same way,
# HEAD still at the commit and nothing changed but new files under docs/security, copies those files into the repo,
# never over an existing one, and removes the copy. A reviewer that runs hours later reads exactly the commit the
# first one read, the orchestrator keeps working in the repo meanwhile, and no reviewer sees another's report.
#
# Exit codes. 0 clean. 2 bad arguments, or a file would be overwritten. 3 the reviewer changed something it must not,
# a copy is kept for a look. 4 no report was written. 5 the guard is not installed or wired. 6 claude itself failed.
# 7 the setup command failed.
#
# The reviewer writes its report, the owner or the orchestrator reads it. Nothing here reverts a change, it reports.
set -uo pipefail
export LC_ALL=C

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
home="${KDF_HOME:-$HOME}"
claude_bin="${KDF_CLAUDE_BIN:-claude}"

die() { local code=$1; shift; printf 'kdf-review: %s\n' "$*" >&2; exit "$code"; }
usage() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"; }

repo="" brief="" report="" model="" effort="" codex_report="" timeout_s=7200 dry=0 at="" setup="" prepare=0 collect=""
while [ $# -gt 0 ]; do
	case "$1" in
		--repo) repo="${2:-}"; shift 2 || die 2 "--repo needs a value" ;;
		--brief) brief="${2:-}"; shift 2 || die 2 "--brief needs a value" ;;
		--report) report="${2:-}"; shift 2 || die 2 "--report needs a value" ;;
		--model) model="${2:-}"; shift 2 || die 2 "--model needs a value" ;;
		--effort) effort="${2:-}"; shift 2 || die 2 "--effort needs a value" ;;
		--timeout) timeout_s="${2:-}"; shift 2 || die 2 "--timeout needs a value" ;;
		--codex-report) codex_report="${2:-}"; shift 2 || die 2 "--codex-report needs a value" ;;
		--at) at="${2:-}"; shift 2 || die 2 "--at needs a value" ;;
		--setup) setup="${2:-}"; shift 2 || die 2 "--setup needs a value" ;;
		--prepare) prepare=1; shift ;;
		--collect) collect="${2:-}"; shift 2 || die 2 "--collect needs a value" ;;
		--dry-run) dry=1; shift ;;
		-h|--help) usage; exit 0 ;;
		*) die 2 "unknown argument $1" ;;
	esac
done
if [ -n "$collect" ]; then
	[ -n "$repo" ] && [ -n "$report" ] || die 2 "--collect needs --repo and --report. See --help."
	[ -z "$at$setup$brief" ] && [ "$prepare" -eq 0 ] || die 2 "--collect takes only --repo and --report"
else
	[ -n "$repo" ] && [ -n "$brief" ] && [ -n "$report" ] || die 2 "--repo, --brief and --report are required. See --help."
	[ "$prepare" -eq 0 ] || [ -n "$at" ] || die 2 "--prepare needs --at, a copy is made at a pinned commit"
	[ -z "$setup" ] || [ -n "$at" ] || die 2 "--setup needs --at, it prepares a copy"
fi

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
report_rel="$(relative_inside "$report")" || die 2 "the report must be a path inside the repo"
case "$report_rel" in
	docs/security/*) ;;
	*) die 2 "the report must be under docs/security, not $report_rel" ;;
esac
[ ! -e "$repo/$report_rel" ] || die 2 "the report $report_rel already exists, a review never overwrites one"

# snapshot <dir> <1 to include the refs and the stash, which every copy of a repo shares>
snapshot() {
	local dir=$1 shared=$2
	{
		printf 'HEAD|%s\n' "$(git -C "$dir" rev-parse HEAD 2>/dev/null || echo none)"
		printf 'BRANCH|%s\n' "$(git -C "$dir" symbolic-ref -q --short HEAD 2>/dev/null || echo detached)"
		if [ "$shared" = 1 ]; then
			printf 'REFS|%s\n' "$(git -C "$dir" for-each-ref --format='%(refname) %(objectname)' | git hash-object --stdin)"
			printf 'STASH|%s\n' "$(git -C "$dir" stash list | wc -l | tr -d ' ')"
		fi
		printf 'INDEX|%s\n' "$(git -C "$dir" diff --cached --name-status | git hash-object --stdin)"
		git -C "$dir" ls-files -z -m -o --exclude-standard | while IFS= read -r -d '' f; do
			if [ -f "$dir/$f" ]; then
				printf 'FILE|%s|%s\n' "$f" "$(git -C "$dir" hash-object -- "$f")"
			else
				printf 'FILE|%s|gone\n' "$f"
			fi
		done
	} | LC_ALL=C sort
}

# compare <before> <after>, one line per thing the reviewer must not have done
compare() {
	local before=$1 after=$2 line f
	while IFS= read -r line; do
		case "$line" in
			FILE\|*) ;;
			*) printf 'git state changed, %s\n' "${line%%|*}" ;;
		esac
	done < <(comm -3 "$before" "$after" | sed 's/^[[:space:]]*//' | grep -v '^FILE|' | sort -u)
	while IFS= read -r line; do
		f="${line#FILE|}"
		f="${f%|*}"
		if grep -qF -- "FILE|$f|" "$before"; then
			printf 'changed, %s\n' "$f"
		else
			case "$f" in
				docs/security/*) ;;
				*) printf 'new file outside docs/security, %s\n' "$f" ;;
			esac
		fi
	done < <(comm -13 "$before" "$after" | grep '^FILE|')
	while IFS= read -r line; do
		f="${line#FILE|}"
		f="${f%|*}"
		grep -qF -- "FILE|$f|" "$after" || printf 'removed or reverted, %s\n' "$f"
	done < <(comm -23 "$before" "$after" | grep '^FILE|')
}

# the new files a reviewer wrote, by now all under docs/security
new_files() { comm -13 "$1" "$2" | grep '^FILE|' | sed 's/^FILE|//; s/|[^|]*$//'; }

# ---- 2. collect, the end of a pinned review
# collect_copy <claude exit code, 0 for a reviewer the owner ran by hand>
collect_copy() {
	local rc=$1 pinned_repo pinned_report common_wt common_repo new_refs f
	[ -f "$meta/pin" ] || die 2 "$wt was not made by kdf-review.sh, $meta/pin is missing"
	pinned_repo="$(sed -n 's/^repo=//p' "$meta/pin")"
	pinned_report="$(sed -n 's/^report=//p' "$meta/pin")"
	[ "$pinned_repo" = "$repo" ] || die 2 "that copy belongs to $pinned_repo, not $repo"
	[ "$pinned_report" = "$report_rel" ] || die 2 "that copy was made for $pinned_report, not $report_rel"
	common_wt="$(git -C "$wt" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || die 2 "$wt is not a git copy"
	common_repo="$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir)"
	[ "$common_wt" = "$common_repo" ] || die 2 "$wt is not a copy of $repo"

	snapshot "$wt" 0 >"$meta/after"
	mapfile -t violations < <(compare "$meta/before" "$meta/after")
	if [ "${#violations[@]}" -gt 0 ]; then
		printf 'kdf-review: CONTAMINATION in %s. The reviewer changed what it must not. The copy is kept for a look.\n' "$wt" >&2
		printf '  %s\n' "${violations[@]}" | sort -u >&2
		exit 3
	fi
	if [ "$rc" -ne 0 ]; then
		printf 'kdf-review: claude exited %s in %s, the copy is kept. Last lines of %s\n' "$rc" "$wt" "$log" >&2
		tail -n 15 "$log" >&2
		exit 6
	fi
	[ -s "$wt/$report_rel" ] || die 4 "no report at $report_rel in $wt, the copy is kept"
	mapfile -t news < <(new_files "$meta/before" "$meta/after")
	for f in "${news[@]}"; do
		[ ! -e "$repo/$f" ] || die 2 "$f already exists in $repo, nothing was copied, the copy is kept"
	done
	for f in "${news[@]}"; do
		mkdir -p "$repo/$(dirname "$f")" && cp "$wt/$f" "$repo/$f" || die 2 "could not copy $f into $repo, the copy is kept"
	done
	new_refs="$(comm -13 "$meta/refs" <(git -C "$repo" for-each-ref --format='%(refname)' | sort))"
	git -C "$repo" worktree remove --force "$wt" >/dev/null 2>&1 \
		|| printf 'kdf-review: could not remove %s, run git -C %s worktree remove --force %s\n' "$wt" "$repo" "$wt" >&2
	rm -rf "$meta"
	printf 'kdf-review: clean. %s file(s) brought into %s, report %s, %s lines\n' \
		"${#news[@]}" "$repo" "$report_rel" "$(wc -l <"$repo/$report_rel" | tr -d ' ')"
	if [ -n "$new_refs" ]; then
		printf 'kdf-review: refs made since the copy was prepared. The orchestrator makes branches too, check none is the reviewer'"'"'s.\n'
		printf '  %s\n' $new_refs
	fi
	exit 0
}

if [ -n "$collect" ]; then
	wt="$(cd "$collect" 2>/dev/null && pwd)" || die 2 "--collect $collect is not a directory"
	meta="$wt.kdf-pin"
	log="$meta/none"
	collect_copy 0
fi

# ---- 3. the brief, the prompts, and the copy's place when a commit is pinned
brief_rel="$(relative_inside "$brief")" || die 2 "the brief must be a file inside the repo"
codex_rel=""
if [ -n "$codex_report" ]; then
	codex_rel="$(relative_inside "$codex_report")" || die 2 "the Codex report must be a path inside the repo"
	case "$codex_rel" in
		docs/security/*) ;;
		*) die 2 "the Codex report must be under docs/security, not $codex_rel" ;;
	esac
fi
sha=""
if [ -n "$at" ]; then
	sha="$(git -C "$repo" rev-parse --verify --quiet "$at^{commit}")" || die 2 "--at $at is not a commit in $repo"
	git -C "$repo" cat-file -e "$sha:$brief_rel" 2>/dev/null \
		|| die 2 "the brief $brief_rel is not in commit ${sha:0:10}, commit it before pinning the review"
	if git -C "$repo" cat-file -e "$sha:$report_rel" 2>/dev/null; then
		die 2 "the report $report_rel is already in commit ${sha:0:10}"
	fi
	copies="$(dirname "$repo")/.kdf-review"
	wt="$copies/$(basename "$repo")@${sha:0:10}-$(basename "$report_rel" .md)"
	meta="$wt.kdf-pin"
	[ ! -e "$wt" ] && [ ! -e "$meta" ] || die 2 "$wt already exists, collect it or remove it first"
else
	[ -f "$repo/$brief_rel" ] || die 2 "the brief $brief_rel does not exist"
fi

prompt="Read $brief_rel and run the review, write your report to $report_rel, edit nothing else."
codex_line=""
[ -n "$codex_rel" ] && codex_line="Read $brief_rel and run the review, write your report to $codex_rel, edit nothing else."

if [ "$dry" -eq 1 ]; then
	if [ "$prepare" -eq 1 ]; then printf 'Prompt, %s\n' "$prompt"; else printf 'Claude prompt, %s\n' "$prompt"; fi
	[ -n "$codex_line" ] && printf 'Codex prompt, %s\n' "$codex_line"
	[ -n "$sha" ] && printf 'Copy, %s at %s\n' "$wt" "$sha"
	exit 0
fi

work="$(mktemp -d "${TMPDIR:-/tmp}/kdf-review.XXXXXX")"
log="$work/claude.log"

# ---- 4. the guard must be installed and wired before a Claude reviewer starts
if [ "$prepare" -eq 0 ]; then
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
fi

args=(-p "$prompt" --output-format text)
[ -n "$model" ] && args+=(--model "$model")
[ -n "$effort" ] && args+=(--effort "$effort")
runner=()
if command -v timeout >/dev/null 2>&1 && timeout --version 2>/dev/null | grep -q coreutils; then
	runner=(timeout "$timeout_s")
fi

# ---- 5. a pinned review, in a copy of its own
if [ -n "$sha" ]; then
	mkdir -p "$copies" || die 2 "could not make $copies"
	git -C "$repo" worktree add --quiet --detach "$wt" "$sha" >"$work/worktree.log" 2>&1 \
		|| { cat "$work/worktree.log" >&2; die 2 "git could not make a copy at $wt"; }
	if [ -n "$setup" ]; then
		printf 'kdf-review: setting up the copy, %s\n' "$setup"
		if ! (cd "$wt" && KDF_MAIN_REPO="$repo" bash -c "$setup") >"$work/setup.log" 2>&1; then
			tail -n 15 "$work/setup.log" >&2
			git -C "$repo" worktree remove --force "$wt" >/dev/null 2>&1
			die 7 "the setup command failed, the copy was removed. Log $work/setup.log"
		fi
	fi
	mkdir -p "$meta"
	printf 'repo=%s\nsha=%s\nreport=%s\nbrief=%s\n' "$repo" "$sha" "$report_rel" "$brief_rel" >"$meta/pin"
	snapshot "$wt" 0 >"$meta/before"
	git -C "$repo" for-each-ref --format='%(refname)' | sort >"$meta/refs"

	if [ "$prepare" -eq 1 ]; then
		printf 'kdf-review: a copy of %s at %s is ready for a reviewer you start by hand.\n' "$(basename "$repo")" "${sha:0:10}"
		printf '  Open this folder, and nothing else, in the reviewer, Codex in VS Code for example\n    %s\n' "$wt"
		printf '  Give it this one line\n    %s\n' "$prompt"
		printf '  When it has written the report, bring it home with\n    bash %s --repo %s --report %s --collect %s\n' \
			"$here/kdf-review.sh" "$repo" "$report_rel" "$wt"
		exit 0
	fi

	printf 'kdf-review: starting the reviewer in its copy %s, log %s\n' "$wt" "$log"
	(cd "$wt" && env -u KDF_GUARD_ALLOW_SELF_EDIT KDF_ROLE=reviewer "${runner[@]}" "$claude_bin" "${args[@]}") >"$log" 2>&1
	rc=$?
	if [ -n "$codex_rel" ]; then
		printf 'kdf-review: for Codex at the same commit, prepare its own copy with\n  bash %s --repo %s --brief %s --report %s --at %s --prepare' \
			"$here/kdf-review.sh" "$repo" "$brief_rel" "$codex_rel" "$sha"
		[ -n "$setup" ] && printf ' --setup %q' "$setup"
		printf '\n'
	fi
	collect_copy "$rc"
fi

# ---- 6. a review in the repo itself
snapshot "$repo" 1 >"$work/before"
printf 'kdf-review: starting the reviewer in %s, log %s\n' "$repo" "$log"
(cd "$repo" && env -u KDF_GUARD_ALLOW_SELF_EDIT KDF_ROLE=reviewer "${runner[@]}" "$claude_bin" "${args[@]}") >"$log" 2>&1
rc=$?
snapshot "$repo" 1 >"$work/after"
mapfile -t violations < <(compare "$work/before" "$work/after")
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
