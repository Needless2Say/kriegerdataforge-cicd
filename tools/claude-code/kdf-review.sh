#!/usr/bin/env bash
# kdf-review.sh, run one fresh reviewer the KDF Code Review Process way, in the repo folder itself.
#
#   Claude
#     bash kdf-review.sh --repo <root> --brief <file> --report <file> [--codex-report <file>] [--pin <commit>]
#                        [--model <m>] [--effort <e>] [--timeout <s>] [--dry-run]
#   Codex, or any reviewer the owner starts by hand, in the same folder
#     bash kdf-review.sh --repo <root> --brief <file> --report <file> --codex-report <file> --pin <commit> --prepare
#     bash kdf-review.sh --repo <root> --collect
#   Codex in the cloud, which reads the pushed pin on GitHub and hands its report back on a branch
#     bash kdf-review.sh --repo <root> --codex-report <file> --pin <commit> --collect-branch <branch>
#
# Every reviewer reads the repo folder itself, with no copy of it and no second environment. --pin first checks that
# the pin is pushed to origin, that the folder is at it with no tracked file changed, and that the brief's scope table
# matches it (kdf-brief.js check), so every reviewer of a scope reads the same state. One review of a folder is open
# at a time, and nothing else changes the folder while it is.
#
# Claude. The launcher checks the arguments and the guard, snapshots git, runs claude -p with KDF_ROLE=reviewer and
# without the owner's self edit switch, snapshots again, and fails the run when anything but a new file under
# docs/reviews, the review archive, changed. The review opens when claude starts and closes when it ends. --timeout
# stops a reviewer that runs longer, 14400 seconds by default, four hours, since a slice's first read has taken three.
# The run's log is claude's stream-json, one event a line as the run goes, so a detached run is watched by its log. A
# clean run leaves Claude Code's own count of it beside the report, <report stem>.usage.json, read from the stream's
# last result event, the models, the start and end, the duration, the turns, the tokens and the cost, so a
# retrospective measures the run rather than reading what the reviewer wrote about itself. The report is never touched.
#
# A reviewer without the guard, Codex. --prepare checks the pin, snapshots git, opens the review, and prints the one
# line the owner gives the reviewer in this folder. --collect, once the report is written, checks git the same way and
# closes the review. A failed check leaves the review open, put right what the reviewer changed and collect again.
#
# No reviewer sees another's report of the scope, nor the scratch notes the other left beside it. While a review is
# open the other report, and every other untracked file in the brief's folder, waits in the repo's .git/kdf-review
# folder, out of the working tree, and closing the review puts each back.
#
# Codex in the cloud. --collect-branch fetches the branch Codex's pull request came from, checks that it is built on
# the pin and adds nothing but new files under docs/reviews, and writes the report into the folder. The owner closes
# that pull request unmerged. Every collect warns when a report's header does not name the pin or what it read first,
# and when it lacks the Time spent line with the clock's start and end, or the Usage line, that a retrospective reads
# for a reviewer the launcher did not start.
#
# Exit codes. 0 clean. 2 bad arguments, the folder is not at the pin, or another review of it is open. 3 the reviewer
# changed something it must not, nothing is reverted. 4 no report was written. 5 the guard is not installed or wired.
# 6 claude itself failed or ran past --timeout, or a Claude run was cut off before it closed its review.
#
# The reviewer writes its report, the owner or the orchestrator reads it. Nothing here reverts a change, it reports.
set -uo pipefail
export LC_ALL=C

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
home="${KDF_HOME:-$HOME}"
claude_bin="${KDF_CLAUDE_BIN:-claude}"

die() { local code=$1; shift; printf 'kdf-review: %s\n' "$*" >&2; exit "$code"; }
usage() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"; }

