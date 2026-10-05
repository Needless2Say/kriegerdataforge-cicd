#!/usr/bin/env bash
# kdf-ask-codex.sh, ask Codex for a read only review or a second opinion, the one way every session does (D-052).
#
#   bash kdf-ask-codex.sh --repo <root> --brief <file> [--at <commit>] [--base <commit>]
#   bash kdf-ask-codex.sh --files <folder> --brief <file>
#   either takes [--effort high|xhigh] [--model <model>] [--out <answer.md>] [--no-settled] [--dry-run]
#
# Repo mode reads <commit> of <root>, HEAD when --at is not given, in a detached worktree of its own. A worktree holds
# tracked files alone, so a secret file that git ignores is never in Codex's folder, and the worktree is removed when
# the run ends, failed or not. --base names the branch or commit a change is measured from, and the frame then names
# the change as a git diff from their merge base, what git diff <base>...HEAD shows, so a main that moved on is not
# read as part of it. Files mode reads a folder of files, patches from several repos for one, copied into a throwaway
# repo. It refuses a folder that is a repo, a file named like a secret file (.env*, *.pem, *.key, *.tfvars) and a file
# that holds a token's shape.
#
# The brief holds the session's question alone, and the tool sets it in the standard frame. Read only, files in this
# folder alone, PowerShell for commands since Git Bash cannot start in Codex's sandbox, the ecosystem's writing
# conventions, the owner's settled decisions from the context repo's context/SETTLED.md when that clone sits beside
# this one (--no-settled leaves them out), and real problems only. The frame reaches Codex on stdin. Codex runs with
# the flags verified on 2026-10-05, the user's config, MCP servers, plugins, apps, web search, memories and other
# agents off, a read only sandbox, and nothing kept after the run.
#
# Before it runs it refuses a session in the reviewer role (KDF_ROLE=reviewer), a missing or empty brief, a commit the
# repo does not have, and a folder that holds anything git ignores or does not track. After it runs it fails when the
# folder changed, and warns when Codex did anything but run commands, reason and answer, read from its JSON events.
# The answer, the frame and the events go to the archive, $KDF_CODEX_ARCHIVE or temp/codex in the workspace, the
# owner's local scratch and never a repo, the answer under a header with what was read, the model, the time and the
# tokens. --dry-run prints the frame and runs nothing.
#
# Exit 0 when Codex answered and changed nothing, 1 when it failed or changed its folder, 2 on a refusal before it ran.
# KDF_CODEX_BIN names the codex binary and KDF_SETTLED the settled decisions file, for a test.
set -uo pipefail
export LC_ALL=C

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workspace="$(cd "$here/../../.." && pwd)"
codex_bin="${KDF_CODEX_BIN:-codex}"
settled_file="${KDF_SETTLED-$workspace/kriegerdataforge-context/context/SETTLED.md}"
archive="${KDF_CODEX_ARCHIVE:-$workspace/temp/codex}"
# a token's shape, GitHub's, a private key's, AWS's and OpenAI's, so files mode never sends one
token_shapes='gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,}|-----BEGIN [A-Z ]*PRIVATE KEY'
token_shapes="$token_shapes|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}"

die() { local code=$1; shift; printf 'kdf-ask-codex: %s\n' "$*" >&2; exit "$code"; }
say() { printf 'kdf-ask-codex: %s\n' "$*"; }
usage() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"; }

repo="" files="" brief="" at="" base="" effort="high" model="gpt-6.1-sol" out="" settled=1 dry=0
while [ $# -gt 0 ]; do
	case "$1" in
		--repo) repo="${2:-}"; shift 2 || die 2 "--repo needs a value" ;;
		--files) files="${2:-}"; shift 2 || die 2 "--files needs a value" ;;
		--brief) brief="${2:-}"; shift 2 || die 2 "--brief needs a value" ;;
		--at) at="${2:-}"; shift 2 || die 2 "--at needs a value" ;;
		--base) base="${2:-}"; shift 2 || die 2 "--base needs a value" ;;
		--effort) effort="${2:-}"; shift 2 || die 2 "--effort needs a value" ;;
		--model) model="${2:-}"; shift 2 || die 2 "--model needs a value" ;;
		--out) out="${2:-}"; shift 2 || die 2 "--out needs a value" ;;
		--no-settled) settled=0; shift ;;
		--dry-run) dry=1; shift ;;
		-h|--help) usage; exit 0 ;;
		*) die 2 "unknown argument $1" ;;
	esac
done

