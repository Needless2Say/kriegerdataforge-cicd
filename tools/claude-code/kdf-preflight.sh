#!/usr/bin/env bash
# kdf-preflight.sh, a Linux pre-flight of a repo's CI lanes in a container, the one way every session runs one (D-072).
#
#   bash kdf-preflight.sh --repo <root> --lane <lane> [--lane <lane>]... [--at <commit>] [--keep] [--timeout <seconds>]
#
# A lane is a ci-* target on its own line in the repo's Makefile at the commit, or actionlint, the image's actionlint
# with ShellCheck over the repo's workflows. A lane holding one of the guard's owner only make words, such as deploy,
# release, publish or prod, or dev without local, is refused as a typed make of it is, and so is ci-version-check,
# which compares VERSION against origin/main, a history an archive does not have. The lanes run in the order given.
#
# The commit is --at, resolved to its full hash, or HEAD on a clean tree. A tree with changes or with untracked files
# git does not ignore is refused with no --at, since the run would leave them out unseen. Every GIT_ variable is dropped
# first, so none points the tool anywhere else. A tracked file named like a secret file, the names kdf-ask-codex.sh
# refuses but an .env example, refuses the run before anything is exported, since a build's layers outlive the run, and
# a token's shape in tracked content is listed as a warning and not refused, since that text is already in git.
#
# Docker must reach this machine alone. The tool refuses, before it sends anything, while DOCKER_HOST, DOCKER_CONTEXT,
# DOCKER_CONFIG, BUILDX_BUILDER or BUILDX_CONFIG is set, while ~/.docker/config.json names a current context other than
# default or desktop-linux, read as the guard reads it, and while ~/.docker/buildx/current chooses a builder other than
# the engine's own. Every docker option it passes is on the guard's list for build and rmi, and it never runs docker
# run, exec or anything that cleans the daemon as a whole.
#
# The run's folder, <workspace>/temp/kdf-preflight/<run id>/, holds context/, which is the commit's tar from git archive
# with LF line ends beside the image's Dockerfile and lane script and nothing else, and build.log. The base stage is
# built first and alone, tagged kdf-preflight-base:<the Dockerfile's hash>, then the lanes stage, tagged
# kdf-preflight-run:<run id> and removed with docker rmi when the run ends, failed or not. Each build runs under timeout
# with what remains of --timeout, 1800 seconds unless given, and each lane under its own inside the container. The
# result is read from the marker lines holding the run id that the image's last step prints, never from the build's
# status. A lane that fails on a private package is reported in the pull request as a skipped pre-flight, and the tool
# says so when git's credential failure is in the log.
#
# Exit 0 when every lane passed, 1 when a lane failed, 2 on a refusal before anything was built, 3 when the run could
# not complete, a base that would not build, docker unreachable, the run past its timeout, or no whole set of marker
# lines, with the log's tail. The folder is removed on 0 unless --keep is given and on 2, and kept on 1 and 3.
# KDF_DOCKER_BIN names the docker program and KDF_PREFLIGHT_DIR the runs folder, for a test.
set -uo pipefail
export LC_ALL=C
# git finds its repo, its config and its programs through GIT_ variables first, and the tool needs none of them
while IFS= read -r variable; do unset "$variable"; done < <(compgen -e | grep '^GIT_')

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workspace="$(cd "$here/../../.." && pwd)"
docker_bin="${KDF_DOCKER_BIN:-docker}"
runs="${KDF_PREFLIGHT_DIR:-$workspace/temp/kdf-preflight}"
# a token's shape, GitHub's, a private key's, AWS's and OpenAI's, the shapes kdf-ask-codex.sh screens for
token_shapes='gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,}|-----BEGIN [A-Z ]*PRIVATE KEY'
token_shapes="$token_shapes|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}"
# the names of secret files, matched in any case, exactly kdf-ask-codex.sh's
secret_globs=('.env*' '*.pem' '*.key' '*.p12' '*.pfx' '*.tfvars' '*.tfstate*' 'id_rsa*' 'id_dsa*' 'id_ecdsa*'
	'id_ed25519*' '.git-credentials' '.netrc')