repo="" brief="" report="" model="" effort="" codex_report="" timeout_s=14400 dry=0 pin="" prepare=0 collect=0
collect_branch=""
while [ $# -gt 0 ]; do
	case "$1" in
		--repo) repo="${2:-}"; shift 2 || die 2 "--repo needs a value" ;;
		--brief) brief="${2:-}"; shift 2 || die 2 "--brief needs a value" ;;
		--report) report="${2:-}"; shift 2 || die 2 "--report needs a value" ;;
		--model) model="${2:-}"; shift 2 || die 2 "--model needs a value" ;;
		--effort) effort="${2:-}"; shift 2 || die 2 "--effort needs a value" ;;
		--timeout) timeout_s="${2:-}"; shift 2 || die 2 "--timeout needs a value" ;;
		--codex-report) codex_report="${2:-}"; shift 2 || die 2 "--codex-report needs a value" ;;
		--pin) pin="${2:-}"; shift 2 || die 2 "--pin needs a value" ;;
		--prepare) prepare=1; shift ;;
		--collect) collect=1; shift ;;
		--collect-branch) collect_branch="${2:-}"; shift 2 || die 2 "--collect-branch needs a value" ;;
		--dry-run) dry=1; shift ;;
		-h|--help) usage; exit 0 ;;
		*) die 2 "unknown argument $1" ;;
	esac
done
if [ -n "$collect_branch" ]; then
	[ -n "$repo" ] && [ -n "$codex_report" ] && [ -n "$pin" ] \
		|| die 2 "--collect-branch needs --repo, --codex-report and --pin. See --help."
	[ -z "$brief$report$model$effort" ] && [ "$prepare$collect$dry" = 000 ] \
		|| die 2 "--collect-branch takes only --repo, --codex-report and --pin"
elif [ "$collect" -eq 1 ]; then
	[ -n "$repo" ] || die 2 "--collect needs --repo. See --help."
	[ -z "$brief$report$codex_report$pin$model$effort" ] && [ "$prepare$dry" = 00 ] \
		|| die 2 "--collect takes only --repo, the open review names the rest"
elif [ "$prepare" -eq 1 ]; then
	[ -n "$repo" ] && [ -n "$brief" ] && [ -n "$report" ] && [ -n "$codex_report" ] && [ -n "$pin" ] \
		|| die 2 "--prepare needs --repo, --brief, --report, --codex-report and --pin. See --help."
else
	[ -n "$repo" ] && [ -n "$brief" ] && [ -n "$report" ] || die 2 "--repo, --brief and --report are required. See --help."
fi

