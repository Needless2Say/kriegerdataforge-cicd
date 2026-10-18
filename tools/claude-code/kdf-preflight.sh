#!/usr/bin/env bash
# kdf-preflight.sh, a Linux pre-flight of a repo's CI lanes in a container, the one way every session runs one (D-072,
# D-078).
#
#   bash kdf-preflight.sh --repo <root> --lane <lane> [--lane <lane>]... [--at <commit>] [--setup <target>]
#                         [--no-setup] [--github <name>] [--keep] [--timeout <seconds>]
#
# A lane is a ci-* target on its own line in the repo's Makefile at the commit, or actionlint, the image's actionlint
# with ShellCheck over the repo's workflows. A lane holding one of the guard's owner only make words, such as deploy,
# release, publish or prod, or dev without local, is refused as a typed make of it is, and so is ci-version-check,
# which compares VERSION against origin/main, a history an archive does not have. The lanes run in the order given.
#
# Setup runs first (D-078). When a make lane is named and the Makefile at the commit has a setup target on its own
# line, make setup runs in the container before the first lane, as a fresh clone is set up. --setup <target> names
# another, such as install, and --no-setup runs none. A setup target is refused as a lane is, and so is one named as a
# lane too, --setup beside --no-setup, either named twice, and either with no make lane. A red setup runs no make lane,
# each said not run, while actionlint still runs, and the run reads 1.
#
# The owner's private Python packages, by mirrors (D-078). When a make lane is named, the seven files CI's fetch plan
# reads, requirements.txt, requirements.in, requirements-dev.txt, requirements-dev.in, requirements-test.txt,
# requirements-test.in and pyproject.toml, are read at the commit for each pin of
# git+https://github.com/Needless2Say/<repo>.git, as CI's PIN finds one, a comment skipped, and each repo must be on
# CI's allowlist in scripts/fetch_private_packages.py, read beside this tool. The scan is a convenience and not the
# fence, since a pin it does not read fails at once in the container, which asks for no login. Nothing is mirrored
# unless GitHub says the repo under test is private, the repo named by the clone's one origin, or by --github <name>
# for a fresh repo with no origin, and unless GitHub holds the commit's base there, its merge base with origin/main,
# or the commit itself with --github. So a commit from a pull request or a fork gets no private history. gh answers
# both with its own login. A private repo's pins are fetched by this machine's git with its own credential helper,
# prompts off, into bare mirrors of main, every tag and each pinned commit, none of the host's git settings shaping
# them, and every path in each mirror's history is judged by the secret file rule below. The context gains each
# mirror's HEAD, refs and objects and a config of the tool's own, which the image reads through CI's rewrite of the
# repo's https URL, so no token enters.
#
# A lane that fails on git's credential refusal means a pin the scan missed or a ref a mirror lacks, a defect, so the
# run failed and the pull request reports a failed pre-flight. A repo GitHub calls public mirrors nothing, so its lanes
# that need a private package, such as ci-style, run on the host and the pull request says so. A private npm package
# is not served yet, so a lane that fails on one from npm.pkg.github.com is reported as a skipped pre-flight.
#
# The commit is --at, resolved to its full hash, or HEAD on a clean tree. A tree with changes or with untracked files
# git does not ignore is refused with no --at, since the run would leave them out unseen. Every GIT_ variable is dropped
# first, so none points the tool anywhere else. A tracked file named like a secret file, the names kdf-ask-codex.sh
# refuses but an .env example, refuses the run before anything is exported, since a build's layers outlive the run, and
# a token's shape in tracked content is listed as a warning and not refused, since that text is already in git.
#
# A session in the reviewer role is refused first, since the guard refuses its docker build and runs this unread.
# Docker must reach this machine alone. The tool refuses, before it sends anything, while DOCKER_HOST, DOCKER_CONTEXT,
# DOCKER_CONFIG, BUILDX_BUILDER or BUILDX_CONFIG is set, while ~/.docker/config.json names a current context other than
# default or desktop-linux, read as the guard reads it, and while ~/.docker/buildx/current chooses a builder other than
# the engine's own. Every docker option it passes is on the guard's list for build and rmi, and it never runs docker
# run, exec or anything that cleans the daemon as a whole.
#
# The run's folder, <workspace>/temp/kdf-preflight/<run id>/, holds context/, which is the commit's tar from git archive
# with LF line ends beside the image's Dockerfile and lane script and the mirrors folder and nothing else, and
# build.log. The base stage is built first and alone, tagged kdf-preflight-base:<the Dockerfile's hash>, then the lanes
# stage, tagged kdf-preflight-run:<run id> and removed with docker rmi when the run ends, failed or not. The fetches and
# each build run under timeout with what remains of --timeout, 1800 seconds unless given, and setup and each lane under
# its own inside the container. The result is read from the marker lines holding the run id that the image's last step
# prints, that step found by the line BuildKit opens it with and its lines counted only when they open with a marker,
# never from the build's status, every result and setup line checked, and a red setup and each failed lane are shown
# with the excerpt of its own output that step prints after them, which BuildKit clipping a noisy lane cannot take.
#
# Exit 0 when setup passed, where it was due, and every lane passed, 1 when setup or a lane failed, 2 on a refusal
# before anything was built, 3 when the run could not complete, a base that would not build, docker unreachable, the
# run past its timeout, a visibility GitHub could not give, a fetch git could not finish, or marker lines that are not
# one whole and consistent set, with the log's tail. The folder is removed on 0 unless --keep is given and on 2, and
# kept on 1 and 3, and its mirrors are removed however it ends. KDF_DOCKER_BIN names the docker program, KDF_GH_BIN gh,
# KDF_PREFLIGHT_DIR the runs folder and KDF_PREFLIGHT_GIT_BASE where the mirrors are fetched from, each for a test.
set -uo pipefail
export LC_ALL=C
# git finds its repo, its config and its programs through GIT_ variables first, and the tool needs none of them. git
# asks an askpass program before it reads the prompt switch, so none is named here either
while IFS= read -r variable; do unset "$variable"; done < <(compgen -e | grep '^GIT_')
unset SSH_ASKPASS

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workspace="$(cd "$here/../../.." && pwd)"
docker_bin="${KDF_DOCKER_BIN:-docker}"
gh_bin="${KDF_GH_BIN:-gh}"
runs="${KDF_PREFLIGHT_DIR:-$workspace/temp/kdf-preflight}"
git_base="${KDF_PREFLIGHT_GIT_BASE:-https://github.com/Needless2Say}"
fetch_script="$here/../../scripts/fetch_private_packages.py"
# a token's shape, GitHub's, a private key's, AWS's and OpenAI's, the shapes kdf-ask-codex.sh screens for
token_shapes='gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,}|-----BEGIN [A-Z ]*PRIVATE KEY'
token_shapes="$token_shapes|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}"
# the names of secret files, matched in any case, exactly kdf-ask-codex.sh's
secret_globs=('.env*' '*.pem' '*.key' '*.p12' '*.pfx' '*.tfvars' '*.tfstate*' 'id_rsa*' 'id_dsa*' 'id_ecdsa*'
	'id_ed25519*' '.git-credentials' '.netrc')