die() { local code=$1; shift; printf 'kdf-preflight: %s\n' "$*" >&2; exit "$code"; }
say() { printf 'kdf-preflight: %s\n' "$*"; }
usage() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"; }
# whether a tracked path is named like a secret file or sits under a keys folder, judged from the name alone. An .env
# example is no secret, as the guard holds, and anything under keys/ is one whatever its name
secret_name() {
	local path="${1,,}" glob
	case "/$path" in */keys/*) return 0 ;; esac
	case "${path##*/}" in .env*.example) return 1 ;; esac
	for glob in "${secret_globs[@]}"; do
		# shellcheck disable=SC2254 # the glob is a pattern on purpose
		case "${path##*/}" in $glob) return 0 ;; esac
	done
	return 1
}
# whether a lane holds a word of the guard's owner only make targets, REMOTE_MAKE_WORDS in kdf-guard.js, or names dev
# without local, split on the guard's separators
owner_lane() {
	local word dev=0 named_local=0
	for word in ${1//[-_.:\/]/ }; do
		case "$word" in
			prod|production|deploy|apply|destroy|publish|release|promote|rollout) return 0 ;;
			dev) dev=1 ;;
			local) named_local=1 ;;
		esac
	done
	[ "$dev" -eq 1 ] && [ "$named_local" -eq 0 ]
}

repo="" at="" keep=0 timeout_s=1800
lanes=()
while [ $# -gt 0 ]; do
	case "$1" in
		--repo) repo="${2:-}"; shift 2 || die 2 "--repo needs a value" ;;
		--at) at="${2:-}"; shift 2 || die 2 "--at needs a value" ;;
		--lane)
			[ $# -ge 2 ] || die 2 "--lane needs a value"
			lanes+=("$2")
			shift 2 ;;
		--keep) keep=1; shift ;;
		--timeout) timeout_s="${2:-}"; shift 2 || die 2 "--timeout needs a value" ;;
		-h|--help) usage; exit 0 ;;
		*) die 2 "unknown argument $1" ;;
	esac
done

# ---- 1. what may run at all
[ -n "$repo" ] || die 2 "--repo is required. See --help."
[ "${#lanes[@]}" -gt 0 ] || die 2 "name at least one --lane. See --help."
[[ "$timeout_s" =~ ^[1-9][0-9]{0,5}$ ]] || die 2 "--timeout is a whole number of seconds from 1 to 999999"

# ---- 2. docker reaches this machine's own engine alone, its environment and its files read as the guard reads them
for variable in DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG BUILDX_BUILDER BUILDX_CONFIG; do
	[ -z "${!variable:-}" ] || die 2 "$variable is set, which can point docker or buildx elsewhere. The owner unsets it."
done
command -v node >/dev/null 2>&1 || die 2 "node is not on PATH, it reads docker's configuration as the guard does"
# the home is node's os.homedir(), the guard's own, and a file that exists and cannot be read refuses the run
elsewhere="$(node -e '
	const fs = require("fs"), os = require("os"), path = require("path");
	const local = ["default", "desktop-linux"];
	const docker = path.join(os.homedir(), ".docker");
	function read(name) {
		let text;
		try { text = fs.readFileSync(path.join(docker, name), "utf8"); } catch (err) {
			if (err.code === "ENOENT") return null;
			throw new Error(name + " could not be read, " + err.code);
		}
		try { return JSON.parse(text); } catch (err) { throw new Error(name + " could not be read as JSON"); }
	}
	function refuse(words) { console.log(words); process.exit(1); }
	try {
		const config = read("config.json");
		const context = config && config.currentContext;
		if (context && !local.includes(context)) {
			refuse("the current context is " + context + " in " + docker + ", which can be another machine. "
				+ "The owner switches it back.");
		}
		const current = read(path.join("buildx", "current"));
		if (current !== null) {
			if (!current || typeof current !== "object" || Array.isArray(current)) {
				throw new Error("buildx/current could not be read as a builder");
			}
			const name = String(current.Name || ""), key = String(current.Key || "");
			if (name && !local.includes(name)) {
				refuse("the buildx builder is " + name + " in " + docker + ", which is not the local engine itself. "
					+ "The owner switches it back with docker buildx use default.");
			}
			if (key && !local.includes(key)) {
				refuse("the buildx endpoint is " + key + " in " + docker + ", which can be another machine. "
					+ "The owner switches it back.");
			}
		}
	} catch (err) {
		refuse(err.message + ", so where docker leads is unknown. The owner checks " + docker + ".");
	}
' 2>&1)" || die 2 "$elsewhere"