# ---- 1. what may run at all
[ "${KDF_ROLE:-}" != reviewer ] || die 2 "a session in the reviewer role never asks Codex, its review is its own"
if [ -n "$repo" ] && [ -n "$files" ] || [ -z "$repo$files" ]; then
	die 2 "give --repo or --files, one of them. See --help."
fi
[ -z "$files" ] || [ -z "$at$base" ] || die 2 "--at and --base go with --repo"
[ -n "$brief" ] || die 2 "--brief is required. See --help."
[ -s "$brief" ] || die 2 "the brief $brief is missing or empty"
case "$effort" in high|xhigh) ;; *) die 2 "--effort is high or xhigh" ;; esac
command -v node >/dev/null 2>&1 || die 2 "node is not on PATH, it reads Codex's events"
[ "$dry" -eq 1 ] || command -v "$codex_bin" >/dev/null 2>&1 || die 2 "$codex_bin is not on PATH"

work="$(mktemp -d "${TMPDIR:-/tmp}/kdf-ask-codex.XXXXXX")" || die 2 "no scratch folder"
folder="$work/folder"
cleanup() {
	# the worktree is this run's alone, so a forced removal takes nothing of anyone else's
	if [ -n "$repo" ] && [ -d "$folder" ]; then
		git -C "$repo" worktree remove "$folder" >/dev/null 2>&1 \
			|| git -C "$repo" worktree remove --force "$folder" >/dev/null 2>&1
	fi
	rm -rf "$work"
}
trap cleanup EXIT

# ---- 2. the folder Codex reads, holding tracked files alone
base_commit=""
if [ -n "$repo" ]; then
	repo="$(cd "$repo" 2>/dev/null && pwd)" || die 2 "--repo is not a directory"
	top="$(git -C "$repo" rev-parse --show-toplevel 2>/dev/null)" || die 2 "$repo is not a git repository"
	commit="$(git -C "$repo" rev-parse -q --verify "${at:-HEAD}^{commit}")" || die 2 "$repo has no commit ${at:-HEAD}"
	if [ -n "$base" ]; then
		base_commit="$(git -C "$repo" rev-parse -q --verify "$base^{commit}")" || die 2 "$repo has no commit $base"
		# measured from the merge base, as git diff <base>...HEAD is, so a main that moved on is not read as the change
		base_commit="$(git -C "$repo" merge-base "$base_commit" "$commit")" \
			|| die 2 "$base and ${at:-HEAD} share no history"
	fi
	git -C "$repo" worktree add -q --detach "$folder" "$commit" >/dev/null 2>&1 || die 2 "the worktree could not be made"
	subject="$(git -C "$repo" log -1 --format=%s "$commit" | cut -c1-90)"
	what="$(basename "$top") at commit $commit, \"$subject\""
	label="$(basename "$top")-${commit:0:7}"
else
	files="$(cd "$files" 2>/dev/null && pwd)" || die 2 "--files is not a directory"
	[ ! -e "$files/.git" ] || die 2 "$files is a repo, read it with --repo"
	secret="$(find "$files" -type f \( -name '.env*' -o -name '*.pem' -o -name '*.key' -o -name '*.tfvars' \) \
		-print -quit)"
	[ -z "$secret" ] || die 2 "$secret is named like a secret file, Codex never reads one"
	! grep -r -q -E "$token_shapes" "$files" || die 2 "a file in $files holds a token's shape, nothing is sent"
	if ! {
		mkdir -p "$folder" && cp -R "$files/." "$folder/" \
			&& git -C "$folder" init -q -b main \
			&& git -C "$folder" add -A \
			&& git -C "$folder" -c user.name=kdf-ask-codex -c user.email=kdf-ask-codex@localhost commit -q -m read
	}; then
		die 2 "the throwaway repo could not be made"
	fi
	what="the files of $(basename "$files"), patches and the facts they rest on"
	label="files-$(basename "$files")"
fi
[ -z "$(git -C "$folder" status --ignored --short)" ] || die 2 "the folder holds a file git ignores or does not track"