# CI's PIN in fetch_private_packages.py as an extended regular expression, held to it by a test
pin_pattern="git\\+https://github\\.com/Needless2Say/[A-Za-z0-9._-]+\\.git@[^][:space:]#;,'\"[]+"
# the files CI's fetch plan reads by default, its requirement_files input
pin_files=(requirements.txt requirements.in requirements-dev.txt requirements-dev.in requirements-test.txt
	requirements-test.in pyproject.toml)

die() { local code=$1; shift; printf 'kdf-preflight: %s\n' "$*" >&2; exit "$code"; }
say() { printf 'kdf-preflight: %s\n' "$*"; }
usage() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"; }
# text with the user part of every URL removed, as CI's redact does, since a host's rewrite can hold a token
redact() { sed -E 's#(https?://)[^/[:space:]@]+@#\1***@#g'; }
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
# the name of a repo of the owner's on GitHub that an origin URL names, in its https or ssh form, with or without .git
github_name() {
	local name
	case "$1" in
		https://github.com/Needless2Say/*) name="${1#https://github.com/Needless2Say/}" ;;
		git@github.com:Needless2Say/*) name="${1#git@github.com:Needless2Say/}" ;;
		ssh://git@github.com/Needless2Say/*) name="${1#ssh://git@github.com/Needless2Say/}" ;;
		*) return 1 ;;
	esac
	name="${name%.git}"
	[[ "$name" =~ ^[A-Za-z0-9._-]+$ ]] && [ "$name" != . ] && [ "$name" != .. ] || return 1
	printf '%s\n' "$name"
}
# CI's allowlist, the names in the ALLOWLIST block of its fetch script, one line each or a comment, and nothing else
read_allowlist() {
	local block line names="" entry='^[[:space:]]*"([A-Za-z0-9._-]+)":[[:space:]]*"(private|public)",?[[:space:]]*$'
	block="$(awk '
		/^ALLOWLIST: dict\[str, str\] = \{\r?$/ { inside = 1; next }
		inside && /^\}\r?$/ { found = 1; exit }
		inside { print }
		END { exit !found }' "$fetch_script" 2>/dev/null)" || return 1
	while IFS= read -r line; do
		line="${line%$'\r'}"
		if [[ "$line" =~ $entry ]]; then
			names="$names ${BASH_REMATCH[1]}"
		elif ! [[ "$line" =~ ^[[:space:]]*(#.*)?$ ]]; then
			return 1
		fi
	done <<< "$block"
	[ -n "$names" ] || return 1
	printf '%s \n' "$names"
}

repo="" at="" keep=0 timeout_s=1800 setup_target="" setup_named=0 no_setup=0 github="" github_named=0
lanes=()
while [ $# -gt 0 ]; do
	case "$1" in
		--repo) repo="${2:-}"; shift 2 || die 2 "--repo needs a value" ;;
		--at) at="${2:-}"; shift 2 || die 2 "--at needs a value" ;;
		--lane)
			[ $# -ge 2 ] || die 2 "--lane needs a value"
			lanes+=("$2")
			shift 2 ;;
		--setup)
			[ $# -ge 2 ] || die 2 "--setup needs a value"
			setup_target="$2" setup_named=$((setup_named + 1))
			shift 2 ;;
		--no-setup) no_setup=$((no_setup + 1)); shift ;;
		--github)
			[ $# -ge 2 ] || die 2 "--github needs a value"
			github="$2" github_named=$((github_named + 1))
			shift 2 ;;
		--keep) keep=1; shift ;;
		--timeout) timeout_s="${2:-}"; shift 2 || die 2 "--timeout needs a value" ;;
		-h|--help) usage; exit 0 ;;
		*) die 2 "unknown argument $1" ;;
	esac
done

# ---- 1. what may run at all. A reviewer builds nothing, as the guard refuses its docker build
[ "${KDF_ROLE:-}" != reviewer ] || die 2 "a session in the reviewer role never runs a pre-flight, it reads alone"
[ -n "$repo" ] || die 2 "--repo is required. See --help."
[ "${#lanes[@]}" -gt 0 ] || die 2 "name at least one --lane. See --help."
[[ "$timeout_s" =~ ^[1-9][0-9]{0,5}$ ]] || die 2 "--timeout is a whole number of seconds from 1 to 999999"
[ "$setup_named" -le 1 ] || die 2 "--setup is named twice"
[ "$no_setup" -le 1 ] || die 2 "--no-setup is named twice"
[ "$setup_named" -eq 0 ] || [ "$no_setup" -eq 0 ] || die 2 "--setup and --no-setup cannot both be given"
[ "$github_named" -le 1 ] || die 2 "--github is named twice"
if [ "$github_named" -eq 1 ]; then
	[[ "$github" =~ ^[A-Za-z0-9._-]+$ ]] && [ "$github" != . ] && [ "$github" != .. ] \
		|| die 2 "--github $github is no repo name, which is letters, digits, ., - and _ alone"
fi

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
seen=" " make_lane=0
for lane in "${lanes[@]}"; do
	case "$seen" in *" $lane "*) die 2 "--lane $lane is named twice" ;; esac
	seen="$seen$lane "
	if [ "$lane" = actionlint ]; then
		git -C "$top" ls-tree --name-only "$commit" -- .github/workflows/ 2>/dev/null | grep -q -E '\.ya?ml$' \
			|| die 2 "--lane actionlint, but $short has no workflows in .github/workflows"
		continue
	fi
	make_lane=1
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

# ---- 5. setup, the repo's own by default, refused as a lane is (D-078)
if [ "$make_lane" -eq 0 ]; then
	[ "$setup_named" -eq 0 ] || die 2 "--setup needs a make lane, since actionlint alone runs no setup"
	[ "$no_setup" -eq 0 ] || die 2 "--no-setup needs a make lane, since actionlint alone runs no setup"
fi
setup=""
if [ "$no_setup" -eq 1 ]; then
	setup_said="no setup, --no-setup was given"
elif [ "$setup_named" -eq 1 ]; then
	setup="$setup_target"
	[[ "$setup" =~ ^[a-z0-9_][a-z0-9_-]*$ ]] \
		|| die 2 "--setup $setup is no plain make target, which is lower case letters, digits, - and _ alone"
	[ "$setup" != ci-version-check ] \
		|| die 2 "--setup ci-version-check compares VERSION against origin/main, a history an archive does not have"
	! owner_lane "$setup" \
		|| die 2 "--setup $setup names a deploy, a release or DEV or PROD, which is the owner's, as a typed make of it is"
	case " ${lanes[*]} " in *" $setup "*) die 2 "--setup $setup is named as a lane too" ;; esac
	[ -n "$makefile" ] || die 2 "$given has no Makefile at $short, so $setup is no target"
	printf '%s\n' "$makefile" | grep -q -E "^$setup:([^=]|$)" \
		|| die 2 "$setup is no target on its own line in the Makefile at $short"
elif [ "$make_lane" -eq 0 ]; then
	setup_said="no setup, actionlint alone needs none"
elif printf '%s\n' "$makefile" | grep -q -E '^setup:([^=]|$)'; then
	setup=setup
else
	setup_said="no setup, the Makefile at $short has no setup target"
fi
[ -z "$setup" ] || setup_said="setup first, make $setup, then the lanes"

# ---- 6. no secret enters. A tracked secret file is refused, and a token's shape in tracked content is listed
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

# ---- 7. the owner's private repos the commit pins, and whether any may be mirrored (D-078). The run's one deadline
# starts here, so the questions to GitHub and the fetches count against it as the builds do
deadline=$(( $(date +%s) + timeout_s ))
remaining() { echo $(( deadline - $(date +%s) )); }
pinned=() pin_shas=()
if [ "$make_lane" -eq 1 ]; then
	matches=""
	for file in "${pin_files[@]}"; do
		git -C "$top" cat-file -e "$commit:$file" 2>/dev/null || continue
		text="$(git -C "$top" show "$commit:$file" 2>&1)" || die 3 "git could not read $file at $short, $text"
		# a comment is a # at the start of a line or after whitespace, as pip reads one
		matches="$matches$(printf '%s\n' "$text" | sed -E 's/(^|[[:space:]])#.*$//' | grep -o -E -e "$pin_pattern")"
		matches="$matches"$'\n'
	done
	if [ -n "${matches//[[:space:]]/}" ]; then
		allowlist="$(read_allowlist)" \
			|| die 3 "CI's allowlist could not be read from the ALLOWLIST block of $fetch_script, so the pins of $short" \
				"cannot be checked"
		declare -A named_repos=()
		while IFS= read -r match; do
			[ -n "$match" ] || continue
			rest="${match#git+https://github.com/Needless2Say/}"
			name="${rest%%.git@*}" ref="${rest#*.git@}"
			case "$allowlist" in *" $name "*) ;; *)
				die 2 "$short pins Needless2Say/$name, which is not on CI's allowlist in" \
					"scripts/fetch_private_packages.py, so the run is refused" ;;
			esac
			named_repos[$name]=1
			if [[ "$ref" =~ ^[0-9a-f]{40}$ ]]; then pin_shas+=("$name $ref"); fi
		done <<< "$matches"
		mapfile -t pinned < <(printf '%s\n' "${!named_repos[@]}" | sort)
	fi
fi

# the repo under test, named by the clone's one origin, which no commit carries, or by --github for a fresh repo
origins="$(git -C "$top" config --local --get-all remote.origin.url 2>/dev/null)"
origin_count=0
[ -z "$origins" ] || origin_count=$(( $(printf '%s\n' "$origins" | wc -l) ))
named=""
if [ "$github_named" -eq 1 ]; then
	[ "$origin_count" -eq 0 ] \
		|| die 2 "--github names the repo of a fresh repo with no origin, and $given has an origin, which names it"
	named="$github"
elif [ "$origin_count" -eq 1 ]; then
	named="$(github_name "$origins")" || named=""
fi
# whether GitHub calls the named repo private, true or false, else why that is unknown
ask_private() {
	local left answer status errors
	command -v "$gh_bin" >/dev/null 2>&1 \
		|| { printf 'gh is not on the PATH, so whether %s is private on GitHub is unknown' "$1"; return 1; }
	left=$(remaining)
	[ "$left" -gt 0 ] || { printf 'the run passed its timeout before GitHub was asked about %s' "$1"; return 1; }
	errors="$(mktemp)"
	answer="$(timeout --kill-after=5 "$left" "$gh_bin" api "repos/Needless2Say/$1" --jq .private 2>"$errors" \
		| tr -d '\r')"
	status=$?
	if [ "$status" -ne 0 ]; then
		printf 'gh could not say whether Needless2Say/%s is private, %s. When gh is signed out, the owner signs it in' \
			"$1" "$(tr -d '\r' < "$errors" | tail -n 1 | redact)"
		printf ' with gh auth login'
		rm -f "$errors"
		return 1
	fi
	rm -f "$errors"
	case "$answer" in
		true|false) printf '%s' "$answer" ;;
		*) printf 'gh answered %s for whether Needless2Say/%s is private, neither true nor false' "$answer" "$1"
			return 1 ;;
	esac
}
visibility="" visibility_said="" mirror=0
if [ "${#pinned[@]}" -gt 0 ]; then
	unknown="so whether it is private on GitHub is unknown, and its pins are not mirrored"
	[ "$origin_count" -le 1 ] || die 2 "$given has $origin_count origin URLs, which name no one GitHub repo, $unknown"
	if [ -z "$named" ] && [ "$origin_count" -eq 1 ]; then
		die 2 "$given's origin, $(printf '%s' "$origins" | redact), is not a repo of github.com/Needless2Say, $unknown"
	fi
	[ -n "$named" ] || die 2 "$given has no origin, $unknown. A fresh repo names its repo with --github <name>"
	visibility="$(ask_private "$named")" || die 3 "$visibility"
	if [ "$visibility" = true ]; then
		# a commit fetched from anywhere into a private repo's clone keeps the clone's origin, so it must be built on
		# that repo's own history, a base GitHub confirms is the repo's
		if [ "$github_named" -eq 1 ]; then
			base="$commit"
		else
			git -C "$top" rev-parse -q --verify "refs/remotes/origin/main^{commit}" >/dev/null 2>&1 \
				|| die 2 "$given has no origin/main, so no base of $short can be confirmed on GitHub, and nothing" \
					"private is mirrored. Fetch origin, then run again"
			base="$(git -C "$top" merge-base "$commit" refs/remotes/origin/main 2>/dev/null)" \
				|| die 2 "$short shares no history with origin/main, so it is built on no base GitHub confirms in" \
					"$named, and nothing private is mirrored"
		fi
		left=$(remaining)
		confirmed=""
		if [ "$left" -gt 0 ]; then
			confirmed="$(timeout --kill-after=5 "$left" "$gh_bin" api "repos/Needless2Say/$named/commits/$base" \
				--jq .sha 2>/dev/null | tr -d '\r')"
		fi
		[ "$confirmed" = "$base" ] \
			|| die 2 "GitHub does not hold $base in Needless2Say/$named, so $short is built on no base GitHub confirms" \
				"there, and nothing private is mirrored"
		mirror=1
	fi
elif [ -n "$named" ]; then
	# nothing to mirror, so the answer only says what the repo is, and one GitHub cannot give changes nothing else
	visibility="$(ask_private "$named")" || {
		visibility_said="whether $named is private on GitHub could not be read, which changes nothing else, since"
		visibility_said="$visibility_said nothing is mirrored. $visibility"
		visibility=""
	}
fi

# ---- 8. the run's own folder, id and image, kept or removed by how it ends, and its mirrors removed however it ends
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
	# no mirror's history is kept past the run, a red one included, which keeps its log and tar
	rm -rf "$run/mirrors" "$context/mirrors" "$run/template" "$run/hooks" "$run/paths" "$run/fetch.err"
	# this run's image alone, never a prune, so another run's image or cache is never touched, bounded so a stalled
	# daemon never holds the run, and said when it fails, the result unchanged since the lanes' result stands
	local left_behind=""
	if [ "$lanes_built" -eq 1 ] && ! timeout --kill-after=5 60 "$docker_bin" rmi "kdf-preflight-run:$id" >/dev/null 2>&1
	then
		# a build that never tagged its image leaves nothing to remove, and an answer that cannot be had is a warning
		left_behind="$(timeout --kill-after=5 30 "$docker_bin" images -q "kdf-preflight-run:$id" 2>/dev/null)" \
			|| left_behind="unknown"
	fi
	if [ -n "$left_behind" ]; then
		printf 'kdf-preflight: WARNING the image kdf-preflight-run:%s may be left behind, docker rmi it by hand\n' \
			"$id" >&2
	fi
	if [ "$code" -eq 2 ] || { [ "$code" -eq 0 ] && [ "$keep" -eq 0 ]; }; then rm -rf "$run"; fi
	exit "$code"
}
trap finish EXIT
trap 'exit 3' INT TERM HUP

say "testing $(basename "$top") at $commit, lanes ${lanes[*]}, run $id"
say "$setup_said"
case "$visibility:$mirror" in
	true:1) say "$named is private on GitHub, so its pins are mirrored" ;;
	true:0) say "$named is private on GitHub, and the scan found no pin of the owner's to mirror" ;;
	false:*) say "$named is public on GitHub, so nothing private is mirrored" ;;
esac
[ -z "$visibility_said" ] || say "$visibility_said"
while IFS= read -r hit; do
	[ -z "$hit" ] || say "WARNING ${hit#"$commit":} holds a token's shape. It is already in git and enters the" \
		"container with the rest, so it should be a fixture"
done <<< "$hits"

# ---- 9. the context, the commit's tar with LF line ends beside the image's two files and the mirrors, and nothing else
tail_log() {
	printf 'kdf-preflight: the last lines of %s\n' "$log" >&2
	tail -n 40 "$log" | tr -d '\r' >&2
}
incomplete() { tail_log; die 3 "the run could not complete, $*. The run is kept at $run"; }
expired() {
	tail_log
	die 3 "the run passed its timeout of $timeout_s seconds $*, so it could not complete. The run is kept at $run"
}
mkdir "$context" "$context/mirrors" || die 3 "the context folder could not be made in $run"
git -C "$top" -c core.autocrlf=false -c core.eol=lf archive --format=tar -o "$context/repo.tar" "$commit" 2>>"$log" \
	|| die 3 "git archive could not export $short, the log is $log"
cp "$here/preflight/Dockerfile" "$here/preflight/lanes.sh" "$context/" 2>>"$log" \
	|| die 3 "the image's files could not be copied from $here/preflight"

# ---- 10. the mirrors, fetched by this machine's git with its own login and prompts off, and shaped by none of its
# settings, an empty template and hooks folder of the run's own, the formats written out, and automatic maintenance
# off as in CI (D-045). Each fetch's URL is pinned to itself, which beats any shorter rewrite since git takes the
# longest, and its TLS check to on, the most specific URL a setting can name, and both are read back from git before it
# runs, since a rewrite of the whole URL ties the pin and git keeps the first it read
mirrored=()
if [ "$mirror" -eq 1 ]; then
	mkdir "$run/template" "$run/hooks" "$run/mirrors" || die 3 "the mirrors' folders could not be made in $run"
	isolated=(-c "core.hooksPath=$run/hooks" -c gc.auto=0 -c gc.autoDetach=false -c maintenance.auto=false
		-c maintenance.autoDetach=false -c core.askPass=)
	mirror_git() {
		local left
		left=$(remaining)
		[ "$left" -gt 0 ] || return 124
		timeout --kill-after=10 "$left" env GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never git "${isolated[@]}" "$@"
	}
	fetch_failed() {
		local status=$1 what=$2
		redact < "$run/fetch.err" >> "$log"
		case "$status" in 124|137) expired "while $what was fetched" ;; esac
		die 3 "the fetch of $what failed, $(redact < "$run/fetch.err" | tr -d '\r' | grep -v '^$' | head -n 2 \
			| tr '\n' ' ')When a login was missing, the owner signs git in to GitHub once, then runs again. The run" \
			"is kept at $run"
	}
	for name in "${pinned[@]}"; do
		url="$git_base/$name.git" bare="$run/mirrors/$name.git"
		pinning=(-c "url.$url.insteadOf=$url" -c "http.$url.sslVerify=true")
		mirror_git -c init.defaultRefFormat=files init -q --bare -b main --object-format=sha1 \
			--template="$run/template" "$bare" >/dev/null 2>"$run/fetch.err" || fetch_failed $? "$name"
		effective="$(mirror_git --git-dir="$bare" "${pinning[@]}" ls-remote --get-url "$url" 2>/dev/null | tr -d '\r')"
		[ "$effective" = "$url" ] \
			|| die 2 "the fetch of $name would go to $(printf '%s' "$effective" | redact), not $url, since this" \
				"machine's git rewrites that URL. The owner checks git's url.*.insteadOf settings"
		tls="$(mirror_git --git-dir="$bare" "${pinning[@]}" config --type=bool --get-urlmatch http.sslVerify "$url" \
			2>/dev/null | tr -d '\r')"
		[ "$tls" = true ] \
			|| die 2 "the fetch of $name would not check TLS, since git reads http.sslVerify as" \
				"$(printf '%s' "$tls" | redact) for $url. The owner checks git's http.*.sslVerify settings"
		mirror_git --git-dir="$bare" "${pinning[@]}" fetch -q --no-tags --no-auto-maintenance "$url" \
			'+refs/heads/main:refs/heads/main' '+refs/tags/*:refs/tags/*' 2>"$run/fetch.err" \
			|| fetch_failed $? "$name"
		# each pinned commit the mirror lacks, under a ref of its own, as CI's fetch script does, so the screen walks it
		# and pip's clone checks it out
		for entry in "${pin_shas[@]}"; do
			[ "${entry%% *}" = "$name" ] || continue
			sha="${entry#* }"
			git --git-dir="$bare" cat-file -e "$sha^{commit}" 2>/dev/null && continue
			mirror_git --git-dir="$bare" "${pinning[@]}" fetch -q --no-tags --no-auto-maintenance "$url" \
				"$sha:refs/heads/kdf-pin-${sha:0:12}" 2>"$run/fetch.err" || fetch_failed $? "$name at $sha"
		done
		[ ! -e "$bare/reftable" ] \
			|| die 2 "the mirror of $name keeps its refs in a reftable folder, which the image would not read, so this" \
				"machine's git settings shaped it. The owner checks git's init settings"
		# every path any commit of the mirror adds, changes or removes, so a secret file renamed or only in a root or a
		# pinned commit is named too, judged as a tracked file is, since the whole history enters the image
		git --git-dir="$bare" -c log.showSignature=false -c log.diffMerges=separate log --all --root --no-renames \
			--name-only --format= -m -z --no-color > "$run/paths" 2>>"$log" \
			|| die 2 "git could not list every path of $name's history, so its mirror cannot be screened and the run" \
				"is refused"
		while IFS= read -r -d '' path; do
			[ -n "$path" ] || continue
			! secret_name "$path" \
				|| die 2 "$name's history holds $path, named like a secret file, which never enters a container, since" \
					"a build's layers outlive the run. The owner decides"
		done < "$run/paths"
		# the mirror's parts alone, and a config of the tool's own, so no FETCH_HEAD, no setting git wrote on this
		# machine and no template or hook file enters
		copy="$context/mirrors/$name.git"
		{ mkdir "$copy" && cp "$bare/HEAD" "$copy/HEAD" && cp -r "$bare/refs" "$copy/refs" \
			&& cp -r "$bare/objects" "$copy/objects" \
			&& { [ ! -f "$bare/packed-refs" ] || cp "$bare/packed-refs" "$copy/packed-refs"; } \
			&& printf '[core]\n\trepositoryformatversion = 0\n\tbare = true\n' > "$copy/config"; } 2>>"$log" \
			|| die 3 "the mirror of $name could not be copied into the context, the log is $log"
		mirrored+=("$name")
		say "mirroring $name, main at $(git --git-dir="$bare" rev-parse -q --verify refs/heads/main)"
	done
fi
# the context read back whole, each entry one of its parts, before anything is built
config_text="$(printf '[core]\n\trepositoryformatversion = 0\n\tbare = true')"
read_back=0
while IFS= read -r -d '' entry; do
	read_back=$((read_back + 1))
	part="${entry#"$context"/}"
	case "$part" in
		Dockerfile|lanes.sh|repo.tar|mirrors) continue ;;
		mirrors/*) ;;
		*) die 3 "the context holds $part, which is none of its parts, so nothing is built" ;;
	esac
	inside="${part#mirrors/}"
	name="${inside%%/*}"
	case " ${mirrored[*]} " in *" ${name%.git} "*) ;; *)
		die 3 "the context holds $part, which is no mirror this run made, so nothing is built" ;;
	esac
	[ "$name" != "$inside" ] || continue
	case "${inside#*/}" in
		HEAD|config|packed-refs|refs|refs/*|objects|objects/*) ;;
		*) die 3 "the context holds $part, which is no part of a mirror the image reads, so nothing is built" ;;
	esac
done < <(find "$context" -mindepth 1 -print0)
[ "$read_back" -ge 4 ] || die 3 "the context of run $id could not be read back"
for name in "${mirrored[@]}"; do
	[ "$(cat "$context/mirrors/$name.git/config" 2>/dev/null)" = "$config_text" ] \
		|| die 3 "the mirror of $name holds a config other than the tool's own, so nothing is built"
done

# ---- 11. the builds, each under what remains of the timeout
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
	--build-arg="RUN_ID=$id" --build-arg="LANE_TIMEOUT=$left" --build-arg="LANES=${lanes[*]}" \
	--build-arg="SETUP=$setup" --progress=plain "$context" >> "$log" 2>&1
status=$?
case "$status" in 124|137) expired "while the lanes ran" ;; esac

# ---- 12. the result, from the marker lines of this run alone, never from the build's status. BuildKit opens each
# step's output with a line of its own, "#<n> [lanes i/j] RUN <the step>", which no lane can print, since every line a
# step prints follows "#<n> <seconds> ". The marker step is found by that line, its run id written out or as the
# Dockerfile names it, and only lines of that step that open with a marker count, so neither a lane's output nor an
# excerpt can pass for a result. Every result and setup line is read and must add up, one result for each lane named
# and none other, one setup line naming the target when setup was due and none when not, skipped for a make lane after
# a red setup alone, so a lane that never ran never reads as passed (D-078)
plain="$(tr -d '\r' < "$log")"
step="$(printf '%s\n' "$plain" \
	| sed -n -E "s/^#([0-9]+) \[[^]]*\] RUN .*KDF-PREFLIGHT-END ($id|\\\$RUN_ID)\".*/\1/p" | tail -n 1)"