# ---- 3. the commit, exactly
given="$repo"
repo="$(cd "$repo" 2>/dev/null && pwd)" || die 2 "--repo $given is not a folder"
top="$(git -C "$repo" rev-parse --show-toplevel 2>/dev/null)" || die 2 "$given is not a git repository"
if [ -n "$at" ]; then
	commit="$(git -C "$top" rev-parse -q --verify "$at^{commit}" 2>/dev/null)" || die 2 "$given has no commit $at"
else
	changes="$(git -C "$top" status --porcelain --untracked-files=normal 2>&1)" \
		|| die 2 "git could not read the tree of $given, $changes"
	if [ -n "$changes" ]; then
		die 2 "$given has changes or untracked files git does not ignore, $(printf '%s\n' "$changes" | head -3 \
			| tr '\n' ' ')and a run of HEAD would leave them out unseen, so commit them, or pass --at <commit> to" \
			"test a commit as it stands"
	fi
	commit="$(git -C "$top" rev-parse -q --verify "HEAD^{commit}" 2>/dev/null)" || die 2 "$given has no commit yet"
fi
short="${commit:0:12}"

# ---- 4. the lanes, each the session's to run
makefile="$(git -C "$top" show "$commit:Makefile" 2>/dev/null)" || makefile=""
seen=" "
for lane in "${lanes[@]}"; do
	case "$seen" in *" $lane "*) die 2 "--lane $lane is named twice" ;; esac
	seen="$seen$lane "
	if [ "$lane" = actionlint ]; then
		git -C "$top" ls-tree --name-only "$commit" -- .github/workflows/ 2>/dev/null | grep -q -E '\.ya?ml$' \
			|| die 2 "--lane actionlint, but $short has no workflows in .github/workflows"
		continue
	fi
	[[ "$lane" =~ ^ci-[a-z0-9]+(-[a-z0-9]+)*$ ]] \
		|| die 2 "--lane $lane is no lane, which is a ci-* target of the repo's Makefile or actionlint"
	[ "$lane" != ci-version-check ] \
		|| die 2 "ci-version-check compares VERSION against origin/main, a history an archive does not have, so it runs" \
			"on the host"
	! owner_lane "$lane" \
		|| die 2 "--lane $lane names a deploy, a release or DEV or PROD, which is the owner's, as a typed make of it is"
	[ -n "$makefile" ] || die 2 "$given has no Makefile at $short, so $lane is no target"
	printf '%s\n' "$makefile" | grep -q -E "^$lane:([^=]|$)" \
		|| die 2 "$lane is no target on its own line in the Makefile at $short"
done

# ---- 5. no secret enters. A tracked secret file is refused, and a token's shape in tracked content is listed
listed=0 found=""
while IFS= read -r -d '' path; do
	listed=$((listed + 1))
	if [ -z "$found" ] && secret_name "$path"; then found="$path"; fi
done < <(git -C "$top" ls-tree -r -z --name-only "$commit")
[ "$listed" -gt 0 ] || die 3 "git could not list the files of $short"
[ -z "$found" ] || die 2 "$short tracks $found, named like a secret file, which never enters a container, since a" \
	"build's layers outlive the run. The owner moves it out of git"
hits="$(git -C "$top" -c core.quotepath=off grep -I -l -E -e "$token_shapes" "$commit" 2>&1)"
case $? in 0|1) ;; *) die 3 "git grep could not screen $short, $hits" ;; esac

# ---- 6. the run's own folder, id and image, kept or removed by how it ends
mkdir -p "$runs" 2>/dev/null || die 3 "the runs folder $runs could not be made"
runs="$(cd "$runs" && pwd)"
run="" id=""
for _ in 1 2 3 4 5; do
	id="$(date '+%Y%m%d-%H%M%S')-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
	if mkdir "$runs/$id" 2>/dev/null; then run="$runs/$id"; break; fi
done
[ -n "$run" ] || die 3 "no run folder could be made in $runs"
context="$run/context" log="$run/build.log"
lanes_built=0
finish() {
	local code=$?
	trap - EXIT
	# this run's image alone, never a prune, so another run's image or cache is never touched
	if [ "$lanes_built" -eq 1 ]; then "$docker_bin" rmi "kdf-preflight-run:$id" >/dev/null 2>&1; fi
	if [ "$code" -eq 2 ] || { [ "$code" -eq 0 ] && [ "$keep" -eq 0 ]; }; then rm -rf "$run"; fi
	exit "$code"
}
trap finish EXIT
trap 'exit 3' INT TERM HUP

