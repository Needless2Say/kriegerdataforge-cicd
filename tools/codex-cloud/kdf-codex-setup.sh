#!/usr/bin/env bash
# kdf-codex-setup.sh, the setup script of a Codex cloud environment that reviews a KDF Python repo. On trial for the
# kdf-sdk's S2, the KDF Code Review Process section 11, cicd ADR D-039.
#
# The owner pastes this file whole into the environment's setup script field. Codex runs it at the repo's root before
# the agent starts, hands it the environment's secrets, and removes them before the agent phase. It installs the repo's
# development environment with the repo's own `make setup`, handing the private packages' token to that one command
# alone, and then proves the token is in no file the install could have written.
#
# The secret. KDF_CODEX_PACKAGES_TOKEN, a fine grained token made for this environment alone, Contents read only on
# only the private repos this repo installs, for 30 days. Never GH_PACKAGES_PAT, the owner's own token. The repo's
# Makefile reads GH_PACKAGES_PAT and hands it to git through GIT_CONFIG_COUNT pairs in the environment of the install,
# so no git config, requirements file or pip record holds it. Git reads no global or system config during the install,
# so a credential helper the image sets up cannot store the token either.
#
# The proof. After the install, grep -F searches the home folder, the repo with its environment, the temp folder and
# pip's cache for the token's value, in every file's text and every path's name, the value read from a pipe so it is
# never on a command line. A hit fails the setup, so no agent starts on a machine that holds the token, and prints
# only the paths, the value masked even in a path. What the install prints is masked the same way, since Codex shows
# the setup's output.
#
# Exit codes. 0 installed, and the token is on no disk it searched. 1 no secret, no python3.14, make or git, or the
# install failed. 3 the token was found on disk.
set -uo pipefail

say() { printf 'kdf-codex-setup: %s\n' "$*" >&2; }

token="${KDF_CODEX_PACKAGES_TOKEN:-}"
unset KDF_CODEX_PACKAGES_TOKEN
if [ -z "$token" ]; then
	say "the environment has no KDF_CODEX_PACKAGES_TOKEN secret. The process's section 11 says how to make it"
	exit 1
fi
for tool in python3.14 make git; do
	if ! command -v "$tool" >/dev/null 2>&1; then
		say "no $tool on PATH. Set the environment's Python to 3.14, the repos' only version, and keep make and git"
		exit 1
	fi
done

repo="$(pwd)"
cache="${PIP_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/pip}"

# mask, what the install prints with the token's value replaced, the value read from the environment and not an argument
mask() {
	KDF_MASK="$token" awk '
		BEGIN { secret = ENVIRON["KDF_MASK"]; n = length(secret) }
		{
			line = $0
			out = ""
			while (n > 0 && (i = index(line, secret)) > 0) {
				out = out substr(line, 1, i - 1) "<the token>"
				line = substr(line, i + n)
			}
			print out line
		}'
}

# The install. The token reaches the environment of make and its children alone, git reads neither the image's global
# nor its system config, pip keeps no cache, and nothing asks for a password
say "installing with make setup in $repo"
GH_PACKAGES_PAT="$token" GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0 PIP_NO_CACHE_DIR=1 \
	make setup 2>&1 | mask
rc=${PIPESTATUS[0]}
if [ "$rc" -ne 0 ]; then
	say "make setup failed, exit $rc. Nothing was searched, and the agent should not start"
	exit 1
fi

# The proof. Every place the install could write, searched for the value in each file's text and in each path's name
declare -A seen=()
hits=()
for place in "$HOME" "$repo" "${TMPDIR:-/tmp}" "$cache"; do
	[ -e "$place" ] || continue
	while IFS= read -r -d '' hit; do
		[ -n "${seen[$hit]:-}" ] && continue
		seen[$hit]=1
		hits+=("$hit")
	done < <(
		grep -rlsZF -f <(printf '%s\n' "$token") -- "$place"
		find "$place" -print0 2>/dev/null | grep -zF -f <(printf '%s\n' "$token")
	)
done
if [ "${#hits[@]}" -gt 0 ]; then
	say "the token is on disk after the install, in ${#hits[@]} file(s). Delete them and revoke the token"
	for hit in "${hits[@]}"; do
		printf '  %s\n' "${hit//"$token"/<the token>}" >&2
	done
	unset token
	exit 3
fi
unset token
say "installed, and the token is in no file under the home folder, the repo, the temp folder or pip's cache"
exit 0