[ -n "$step" ] || incomplete "the step that prints run $id's results is not in its log, docker exited $status"
marks="$(printf '%s\n' "$plain" | grep -E "^#$step [0-9.]+ KDF-PREFLIGHT-(RESULT|SETUP|END|TAIL|SETUP-TAIL) $id( |$)")"
printf '%s\n' "$marks" | grep -q -E "^#$step [0-9.]+ KDF-PREFLIGHT-END $id$" \
	|| incomplete "no marker line of run $id ended its log, docker exited $status"
declare -A results=()
setup_lines=0 setup_status=""
record='^([a-z0-9_-]+) ([0-9]+|skipped)$' setup_record='^([a-z0-9_-]+) ([0-9]+)$'
while IFS= read -r line; do
	body="${line#"#$step "}"
	body="${body#* }"
	case "$body" in
		"KDF-PREFLIGHT-RESULT $id "*)
			rest="${body#"KDF-PREFLIGHT-RESULT $id "}"
			[[ "$rest" =~ $record ]] || incomplete "run $id printed a malformed result, $rest"
			lane="${BASH_REMATCH[1]}" result="${BASH_REMATCH[2]}"
			case " ${lanes[*]} " in *" $lane "*) ;; *) incomplete "run $id printed a result for $lane, a lane not named" ;;
			esac
			[ -z "${results[$lane]+set}" ] || incomplete "run $id printed two results for $lane"
			results[$lane]="$result" ;;
		"KDF-PREFLIGHT-SETUP $id "*)
			rest="${body#"KDF-PREFLIGHT-SETUP $id "}"
			[[ "$rest" =~ $setup_record ]] || incomplete "run $id printed a malformed setup line, $rest"
			[ -n "$setup" ] || incomplete "run $id printed a setup line where none was due"
			[ "${BASH_REMATCH[1]}" = "$setup" ] \
				|| incomplete "run $id's setup line names ${BASH_REMATCH[1]}, not $setup"
			setup_lines=$((setup_lines + 1)) setup_status="${BASH_REMATCH[2]}" ;;
	esac