say "testing $(basename "$top") at $commit, lanes ${lanes[*]}, run $id"
while IFS= read -r hit; do
	[ -z "$hit" ] || say "WARNING ${hit#"$commit":} holds a token's shape. It is already in git and enters the" \
		"container with the rest, so it should be a fixture"
done <<< "$hits"

# ---- 7. the context, the commit's tar with LF line ends beside the image's two files, and nothing else
mkdir "$context" || die 3 "the context folder could not be made in $run"
git -C "$top" -c core.autocrlf=false -c core.eol=lf archive --format=tar -o "$context/repo.tar" "$commit" 2>>"$log" \
	|| die 3 "git archive could not export $short, the log is $log"
cp "$here/preflight/Dockerfile" "$here/preflight/lanes.sh" "$context/" 2>>"$log" \
	|| die 3 "the image's files could not be copied from $here/preflight"

# ---- 8. the builds, each under what remains of the timeout
deadline=$(( $(date +%s) + timeout_s ))
remaining() { echo $(( deadline - $(date +%s) )); }
tail_log() {
	printf 'kdf-preflight: the last lines of %s\n' "$log" >&2
	tail -n 40 "$log" | tr -d '\r' >&2
}
incomplete() { tail_log; die 3 "the run could not complete, $*. The run is kept at $run"; }
expired() {
	tail_log
	die 3 "the run passed its timeout of $timeout_s seconds $*, so it could not complete. The run is kept at $run"
}

base_tag="kdf-preflight-base:$(sha256sum "$context/Dockerfile" | cut -c1-16)"
left=$(remaining)
[ "$left" -gt 0 ] || expired "before the base was built"
say "building the base $base_tag, a few minutes the first time on a machine"
timeout --kill-after=10 "$left" "$docker_bin" build --target=base --tag="$base_tag" --progress=plain "$context" \
	>> "$log" 2>&1
status=$?
case "$status" in
	0) ;;
	124|137) expired "while the base was built" ;;
	*) incomplete "the base would not build, docker exited $status" ;;
esac

left=$(remaining)
[ "$left" -gt 0 ] || expired "before the lanes ran"
say "running the lanes, the log is $log"
lanes_built=1
timeout --kill-after=10 "$left" "$docker_bin" build --target=lanes --tag="kdf-preflight-run:$id" \
	--build-arg="RUN_ID=$id" --build-arg="LANE_TIMEOUT=$left" --build-arg="LANES=${lanes[*]}" --progress=plain \
	"$context" >> "$log" 2>&1
status=$?
case "$status" in 124|137) expired "while the lanes ran" ;; esac

# ---- 9. the result, from the marker lines of this run alone, never from the build's status
marks="$(tr -d '\r' < "$log" | grep -E " KDF-PREFLIGHT-(RESULT|END) $id( |$)")"
printf '%s\n' "$marks" | grep -q -E " KDF-PREFLIGHT-END $id$" \
	|| incomplete "no marker line of run $id ended its log, docker exited $status"
results=()
for lane in "${lanes[@]}"; do
	result="$(printf '%s\n' "$marks" | sed -n -E "s/.* KDF-PREFLIGHT-RESULT $id $lane ([0-9]+)$/\1/p")"
	case "$result" in ''|*[!0-9]*) incomplete "run $id printed no single result for $lane" ;; esac
	results+=("$result")
done
failed=0
for index in "${!lanes[@]}"; do
	lane="${lanes[$index]}" result="${results[$index]}"
	if [ "$result" -eq 0 ]; then
		say "$lane passed"
		continue
	fi
	failed=$((failed + 1))
	case "$result" in
		124) say "$lane failed, it ran out of its time inside the container" ;;
		*) say "$lane failed, exit $result" ;;
	esac
done
if [ "$failed" -gt 0 ] && grep -q -E "could not read (Username|Password)|terminal prompts disabled" "$log"; then
	say "a lane could not fetch from a private git URL. No token enters the container, so a lane that needs a" \
		"private package is reported in the pull request as a skipped pre-flight"
fi
if [ "$failed" -gt 0 ]; then
	say "$failed of ${#lanes[@]} lanes failed at $commit. The log is $log, kept with the run"
	exit 1
fi
if [ "$keep" -eq 1 ]; then
	say "every lane passed at $commit. The run is kept at $run"
else
	say "every lane passed at $commit"
fi
exit 0