# ---- 1. the repo, and the folder in its git directory where an open review keeps its state
repo="$(cd "$repo" 2>/dev/null && pwd)" || die 2 "--repo is not a directory"
top="$(git -C "$repo" rev-parse --show-toplevel 2>/dev/null)" || die 2 "$repo is not a git repository"
[ "$(cd "$top" && pwd)" = "$repo" ] || die 2 "start from the repo root, $top, so the guard's project directory is the repo"
gitdir="$(git -C "$repo" rev-parse --git-dir)"
case "$gitdir" in
	/*|[A-Za-z]:*) ;;
	*) gitdir="$repo/$gitdir" ;;
esac
hold="$gitdir/kdf-review"
open="$hold/open"

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

# snapshot, what a reviewer could change in git and in the tree
snapshot() {
	{
		printf 'HEAD|%s\n' "$(git -C "$repo" rev-parse HEAD 2>/dev/null || echo none)"
		printf 'BRANCH|%s\n' "$(git -C "$repo" symbolic-ref -q --short HEAD 2>/dev/null || echo detached)"
		# every local ref and the stash, never the remote tracking refs, which an editor's background fetch moves,
		# nor refs/codex/, where Codex's editor extension writes a checkpoint of its own each turn, a tree that no
		# branch, tag or push names, so a clean Codex review was refused until the owner deleted the ref by hand
		printf 'REFS|%s\n' "$(git -C "$repo" for-each-ref --format='%(refname) %(objectname)' \
			| grep -v -E '^refs/(remotes|codex)/' | git hash-object --stdin)"
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

# compare <before> <after>, one line per thing the reviewer must not have done. Only a NEW file under docs/reviews is
# allowed, so a tracked file there, a brief, a plan, a log or an earlier report, counts as changed like any other.
compare() {
	local before=$1 after=$2 line f head
	head="$(sed -n 's/^HEAD|//p' "$before")"
	while IFS= read -r line; do
		case "$line" in
			FILE\|*) ;;
			*) printf 'git state changed, %s\n' "${line%%|*}" ;;
		esac
	done < <(comm -3 "$before" "$after" | sed 's/^[[:space:]]*//' | grep -v '^FILE|' | sort -u)
	while IFS= read -r line; do
		f="${line#FILE|}"
		f="${f%|*}"
		if grep -qF -- "FILE|$f|" "$before" || git -C "$repo" cat-file -e "$head:$f" 2>/dev/null; then
			printf 'changed, %s\n' "$f"
		else
			case "$f" in
				docs/reviews/*) ;;
				*) printf 'new file outside docs/reviews, %s\n' "$f" ;;
			esac
		fi
	done < <(comm -13 "$before" "$after" | grep '^FILE|')
	while IFS= read -r line; do
		f="${line#FILE|}"
		f="${f%|*}"
		grep -qF -- "FILE|$f|" "$after" || printf 'removed or reverted, %s\n' "$f"
	done < <(comm -23 "$before" "$after" | grep '^FILE|')
}

# ---- 2. one open review per folder, and the other report of the scope held out of the tree while it is open
meta() { sed -n "s/^$1=//p" "$open/meta" 2>/dev/null; }

# open_review <reviewer> <the report it writes> <the other report of the scope, or nothing>
open_review() {
	mkdir -p "$hold" || die 2 "could not make $hold"
	if ! mkdir "$open" 2>/dev/null; then
		printf 'kdf-review: a review of %s is open, %s writing %s\n' "$repo" "$(meta reviewer)" "$(meta report)" >&2
		die 2 "one review of a folder at a time. Close it with --collect first"
	fi
	printf 'reviewer=%s\nreport=%s\nother=%s\nbrief=%s\npin=%s\npid=%s\n' \
		"$1" "$2" "$3" "$brief_rel" "$sha" "$$" >"$open/meta"
	: >"$open/held"
}

# hold_out <path>, moves a report of the scope out of the tree while another reviewer reads
hold_out() {
	local f=$1
	[ -n "$f" ] && [ -e "$repo/$f" ] || return 0
	[ ! -e "$hold/held/$f" ] || die 2 "$hold/held/$f is in the way, move it back into the repo first"
	mkdir -p "$(dirname "$hold/held/$f")" && mv "$repo/$f" "$hold/held/$f" || die 2 "could not move $f out of the tree"
	printf '%s\n' "$f" >>"$open/held"
}

# hold_notes, whatever else the other reviewer left in the brief's folder. A brief lets a reviewer keep scratch
# notes and probes beside its report, and they say what it found as plainly as the report does. A review of the SDK
# left three, and the orchestrator moved them out by hand. Only under docs/reviews, the archive, and at the
# archive's own root only the files that sit in it, the folders below are other reviews
hold_notes() {
	local dir f
	dir="$(dirname "$brief_rel")"
	case "$dir" in
		docs/reviews|docs/reviews/*) ;;
		*) return 0 ;;
	esac
	while IFS= read -r -d '' f; do
		[ "$dir" != docs/reviews ] || [ "$(dirname "$f")" = docs/reviews ] || continue
		hold_out "$f"
	done < <(git -C "$repo" ls-files -z -o --exclude-standard -- "$dir/")
}

# close_review, puts every held report back, never over a file, and closes the review
close_review() {
	local f
	[ -d "$open" ] || return 0
	while IFS= read -r f; do
		[ -n "$f" ] || continue
		if [ -e "$repo/$f" ]; then
			printf 'kdf-review: %s is in the tree again, the held one stays at %s\n' "$f" "$hold/held/$f" >&2
		else
			mv "$hold/held/$f" "$repo/$f" || printf 'kdf-review: could not put %s back, it is at %s\n' "$f" "$hold/held/$f" >&2
		fi
	done <"$open/held"
	rm -rf "$open"
}

# check_header <report file> <pin or nothing>, a warning when the header does not show what the reviewer read
check_header() {
	if [ -n "$2" ] && ! grep -q "${2:0:7}" "$1"; then
		printf 'kdf-review: warning, %s does not name the pin %s it read. Check its header.\n' "$1" "${2:0:10}" >&2
	fi
	grep -qi 'read first' "$1" \
		|| printf 'kdf-review: warning, %s does not list the files it read first. Check its header.\n' "$1" >&2
}

# check_time_lines <report file>, a warning when a report the launcher did not start lacks what a retrospective
# measures it by, a Time spent line holding the clock's start and end, and a Usage line. Seven of the twelve reports
# of the kdf-sdk's first slice gave minutes no tool could read, in words, as an estimate, or folded into another line
check_time_lines() {
	local spent
	spent="$(header_line "$1" 'time spent')"
	[ -n "$spent" ] || spent="$(header_line "$1" time)"
	if [ -z "$spent" ]; then
		printf 'kdf-review: warning, %s has no Time spent line, so its minutes are unknown. Check its header.\n' "$1" >&2
	elif [ "$(printf '%s\n' "$spent" | grep -oE '[0-9]{1,2}:[0-9]{2}' | wc -l | tr -d ' ')" -lt 2 ]; then
		printf 'kdf-review: warning, %s gives its time without the clock. %s\n' "$1" \
			'The template asks for From HH:MM to HH:MM.' >&2
	fi
	[ -n "$(header_line "$1" usage)$(header_line "$1" tokens)" ] \
		|| printf 'kdf-review: warning, %s has no Usage line, so its tokens are unknown. Check its header.\n' "$1" >&2
}

# header_line <report file> <label>, the first header line, "- **Label.** value", whose label is the one asked for or
# shares a line with it, "- **Reviewer / usage.**", the label's case and its closing period or colon set aside. The
# same reading kdf-retro.js makes
header_line() {
	awk -v want="$2" '
		match($0, /^[[:space:]]*-[[:space:]]*\*\*[^*]+\*\*/) {
			label = tolower(substr($0, RSTART, RLENGTH))
			sub(/^[[:space:]]*-[[:space:]]*\*\*/, "", label)
			sub(/[.:]?\*\*$/, "", label)
			n = split(label, parts, "/")
			for (i = 1; i <= n; i++) {
				part = parts[i]
				gsub(/^[[:space:]]+|[[:space:]]+$/, "", part)
				if (part == want) { print; exit }
			}
		}' "$1"
}