done <<< "$marks"
for lane in "${lanes[@]}"; do
	[ -n "${results[$lane]+set}" ] || incomplete "run $id printed no single result for $lane"
done
setup_red=0
if [ -n "$setup" ]; then
	[ "$setup_lines" -eq 1 ] || incomplete "run $id printed no single setup line for $setup"
	[ "$setup_status" -eq 0 ] || setup_red=1
fi
for lane in "${lanes[@]}"; do
	if [ "${results[$lane]}" = skipped ]; then
		[ "$lane" != actionlint ] || incomplete "run $id recorded actionlint skipped, which runs whatever setup did"
		[ -n "$setup" ] || incomplete "run $id recorded $lane skipped where no setup ran"
		[ "$setup_red" -eq 1 ] || incomplete "run $id recorded $lane skipped after a green setup"
	elif [ "$setup_red" -eq 1 ] && [ "$lane" != actionlint ]; then
		incomplete "run $id printed a result for $lane after a red setup, where no make lane runs"
	fi
done

if [ -n "$setup" ] && [ "$setup_red" -eq 0 ]; then
	say "setup passed"
elif [ -n "$setup" ]; then
	case "$setup_status" in
		124) say "setup failed, it ran out of its time inside the container" ;;
		*) say "setup failed, exit $setup_status" ;;
	esac
	excerpt="$(printf '%s\n' "$marks" | sed -n -E "s/^#$step [0-9.]+ KDF-PREFLIGHT-SETUP-TAIL $id //p")"
	if [ -n "$excerpt" ]; then
		say "the last lines of setup, an excerpt of its own output"
		printf '%s\n' "$excerpt" | sed 's/^/    /'
	fi