# ---- 3. the frame, the session's question in the standard words
frame="$work/frame.md"
with_settled="no"
{
	cat <<'EOF'
You are giving a read only review or a second opinion. Read only. Read only files inside this folder, never a file
outside it. Use PowerShell for your commands, since Git Bash cannot start in your sandbox.

EOF
	printf 'What you read. %s.' "$what"
	[ -z "$base_commit" ] || printf ' The change is %s.' "git diff $base_commit..HEAD"
	printf '\n\nThe question.\n\n'
	cat "$brief"
	cat <<'EOF'


The ecosystem's conventions. Prose uses commas and periods, never dashes, colons or semicolons in sentences, and no
hyphen joining ordinary words. Lines stay within 120 characters, table rows excepted. An append only log keeps its
old entries as they were written. Do not report style beyond these.
EOF
	if [ "$settled" -eq 1 ] && [ -n "$settled_file" ] && [ -s "$settled_file" ]; then
		printf '\nThe owner'"'"'s settled decisions. Do not propose one again, report only code that contradicts one.\n\n'
		cat "$settled_file"
	fi
	cat <<'EOF'

Report only real problems, most severe first, each with the file and the line, the concrete input or state that
triggers it, and what goes wrong. If you find nothing real, say so plainly. Your answer is advice for the session that
asked, it changes nothing by itself.
EOF
} > "$frame"
if [ "$settled" -eq 1 ] && [ -n "$settled_file" ] && [ -s "$settled_file" ]; then with_settled="yes"; fi

if [ "$dry" -eq 1 ]; then
	cat "$frame"
	say "dry run, Codex was not started. It would read $what."
	exit 0
fi

# ---- 4. Codex, with the flags verified on 2026-10-05 and its events as JSON
began="$(date '+%Y-%m-%d %H:%M')"
start=$(date +%s)
(
	cd "$folder" && "$codex_bin" exec --ignore-user-config -c windows.sandbox=unelevated --ephemeral -s read-only \
		-m "$model" -c "model_reasoning_effort=$effort" -c approval_policy=never -c web_search=disabled \
		--disable memories --disable plugins --disable apps --disable multi_agent --disable image_generation \
		--disable goals --disable browser_use --disable computer_use --json -o "$work/answer.md" - \
		< "$frame" > "$work/events.jsonl" 2> "$work/stderr.txt"
)
status=$?
seconds=$(( $(date +%s) - start ))
changed="$(git -C "$folder" status --ignored --short)"

# ---- 5. what Codex did, from its events, anything but commands, reasoning, a plan and answers called strange
read -r commands tokens strange errors < <(node -e '
	const fs = require("fs");
	const allowed = new Set(["command_execution", "agent_message", "reasoning", "todo_list"]);
	const types = {};
	let tokens = 0, errors = 0;
	for (const line of fs.readFileSync(process.argv[1], "utf8").split("\n")) {
		let event;
		try { event = JSON.parse(line); } catch (err) { continue; }
		if (event.type === "item.completed" && event.item) types[event.item.type] = (types[event.item.type] || 0) + 1;
		if (event.type === "turn.completed" && event.usage) {
			tokens += (event.usage.input_tokens || 0) + (event.usage.output_tokens || 0);
		}
		if (event.type === "error" || event.type === "turn.failed") errors += 1;
	}
	const strange = Object.keys(types).filter((type) => !allowed.has(type)).join(",") || "none";
	console.log([types.command_execution || 0, tokens, strange, errors].join(" "));
' "$work/events.jsonl" 2>/dev/null || echo "0 0 unread 0")

# ---- 6. the archive, then the verdict
mkdir -p "$archive" || die 1 "the archive $archive could not be made"
answer="${out:-$archive/$(date '+%Y-%m-%d-%H%M%S')-$label.md}"
{
	printf '# Codex on %s\n\n' "$what"
	printf -- '- **Asked.** %s, %s seconds, %s tokens, %s commands, %s at %s effort.\n' \
		"$began" "$seconds" "$tokens" "$commands" "$model" "$effort"
	printf -- '- **Settled decisions in the frame.** %s.\n' "$with_settled"
	printf -- '- **Outside the shell.** %s.\n\n' "$strange"
	if [ -s "$work/answer.md" ]; then cat "$work/answer.md"; else printf '(no answer was written)\n'; fi
} > "$answer" || die 1 "the answer could not be written to $answer"
cp "$frame" "${answer%.md}.frame.md"
cp "$work/events.jsonl" "${answer%.md}.events.jsonl"

if [ "$strange" != none ]; then
	say "WARNING Codex did more than run commands and answer, $strange, read ${answer%.md}.events.jsonl"
fi
if [ -n "$changed" ]; then
	die 1 "Codex changed its folder, which a read only run never does. $(printf '%s' "$changed" | head -3 | tr '\n' ' ')"
fi
if [ "$status" -ne 0 ] || [ "$errors" != 0 ]; then
	die 1 "codex exited $status with $errors errors, $(tail -3 "$work/stderr.txt" | tr '\n' ' ')"
fi
say "answered in $seconds seconds, $tokens tokens, $commands commands, its folder unchanged"
say "the answer is $answer"