# usage_path <report path>, where the launcher writes Claude Code's own count of a run, beside the report
usage_path() {
	case "$1" in
		*.md) printf '%s.usage.json' "${1%.md}" ;;
		*) printf '%s.usage.json' "$1" ;;
	esac
}

# The run's log is claude's stream, one JSON event a line as the run goes, with what claude writes on stderr between
# them. Its result is the last event whose type is result, which claude writes when the run ends, so a run that was
# stopped or crashed has none. Lines that are not JSON, a warning, a cut off last line, are passed over
LAST_RESULT_JS='
const lastResult = (file) => {
  let lines;
  try { lines = require("fs").readFileSync(file, "utf8").split(/\r?\n/); } catch (err) { return null; }
  for (let k = lines.length - 1; k >= 0; k--) {
    const line = lines[k].trim();
    if (!line.startsWith("{")) continue;
    let event;
    try { event = JSON.parse(line); } catch (err) { continue; }
    if (event && typeof event === "object" && !Array.isArray(event) && event.type === "result") return event;
  }
  return null;
};
'

# write_usage <the run's log> <the usage file>, Claude Code's own count of the run, read from the result event at the
# end of its stream. The models, the start and end the launcher saw, the duration, the turns, the tokens summed over
# every model, and the cost. Never the result's text and never the report. A log with no result writes nothing and fails
write_usage() {
	node -e "$LAST_RESULT_JS"'
const fs = require("fs");
const [from, to, report, pin, asked, effort, started, ended] = process.argv.slice(1);
const r = lastResult(from);
if (!r) process.exit(1);
const per = r.modelUsage && typeof r.modelUsage === "object" ? r.modelUsage : {};
const models = Object.keys(per);
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const add = (k) => models.reduce((n, m) => n + (num(per[m][k]) || 0), 0);
const u = r.usage && typeof r.usage === "object" ? r.usage : {};
const tokens = models.length
  ? { input: add("inputTokens"), cache_read: add("cacheReadInputTokens"),
      cache_creation: add("cacheCreationInputTokens"), output: add("outputTokens") }
  : { input: num(u.input_tokens), cache_read: num(u.cache_read_input_tokens),
      cache_creation: num(u.cache_creation_input_tokens), output: num(u.output_tokens) };
const record = {
  written_by: "kdf-review.sh, from the JSON result of claude -p",
  report, pin: pin || null, model_asked: asked || null, effort: effort || null, models,
  started_at: started, ended_at: ended,
  duration_ms: num(r.duration_ms), duration_api_ms: num(r.duration_api_ms), num_turns: num(r.num_turns),
  tokens, total_cost_usd: num(r.total_cost_usd),
  by_model: Object.fromEntries(models.map((m) => [m, {
    input: num(per[m].inputTokens), cache_read: num(per[m].cacheReadInputTokens),
    cache_creation: num(per[m].cacheCreationInputTokens), output: num(per[m].outputTokens),
    cost_usd: num(per[m].costUSD) }]))
};
fs.writeFileSync(to, JSON.stringify(record, null, 2) + "\n");
' "$1" "$2" "$report_rel" "$sha" "$model" "$effort" "$started_at" "$ended_at"
}