fi
failed=0
for lane in "${lanes[@]}"; do
	result="${results[$lane]}"
	if [ "$result" = skipped ]; then
		say "$lane not run, setup failed"
		continue
	fi
	if [ "$result" -eq 0 ]; then
		say "$lane passed"
		continue
	fi
	failed=$((failed + 1))
	case "$result" in
		124) say "$lane failed, it ran out of its time inside the container" ;;
		*) say "$lane failed, exit $result" ;;
	esac
	# the excerpt the last step printed of this lane's own output, this run's lines alone, which a clip of the lanes
	# step cannot take
	excerpt="$(printf '%s\n' "$marks" | sed -n -E "s/^#$step [0-9.]+ KDF-PREFLIGHT-TAIL $id $lane //p")"
	if [ -n "$excerpt" ]; then
		say "the last lines of $lane, an excerpt of its own output"
		printf '%s\n' "$excerpt" | sed 's/^/    /'
	fi
done
# the hints. git's credential failure is a defect where the repo is private or unnamed, and the host's lane where it
# is public, and a private npm package is a skipped pre-flight until one is served (D-078)
if [ "$failed" -gt 0 ] || [ "$setup_red" -eq 1 ]; then
	if grep -q -E "could not read (Username|Password)|terminal prompts disabled" "$log"; then
		if [ "$visibility" = false ]; then
			say "$named is public on GitHub, so nothing private was mirrored, and a lane that needs a private package," \
				"such as ci-style, runs on the host, which the pull request reports so"
		else
			printf -v list '%s, ' "${mirrored[@]}"
			list="${list%, }"
			say "a lane or setup could not fetch from a private git URL, and the run mirrored ${list:-nothing}. A pin" \
				"the scan does not read, in a file or a spelling it misses, or at a commit its mirror lacks, is a" \
				"defect to find, so the run failed and the pull request reports a failed pre-flight"
		fi
	fi
	if grep -E 'npm\.pkg\.github\.com' "$log" | grep -q -E '(^|[^0-9.])(401|403)([^0-9.]|$)'; then
		say "a private npm package could not be fetched from npm.pkg.github.com. Private npm packages are not served" \
			"yet, so the pull request reports a skipped pre-flight"
	fi
fi
if [ "$setup_red" -eq 1 ]; then
	say "setup failed at $commit, so no make lane ran. The log is $log, kept with the run"
	exit 1
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