# result_says <the run's log>, what a failed run's result event gives as its reason, on one line. Exit 1 when the log
# holds no result event, exit 2 when it holds one that gives no reason
result_says() {
	node -e "$LAST_RESULT_JS"'
const r = lastResult(process.argv[1]);
if (!r) process.exit(1);
const said = [r.subtype, r.api_error_status, typeof r.result === "string" ? r.result : ""].filter(Boolean).join(", ");
if (!said) process.exit(2);
process.stdout.write(said.replace(/\s+/g, " ").slice(0, 400));
' "$1" 2>/dev/null
}

# pinned <commit>, the full sha of a commit origin holds, or a refusal
pinned() {
	local s
	s="$(git -C "$repo" rev-parse --verify --quiet "$1^{commit}")" || die 2 "--pin $1 is not a commit in $repo"
	[ -n "$(git -C "$repo" for-each-ref --contains "$s" --format='%(refname)' refs/remotes/origin)" ] \
		|| die 2 "the pin ${s:0:10} is on no branch of origin. Push it first, every reviewer and Sol read a pushed commit"
	printf '%s' "$s"
}

# ---- 3. collect, the end of a review the owner started by hand
if [ "$collect" -eq 1 ]; then
	[ -f "$open/meta" ] || die 2 "no review of $repo is open"
	if [ "$(meta reviewer)" = claude ]; then
		kill -0 "$(meta pid)" 2>/dev/null && die 2 "a Claude reviewer is running in $repo, its review closes itself when it ends"
		close_review
		die 6 "the Claude run that opened this review was cut off before it closed it. The held reports are back, run it again"
	fi
	codex_rel="$(meta report)"
	[ -s "$open/before" ] || die 2 "the open review holds no snapshot to check against. Look in $open before removing it"
	snapshot >"$open/after"
	mapfile -t violations < <(compare "$open/before" "$open/after")
	if [ "${#violations[@]}" -gt 0 ]; then
		printf 'kdf-review: CONTAMINATION. The reviewer changed what it must not. Nothing was reverted.\n' >&2
		printf '  %s\n' "${violations[@]}" | sort -u >&2
		die 3 "the review stays open. Put right what the reviewer changed, then run --collect again"
	fi
	[ -s "$repo/$codex_rel" ] || die 4 "no report at $codex_rel yet, the review stays open"
	pin_read="$(meta pin)"
	close_review
	printf 'kdf-review: clean. Report %s, %s lines. The review of %s is closed\n' \
		"$codex_rel" "$(wc -l <"$repo/$codex_rel" | tr -d ' ')" "$(basename "$repo")"
	check_header "$repo/$codex_rel" "$pin_read"
	check_time_lines "$repo/$codex_rel"
	exit 0
fi

# ---- 3b. collect a report Codex in the cloud wrote, from the branch its pull request came from
if [ -n "$collect_branch" ]; then
	[ ! -d "$open" ] || die 2 "a review of $repo is open. Close it with --collect before a cloud report comes in"
	codex_rel="$(relative_inside "$codex_report")" || die 2 "the Codex report must be a path inside the repo"
	case "$codex_rel" in
		docs/reviews/*) ;;
		*) die 2 "the Codex report must be under docs/reviews, not $codex_rel" ;;
	esac
	sha="$(pinned "$pin")" || exit 2
	[ ! -e "$repo/$codex_rel" ] || die 2 "the report $codex_rel already exists in $repo, a report is never overwritten"
	git -C "$repo" fetch --quiet origin "refs/heads/$collect_branch" 2>/dev/null \
		|| die 2 "origin has no branch $collect_branch"
	tip="$(git -C "$repo" rev-parse FETCH_HEAD)"
	git -C "$repo" merge-base --is-ancestor "$sha" "$tip" \
		|| die 2 "$collect_branch is not built on the pin ${sha:0:10}, so its reviewer read something else"
	mapfile -t violations < <(git -C "$repo" diff --name-status --no-renames "$sha" "$tip" \
		| awk -F '\t' '!($1 == "A" && $2 ~ /^docs\/reviews\//) { print $1 ", " $2 }')
	if [ "${#violations[@]}" -gt 0 ]; then
		printf 'kdf-review: CONTAMINATION. %s changes more than new files under docs/reviews.\n' "$collect_branch" >&2
		printf '  %s\n' "${violations[@]}" >&2
		die 3 "nothing was brought in. Close that pull request unmerged and look at what the reviewer changed"
	fi
	git -C "$repo" cat-file -e "$tip:$codex_rel" 2>/dev/null || die 4 "$collect_branch holds no report at $codex_rel"
	mkdir -p "$(dirname "$repo/$codex_rel")" && git -C "$repo" show "$tip:$codex_rel" >"$repo/$codex_rel" \
		|| die 2 "could not write $codex_rel"
	printf 'kdf-review: clean. Report %s, %s lines, from %s at %s. Close its pull request unmerged.\n' \
		"$codex_rel" "$(wc -l <"$repo/$codex_rel" | tr -d ' ')" "$collect_branch" "${tip:0:10}"
	check_header "$repo/$codex_rel" "$sha"
	check_time_lines "$repo/$codex_rel"
	exit 0
fi

# ---- 4. the brief, the reports and the pin
brief_rel="$(relative_inside "$brief")" || die 2 "the brief must be a file inside the repo"
report_rel="$(relative_inside "$report")" || die 2 "the report must be a path inside the repo"
case "$report_rel" in
	docs/reviews/*) ;;
	*) die 2 "the report must be under docs/reviews, not $report_rel" ;;
esac
codex_rel=""
if [ -n "$codex_report" ]; then
	codex_rel="$(relative_inside "$codex_report")" || die 2 "the Codex report must be a path inside the repo"
	case "$codex_rel" in
		docs/reviews/*) ;;
		*) die 2 "the Codex report must be under docs/reviews, not $codex_rel" ;;
	esac
	[ "$codex_rel" != "$report_rel" ] || die 2 "the Claude report and the Codex report must be two files"
fi
sha=""
if [ -n "$pin" ]; then
	sha="$(pinned "$pin")" || exit 2
	at="$(git -C "$repo" rev-parse HEAD)"
	[ "$at" = "$sha" ] || die 2 "$(basename "$repo") is at ${at:0:10}, not at the pin ${sha:0:10}. Check the pin out first"
	[ -z "$(git -C "$repo" status --porcelain --untracked-files=no)" ] \
		|| die 2 "a tracked file differs from the pin. Commit it into the pin, or put it back, first"
	git -C "$repo" cat-file -e "$sha:$brief_rel" 2>/dev/null || die 2 "the brief $brief_rel is not in the pin, commit it first"
	command -v node >/dev/null 2>&1 || die 5 "node is not on PATH, and a pinned review checks the brief with kdf-brief.js"
	node "$here/kdf-brief.js" check --repo "$repo" --pin "$sha" "$brief_rel" >&2 \
		|| die 2 "the brief's scope table does not match the pin. Measure it with kdf-brief.js counts, commit and pin again"
else
	[ -f "$repo/$brief_rel" ] || die 2 "the brief $brief_rel does not exist"
fi
if [ "$prepare" -eq 1 ]; then mine="$codex_rel"; else mine="$report_rel"; fi
[ ! -e "$repo/$mine" ] || die 2 "the report $mine already exists, a review never overwrites one"
[ ! -e "$hold/held/$mine" ] || die 2 "the report $mine is held by an open review of this folder, close it with --collect first"

claude_line="Read $brief_rel and run the review, write your report to $report_rel, edit nothing else."
codex_line=""
[ -n "$codex_rel" ] && codex_line="Read $brief_rel and run the review, write your report to $codex_rel, edit nothing else."

if [ "$dry" -eq 1 ]; then
	[ "$prepare" -eq 1 ] || printf 'Claude prompt, %s\n' "$claude_line"
	[ -n "$codex_line" ] && printf 'Codex prompt, %s\n' "$codex_line"
	[ -n "$sha" ] && printf 'Pin, %s\n' "$sha"
	exit 0
fi

# ---- 5. a reviewer the owner starts by hand reads this folder next
if [ "$prepare" -eq 1 ]; then
	open_review codex "$codex_rel" "$report_rel"
	trap close_review EXIT
	hold_out "$report_rel"
	hold_notes
	snapshot >"$open/before"
	trap - EXIT
	folder="$repo"
	command -v cygpath >/dev/null 2>&1 && folder="$(cygpath -w "$repo")"
	printf 'kdf-review: %s is at the pin %s, and its review is open for one reviewer you start by hand.\n' \
		"$(basename "$repo")" "${sha:0:10}"
	printf '  Open this folder in the reviewer, Codex in VS Code for example\n    %s\n' "$folder"
	printf '  Give it this one line\n    %s\n' "$codex_line"
	printf '  Change nothing in the folder meanwhile. When the report is written, close the review with\n'
	printf '    bash %s --repo %s --collect\n' "$here/kdf-review.sh" "$repo"
	exit 0
fi

# ---- 6. a Claude reviewer, which needs the guard installed and wired
work="$(mktemp -d "${TMPDIR:-/tmp}/kdf-review.XXXXXX")"
log="$work/claude.log"
usage_rel="$(usage_path "$report_rel")"
[ ! -e "$repo/$usage_rel" ] \
	|| die 2 "$usage_rel already exists, it belongs to an earlier run of this report. Move it first"
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

# stream-json writes each event of the run as it happens, so a detached run's log shows its progress, and its last
# event is the result the usage file is read from. --verbose is what stream-json needs with -p
args=(-p "$claude_line" --output-format stream-json --verbose)
[ -n "$model" ] && args+=(--model "$model")
[ -n "$effort" ] && args+=(--effort "$effort")
runner=()
if command -v timeout >/dev/null 2>&1 && timeout --version 2>/dev/null | grep -q coreutils; then
	runner=(timeout "$timeout_s")
fi

open_review claude "$report_rel" "$codex_rel"
trap close_review EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
hold_out "$codex_rel"
hold_notes
snapshot >"$work/before"
printf 'kdf-review: starting the reviewer in %s, for at most %s seconds, its log %s\n' "$repo" "$timeout_s" "$log"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# stdin from /dev/null, or claude waits for piped input before it starts
(cd "$repo" && env -u KDF_GUARD_ALLOW_SELF_EDIT KDF_ROLE=reviewer "${runner[@]}" "$claude_bin" "${args[@]}") \
	</dev/null >"$log" 2>&1
rc=$?
ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
snapshot >"$work/after"
mapfile -t violations < <(compare "$work/before" "$work/after")
if [ "${#violations[@]}" -gt 0 ]; then
	printf 'kdf-review: CONTAMINATION. The reviewer changed what it must not. Nothing was reverted.\n' >&2
	printf '  %s\n' "${violations[@]}" | sort -u >&2
	printf 'kdf-review: log %s\n' "$log" >&2
	exit 3
fi
if [ "$rc" -ne 0 ]; then
	if [ "$rc" -eq 124 ] && [ "${#runner[@]}" -gt 0 ]; then
		printf 'kdf-review: the reviewer ran past --timeout %s seconds and was stopped\n' "$timeout_s" >&2
	else
		printf 'kdf-review: claude exited %s\n' "$rc" >&2
	fi
	said="$(result_says "$log")"
	case $? in
		0) printf 'kdf-review: its result says, %s\n' "$said" >&2 ;;
		1) printf 'kdf-review: its log holds no result, the run ended before claude wrote one\n' >&2 ;;
	esac
	# an event of the stream can be a whole file a tool read, so each line is cut short
	printf 'kdf-review: last lines of %s\n' "$log" >&2
	tail -n 15 "$log" | cut -c 1-300 >&2
	exit 6
fi
[ -s "$repo/$report_rel" ] || die 4 "the reviewer wrote no report at $report_rel, see $log"

printf 'kdf-review: clean. Report %s, %s lines, log %s\n' "$report_rel" "$(wc -l <"$repo/$report_rel" | tr -d ' ')" "$log"
if write_usage "$log" "$repo/$usage_rel"; then
	printf 'kdf-review: Claude Code counted the run, %s\n' "$usage_rel"
else
	printf 'kdf-review: warning, the log holds no result from claude, so the run has no usage file. See %s\n' "$log" >&2
fi
check_header "$repo/$report_rel" "$sha"
if [ -n "$codex_rel" ] && [ ! -e "$repo/$codex_rel" ] && [ ! -e "$hold/held/$codex_rel" ]; then
	printf 'kdf-review: next, open the folder for Codex at the same commit with\n'
	printf '  bash %s --repo %s --brief %s --report %s --codex-report %s --pin %s --prepare\n' \
		"$here/kdf-review.sh" "$repo" "$brief_rel" "$report_rel" "$codex_rel" "${sha:-$(git -C "$repo" rev-parse HEAD)}"
	printf 'kdf-review: for Codex, %s\n' "$codex_line"
fi
exit 0
