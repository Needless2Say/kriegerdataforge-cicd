#!/usr/bin/env bash
# kdf-scan-install.sh, the owner's install of the local code scan into D:/KriegerDataForge-scan (D-085, design 5.3).
#
#   "/c/Program Files/Git/usr/bin/bash.exe" -p /d/KriegerDataForge-scan/install/<commit>/kdf-scan-install.sh <commit>
#
# Run by the owner alone, in the install account's elevated Git Bash, from the protected folder the owner fetched it
# into at cicd's <commit>, read first from an ordinary window. Every hand step before it is typed, never pasted. It
# installs the tools, the Python, Semgrep's rules and the bundle that cicd's commit pins, and only then names the
# bundle in current.
#
# Before anything it refuses unless bash runs in its privileged mode, so no BASH_ENV, function or option from the
# environment reached it, unless the token names the install account kdf-install, unless cygpath says / is
# C:\Program Files\Git, when UAC's values leave the folder's fence open, EnableLUA 0, ConsentPromptBehaviorAdmin 0, or
# PromptOnSecureDesktop 0 while the prompt would not use the secure desktop, as the launcher reads them, and while a
# shell startup file sits in the account's own profile, its USERPROFILE. It checks the folder before it writes, that it
# is there, holds no link, junction or other special file, holds only the names an install writes, and that every item
# grants Administrators and SYSTEM full control and Users read and run and nothing more, the folder itself refusing
# inheritance, read with icacls /save. Then it runs itself again under env -i with a fixed list of variables and
# bash -p, from a staging folder of its own, its HOME and USERPROFILE that folder's, and checks that nothing else
# reached it.
#
# Every program runs by full path, git, curl, tar, sha256sum and cygpath from Git for Windows and the coreutils of its
# usr/bin, icacls, reg and whoami from System32. git reads no configuration file but the repo's own and curl none,
# -q first, each fetch on https alone. gh, uv and the user's Python never run. One lock, a folder under staging/ made
# by mkdir, serialises installs, so a second refuses while the first runs and takes over a lock its dead holder left.
#
# It fetches cicd's main into a bare repo and refuses the commit unless it is an ancestor of that main, and unless
# this script's bytes are the commit's own, before it reads or runs anything of the commit. The bundle is written from
# the commit's blobs, kdf_scan.py, its launcher, kdf_zizmor.yml, ci_paths.py and scan_rules/, with its manifest. The
# Python's four pins are read from kdf_scan.py's blob by a strict pattern, a pin defined twice or malformed refused, its
# archive fetched on every run and checked against its SHA-256, listed, unpacked by tar by a relative name into staging
# and given a manifest from the listing, and that staged Python alone run, only with -I -S -B. Git's bash reads every
# file as owned by the user who runs it, so before the install changes any owner, the launcher's own reader from the
# commit's blobs reads every owner and grant under the folder under that Python, the owner set first only on the
# staging folder this run wrote, and a wrong one refuses the install with its evidence intact. Then --pins, whose every
# pin must match. The folder's own Python never runs, and is kept only when its manifest is the archive's. cosign is
# fetched by its pinned
# address and SHA-256 into staging and run from there, to verify Opengrep's asset, checked against its SHA-256, with
# its .cert and .sig, the certificate's identity exactly OPENGREP_IDENTITY and its issuer OPENGREP_ISSUER. zizmor.exe
# is taken out of its pinned wheel with that Python's zipfile and checked against its SHA-256. Semgrep's rules are
# fetched at their pinned commit into a bare clone, their digest checked by the bundle's kdf_scan.py, and the rules'
# licence page saved with its date, a page that cannot be saved refusing the install.
#
# A part already in place is kept when it checks whole against its pin or manifest and never changed. A damaged one
# refuses the install, or on a first install, one with no current, is removed and installed again, so a run cut short
# is run again and reuses what it left checked. Each new part is staged and moved into place only when every check
# passes. Then the owner is set to Administrators on everything this run wrote and nothing else, the permission read
# back with icacls and with the launcher's own reader, which reads each owner too, the Python and the bundle held to
# their manifests, and only then
# kdf-scan.py and current are replaced, each by a new file in the same folder renamed over it, tried again while a
# scan holds it open. Exit 0 installed, 2 refused before anything moved into place, 3 failed after a part moved, the
# old current kept. The last line tells the owner to close the elevated window and start no session from it.
#
# For a test, --programs <folder> names the stand ins, each program by its name in that folder, git.native naming a
# git Python can run, and aclcheck the launcher's reader. --root and --cicd, allowed only beside it, name a folder and
# a cicd remote of the test's own, and a fetch may then read file:// too. --programs is refused when the token is
# elevated and named on the first and the last line, so no test run passes for an install.
set -uo pipefail
export LC_ALL=C

CR=$'\r'
NL=$'\n'
TAB=$'\t'
BOM=$'\xef\xbb\xbf'
ROOT_DEFAULT="D:/KriegerDataForge-scan"
CICD_DEFAULT="https://github.com/Needless2Say/kriegerdataforge-cicd"
ACCOUNT="kdf-install"
GIT_ROOT_WINDOWS='C:\Program Files\Git'
UAC_KEY='HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
CA_BUNDLE="C:/Program Files/Git/mingw64/etc/ssl/certs/ca-bundle.crt"
ADMINISTRATORS="*S-1-5-32-544"
INSTALL_PATH="tools/claude-code/kdf-scan-install.sh"
# whoami where only an administrator can write, which the test mode's own check reads whatever --programs names
real_whoami="C:/Windows/System32/whoami.exe"
# the files a shell or its terminal reads at start in a profile
STARTUP_FILES=(.bashrc .bash_profile .bash_login .profile .bash_logout .inputrc .minttyrc)
# the names an install writes at the folder's top
TOP_NAMES=" install staging opengrep zizmor python rules bundles kdf-scan.py current "
# the bundle's files under cicd's scripts/common, and the four every bundle holds
BUNDLE_SOURCES=(kdf_scan.py kdf_scan_launcher.py kdf_zizmor.yml ci_paths.py scan_rules)
BUNDLE_FILES=(kdf_scan.py kdf_scan_launcher.py kdf_zizmor.yml ci_paths.py)
# every pin --pins prints
PIN_NAMES=(OPENGREP_VERSION OPENGREP_ASSET OPENGREP_SHA256 OPENGREP_IDENTITY OPENGREP_ISSUER OPENGREP_URL ZIZMOR_VERSION
	ZIZMOR_WHEEL_URL ZIZMOR_WHEEL_SHA256 ZIZMOR_SHA256 COSIGN_VERSION COSIGN_URL COSIGN_SHA256 RULES_REPO RULES_COMMIT
	RULES_DIGEST RULES_LICENSE_URL PYTHON_VERSION PYTHON_BUILD PYTHON_ARCHIVE_BASE PYTHON_ARCHIVE_URL
	PYTHON_ARCHIVE_SHA256)
# the variables the clean room holds, those Git's runtime adds and those bash sets itself
CLEAN_NAMES=" PATH HOME USERPROFILE TEMP TMP TMPDIR SYSTEMROOT WINDIR MSYSTEM LC_ALL TUF_ROOT PWD OLDPWD SHLVL _ "
# the launcher's own reader of every owner and grant under the folder, run by the installed Python
ACL_CODE='import importlib.util, sys
from pathlib import Path
spec     = importlib.util.spec_from_file_location("kdf_scan_launcher_install", sys.argv[1])
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
problems = launcher.acl_problems(Path(sys.argv[2]))
for problem in problems:
    print(problem)
sys.exit(1 if problems else 0)'

commit="" programs="" root="$ROOT_DEFAULT" cicd="$CICD_DEFAULT" inner="" root_given="" cicd_given=""
run="" run_owned=0 lock="" lock_held=0 first=0 py="" self=""
declare -A program=()
declare -A pin=()
moves=()

say() { printf 'kdf-scan-install  %s\n' "$*"; }
refuse() { say "refused, $*"; exit 2; }
fail() {
	say "FAILED, $*"
	say "current still names what it named before, and each part already moved is checked again by the next run"
	exit 3
}
usage() { /usr/bin/awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"; }

# ======================================================================================================================
# The last line, the lock released and the staging folder removed however the run ends
# ======================================================================================================================

finish() {
	local status=$? shown="${commit:0:12}" prefix=""
	if [ "$run_owned" = 1 ] && [ -n "$run" ]; then
		cd / 2>/dev/null
		/usr/bin/rm -rf "$run"
	fi
	if [ "$lock_held" = 1 ]; then
		/usr/bin/rm -rf "$lock"
	fi
	[ -n "$shown" ] || shown="-"
	[ -z "$programs" ] || prefix="TEST RUN with stand ins from $programs, never an install, "
	if [ "$status" -eq 0 ]; then
		say "${prefix}cicd $shown installed and current, close this elevated window now and start no session from it"
	else
		say "${prefix}cicd $shown NOT installed (exit $status), close this elevated window now and start no session from it"
	fi
}

# ======================================================================================================================
# The arguments and the programs
# ======================================================================================================================

parse_args() {
	if [ "${1:-}" = --inner ]; then
		[ $# -ge 2 ] || refuse "--inner needs its staging folder"
		inner="$2"
		shift 2
	fi
	while [ $# -gt 0 ]; do
		case "$1" in
			--programs|--root|--cicd)
				[ $# -ge 2 ] && [ -n "$2" ] || refuse "$1 needs a value"
				case "$1" in
					--programs) programs="$2" ;;
					--root) root_given="$2" ;;
					--cicd) cicd_given="$2" ;;
				esac
				shift 2 ;;
			-h|--help) usage; exit 0 ;;
			-*) refuse "$1 is not an option of this install" ;;
			*)
				[ -z "$commit" ] || refuse "one commit only, $1 is a second"
				commit="$1"
				shift ;;
		esac
	done
	[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || refuse "name cicd's merge commit, its 40 characters written out"
	if [ -z "$programs" ]; then
		[ -z "$root_given" ] && [ -z "$cicd_given" ] || refuse "--root and --cicd are a test's, beside --programs alone"
	else
		absolute "$programs" && [ -d "$programs" ] || refuse "--programs names no folder by its full path"
		[ -z "$root_given" ] || root="$root_given"
		[ -z "$cicd_given" ] || cicd="$cicd_given"
	fi
}

# whether a path is absolute, in Git Bash's form or Windows' with forward slashes
absolute() { [[ "$1" == /* ]] || [[ "$1" =~ ^[A-Za-z]:/ ]]; }

set_programs() {
	local name
	if [ -z "$programs" ]; then
		program[git]="C:/Program Files/Git/mingw64/bin/git.exe"
		program[curl]="C:/Program Files/Git/mingw64/bin/curl.exe"
		program[tar]="C:/Program Files/Git/usr/bin/tar.exe"
		program[sha256sum]="C:/Program Files/Git/usr/bin/sha256sum.exe"
		program[cygpath]="C:/Program Files/Git/usr/bin/cygpath.exe"
		program[icacls]="C:/Windows/System32/icacls.exe"
		program[reg]="C:/Windows/System32/reg.exe"
		program[whoami]="C:/Windows/System32/whoami.exe"
		program[gitpy]="${program[git]}"
		program[aclcheck]=""
		protocols="https"
		return
	fi
	for name in git curl tar sha256sum cygpath icacls reg whoami aclcheck; do
		program[$name]="$programs/$name"
	done
	program[gitpy]="$programs/git"
	if [ -f "$programs/git.native" ]; then
		program[gitpy]="$(< "$programs/git.native")"
		program[gitpy]="${program[gitpy]%"$CR"}"
	fi
	protocols="https,file"
}

# a path in Windows' own form, for icacls
windows_path() { REPLY="${1//\//\\}"; }

# ======================================================================================================================
# The checks before anything, the account, Git's root, UAC, the token and the profile
# ======================================================================================================================

# --programs runs stand ins, so it is refused whenever the token is elevated, read by System32's whoami whatever the
# stand ins say
refuse_if_elevated() {
	local groups
	if [ -f "$real_whoami" ]; then
		groups="$(MSYS_NO_PATHCONV=1 "$real_whoami" /groups /fo csv /nh)" || refuse "whoami could not read the token"
		case "$groups" in
			*'"S-1-16-12288"'*|*'"S-1-16-16384"'*) refuse "--programs runs stand ins and is refused in an elevated window" ;;
		esac
	elif [ "$(/usr/bin/id -u)" = 0 ]; then
		refuse "--programs runs stand ins and is refused as root"
	fi
}

check_account() {
	local said name
	said="$("${program[whoami]}")" || refuse "whoami could not name this window's account"
	said="${said%%"$CR"*}"
	name="${said##*\\}"
	[ "${name,,}" = "$ACCOUNT" ] || refuse "this window runs as $said, and the install runs in the account $ACCOUNT alone"
	say "account $said ok"
}

check_elevated() {
	local groups
	groups="$(MSYS_NO_PATHCONV=1 "${program[whoami]}" /groups /fo csv /nh)" || refuse "whoami could not read the token"
	case "$groups" in
		*'"S-1-16-12288"'*|*'"S-1-16-16384"'*) say "token elevated ok" ;;
		*) refuse "this window is not elevated, open Git Bash in $ACCOUNT with Run as administrator" ;;
	esac
}

check_git_root() {
	local said
	said="$("${program[cygpath]}" -w /)" || refuse "cygpath could not name Git's root"
	said="${said%%"$CR"*}"
	said="${said%\\}"
	[ "$said" = "$GIT_ROOT_WINDOWS" ] \
		|| refuse "this bash's / is $said, not $GIT_ROOT_WINDOWS, so it is not Git's own bash"
	say "git bash $said ok"
}

# one UAC value by its name, its default when it is not set, and any other failure to read it refused, as the launcher
# reads them
uac_value() {
	local name="$1" default="$2" said line pattern status
	said="$(MSYS_NO_PATHCONV=1 "${program[reg]}" query "$UAC_KEY" /v "$name" /reg:64 2>&1)"
	status=$?
	pattern="^[[:space:]]+$name[[:space:]]+REG_DWORD[[:space:]]+0x([0-9a-fA-F]+)[[:space:]]*$"
	while IFS= read -r line; do
		line="${line%"$CR"}"
		if [[ "$line" =~ $pattern ]]; then
			REPLY=$((16#${BASH_REMATCH[1]}))
			return
		fi
		[[ "$line" =~ ^[[:space:]]+$name[[:space:]] ]] && refuse "UAC's $name is not a number the install can read"
	done <<< "$said"
	[ "$status" != 0 ] && [[ "$said" == *"unable to find the specified registry key or value"* ]] \
		|| refuse "UAC's $name could not be read"
	REPLY="$default"
}

check_uac() {
	local lua prompt secure
	uac_value EnableLUA 1
	lua="$REPLY"
	uac_value ConsentPromptBehaviorAdmin 5
	prompt="$REPLY"
	uac_value PromptOnSecureDesktop 1
	secure="$REPLY"
	[ "$lua" != 0 ] \
		|| refuse "UAC is off, EnableLUA is 0, so every process of an administrator holds what the fence withholds"
	[ "$prompt" != 0 ] \
		|| refuse "ConsentPromptBehaviorAdmin is 0, so an administrator's command is elevated with no prompt"
	if [ "$secure" = 0 ] && [ "$prompt" != 1 ] && [ "$prompt" != 2 ]; then
		refuse "PromptOnSecureDesktop is 0 with ConsentPromptBehaviorAdmin $prompt, so a program could answer the prompt"
	fi
	say "uac EnableLUA $lua ConsentPromptBehaviorAdmin $prompt PromptOnSecureDesktop $secure ok"
}

check_startup_files() {
	local profile="${USERPROFILE:-}" name
	[ -n "$profile" ] || refuse "USERPROFILE is not set, so the account's profile cannot be read"
	profile="${profile//\\//}"
	for name in "${STARTUP_FILES[@]}"; do
		if [ -e "$profile/$name" ] || [ -L "$profile/$name" ]; then
			refuse "a shell startup file, $profile/$name, sits in the account's profile, which this window ran first"
		fi
	done
	say "profile $profile holds no shell startup file ok"
}

# ======================================================================================================================
# The folder's permission, read with icacls /save
# ======================================================================================================================

# whether one item's permission grants Administrators and SYSTEM full control and Users read and run and nothing else,
# the folder itself refusing inheritance
sddl_ok() {
	local sddl="$1" top="$2" flags aces ace sid rights seen=" " list=()
	[[ "$sddl" =~ ^D:([A-Z]*)((\([^()]*\))+)$ ]] || return 1
	flags="${BASH_REMATCH[1]}"
	aces="${BASH_REMATCH[2]}"
	[ "$top" = 0 ] || [[ "$flags" == *P* ]] || return 1
	aces="${aces#\(}"
	aces="${aces%\)}"
	readarray -t list <<< "${aces//\)\(/$NL}"
	[ "${#list[@]}" -eq 3 ] || return 1
	for ace in "${list[@]}"; do
		[[ "$ace" =~ ^A\;[A-Z]*\;([A-Za-z0-9]+)\;\;\;([A-Z]{2}|S-1-[0-9-]+)$ ]] || return 1
		rights="${BASH_REMATCH[1],,}"
		sid="${BASH_REMATCH[2]}"
		case "$sid" in
			S-1-5-32-544) sid=BA ;;
			S-1-5-18) sid=SY ;;
			S-1-5-32-545) sid=BU ;;
		esac
		case "$sid:$rights" in
			BA:fa|BA:ga|BA:0x1f01ff|BA:0x10000000|SY:fa|SY:ga|SY:0x1f01ff|SY:0x10000000) ;;
			BU:0x1200a9|BU:0xa0000000) ;;
			*) return 1 ;;
		esac
		[[ "$seen" != *" $sid "* ]] || return 1
		seen="$seen$sid "
	done
}

# every item under the folder read with icacls /save into a file, each item's permission held to design 5.1's, and
# every item counted, so one icacls could not read is never passed
check_permission() {
	local saved="$1" text line count=0 items problems=0 index name
	local lines=()
	: > "$saved" || refuse "the permission's read back could not be written to $saved"
	items="$(/usr/bin/find "$root" -printf x)"
	windows_path "$root"
	local folder="$REPLY"
	windows_path "$saved"
	MSYS_NO_PATHCONV=1 "${program[icacls]}" "$folder" /save "$REPLY" /T /C /Q > /dev/null 2>&1 \
		|| { say "permission FAIL, icacls could not read every item under $root"; return 1; }
	text="$(/usr/bin/iconv -f UTF-16LE -t UTF-8 "$saved")" \
		|| { say "permission FAIL, the read back is unreadable"; return 1; }
	text="${text#"$BOM"}"
	readarray -t lines <<< "${text//"$CR"/}"
	[ "${lines[0]:-}" = "${root##*/}" ] || { say "permission FAIL, the read back does not start at the folder"; return 1; }
	for ((index = 0; index < ${#lines[@]}; index += 2)); do
		name="${lines[index]}"
		[ -n "$name" ] || continue
		count=$((count + 1))
		if ! sddl_ok "${lines[index + 1]:-}" "$((index == 0))"; then
			say "permission FAIL, $name holds ${lines[index + 1]:-nothing}, not design 5.1's three grants"
			problems=1
		fi
	done
	if [ "$count" -lt "${#items}" ]; then
		say "permission FAIL, icacls read $count items of ${#items}"
		return 1
	fi
	[ "$problems" = 0 ] || return 1
	say "permission ok on $count items, Administrators and SYSTEM full control, Users read and run, nothing more"
}

# whether a path is plain, relative, and safe to write on Windows
plain_path() {
	local path="$1" part parts=()
	[ -n "$path" ] && [[ "$path" != /* ]] && [[ "$path" != */ ]] || return 1
	[[ "$path" =~ ^[[:print:]]+$ ]] && [[ "$path" != *[\\:\*\?\"\<\>\|]* ]] || return 1
	IFS=/ read -ra parts <<< "$path"
	for part in "${parts[@]}"; do
		case "$part" in ''|.|..) return 1 ;; esac
	done
}

# the folder before anything is written, there, no link or junction or other special file, only the names an install
# writes, and the permission of design 5.1 on every item
check_folder_before_writing() {
	local entry name saved
	[ -d "$root" ] && [ ! -L "$root" ] || refuse "$root is not a folder, the owner makes it first as design 5.1 says"
	entry="$(/usr/bin/find "$root" ! -type f ! -type d -print -quit)"
	[ -z "$entry" ] || refuse "$entry is a link, a junction or another special file, which the folder never holds"
	shopt -s nullglob dotglob
	for entry in "$root"/*; do
		name="${entry##*/}"
		case "$name" in current.new.*|kdf-scan.py.new.*) continue ;; esac
		[[ "$TOP_NAMES" == *" $name "* ]] || refuse "$root holds $name, which no install writes, the owner looks"
	done
	shopt -u nullglob dotglob
	if [ -e "$root/current" ]; then
		say "folder $root holds an install"
	else
		say "folder $root holds no install yet, a first install"
	fi
	saved="${TEMP:-/tmp}"
	saved="${saved//\\//}/kdf-scan-install-acl.$$"
	check_permission "$saved" || { /usr/bin/rm -f "$saved"; refuse "the folder's permission is not design 5.1's"; }
	/usr/bin/rm -f "$saved"
}

# ======================================================================================================================
# The clean room, a fixed environment under env -i and bash -p from a staging folder of the install's own
# ======================================================================================================================

rerun_clean() {
	local clean=()
	if [ ! -d "$root/staging" ]; then
		/usr/bin/mkdir "$root/staging" || refuse "$root/staging could not be made"
		set_owner "$root/staging" || refuse "icacls could not set the owner of $root/staging"
	fi
	run="$(/usr/bin/mktemp -d "$root/staging/run.XXXXXXXX")" || refuse "a staging folder could not be made"
	run_owned=1
	printf '%s\n' "$$" > "$run/pid"
	/usr/bin/mkdir -p "$run/home" "$run/tmp" || refuse "the staging folder's home could not be made"
	set_owner "$run" /T || refuse "icacls could not set the owner of the staging folder"
	clean=(
		"PATH=/usr/bin:/mingw64/bin:/c/Windows/System32"
		"HOME=$run/home"
		"USERPROFILE=$run/home"
		"TEMP=$run/tmp"
		"TMP=$run/tmp"
		"TMPDIR=$run/tmp"
		'SYSTEMROOT=C:\Windows'
		'WINDIR=C:\Windows'
		"MSYSTEM=MINGW64"
		"LC_ALL=C"
		"TUF_ROOT=$run/home/.sigstore/root"
	)
	local again=("$commit")
	[ -z "$programs" ] || again+=(--programs "$programs")
	[ -z "$root_given" ] || again+=(--root "$root_given")
	[ -z "$cicd_given" ] || again+=(--cicd "$cicd_given")
	say "clean room $run, env -i and bash -p"
	cd "$run" || refuse "the staging folder could not be entered"
	exec /usr/bin/env -i "${clean[@]}" /usr/bin/bash -p "$self" --inner "$run" "${again[@]}"
}

check_clean_room() {
	local name
	[[ $- == *p* ]] || refuse "the clean room runs without bash's privileged mode"
	[ "$PWD" = "$inner" ] || [ "$(cd "$inner" && pwd)" = "$PWD" ] \
		|| refuse "the clean room runs outside its staging folder"
	for name in $(compgen -e); do
		[[ "$CLEAN_NAMES" == *" $name "* ]] || refuse "the clean room holds $name, which env -i never passed"
	done
	[ "$HOME" = "$inner/home" ] || refuse "the clean room's HOME is not its staging folder's"
	say "clean room ok, its environment the fixed list alone"
}

# ======================================================================================================================
# The lock
# ======================================================================================================================

take_lock() {
	local holder stale
	lock="$root/staging/lock"
	if ! /usr/bin/mkdir "$lock" 2>/dev/null; then
		holder=""
		[ ! -f "$lock/pid" ] || holder="$(< "$lock/pid")"
		holder="${holder%%[!0-9]*}"
		[ -n "$holder" ] || refuse "$lock names no holder, remove it by hand once no install runs"
		if kill -0 "$holder" 2>/dev/null; then
			refuse "another install runs, process $holder holds $lock"
		fi
		stale="$root/staging/stale.$$"
		/usr/bin/mv "$lock" "$stale" 2>/dev/null || refuse "another install took $lock meanwhile"
		/usr/bin/rm -rf "$stale"
		/usr/bin/mkdir "$lock" 2>/dev/null || refuse "another install took $lock meanwhile"
		say "lock taken over from process $holder, which no longer runs"
	fi
	lock_held=1
	printf '%s\n' "$$" > "$lock/pid" || refuse "the lock's holder could not be written"
	set_owner "$lock" /T || refuse "icacls could not set the owner of the lock"
	local other other_pid
	shopt -s nullglob
	for other in "$root"/staging/run.* "$root"/staging/stale.*; do
		[ "$other" != "$run" ] || continue
		other_pid=""
		[ ! -f "$other/pid" ] || other_pid="$(< "$other/pid")"
		other_pid="${other_pid%%[!0-9]*}"
		if [ -n "$other_pid" ] && kill -0 "$other_pid" 2>/dev/null; then
			continue
		fi
		/usr/bin/rm -rf "$other"
		say "staging folder ${other##*/} an earlier run left removed"
	done
	shopt -u nullglob
	say "lock $lock held"
}

# ======================================================================================================================
# cicd at the commit, the bundle and the pins
# ======================================================================================================================

git_fetch_options=()

sha_of() {
	local said
	said="$("${program[sha256sum]}" -- "$1")" || { REPLY=""; return 1; }
	said="${said#\\}"
	REPLY="${said%% *}"
	[[ "$REPLY" =~ ^[0-9a-f]{64}$ ]]
}

fetch_cicd() {
	local cicd_git="$run/cicd.git" mine theirs
	git_fetch_options=(-c credential.helper= -c protocol.allow=never -c protocol.https.allow=always)
	if [ -z "$programs" ]; then
		git_fetch_options+=(-c http.sslBackend=openssl -c "http.sslCAInfo=$CA_BUNDLE")
	else
		git_fetch_options+=(-c protocol.file.allow=always)
	fi
	"${program[git]}" init -q --bare --template= "$cicd_git" || refuse "a bare repo for cicd could not be made"
	"${program[git]}" -C "$cicd_git" "${git_fetch_options[@]}" fetch -q --no-tags "$cicd" \
		"+refs/heads/main:refs/remotes/origin/main" || refuse "cicd's main could not be fetched from $cicd"
	"${program[git]}" -C "$cicd_git" cat-file -e "$commit^{commit}" 2>/dev/null \
		|| refuse "$commit is not on cicd's main, so nothing of it runs"
	"${program[git]}" -C "$cicd_git" merge-base --is-ancestor "$commit" refs/remotes/origin/main \
		|| refuse "$commit is not an ancestor of cicd's main, so nothing of it runs"
	say "cicd $commit on main ok"
	"${program[git]}" -C "$cicd_git" cat-file blob "$commit:$INSTALL_PATH" > "$run/install-at-commit.sh" \
		|| refuse "cicd's commit holds no $INSTALL_PATH"
	sha_of "$self" || refuse "this script could not be hashed"
	mine="$REPLY"
	sha_of "$run/install-at-commit.sh" || refuse "the commit's install script could not be hashed"
	theirs="$REPLY"
	[ "$mine" = "$theirs" ] || refuse "this script differs from the commit's own $INSTALL_PATH, fetch it at $commit"
	say "script is the commit's own ok"
	CICD_GIT="$cicd_git"
}

# a folder's files hashed into a manifest, each line a SHA-256, two spaces and a path inside the folder
write_manifest() {
	local folder="$1" line out="" list=()
	readarray -d '' -t list < <(cd "$folder" && /usr/bin/find . -type f ! -path ./manifest.sha256 -printf '%P\0' \
		| /usr/bin/sort -z)
	[ "${#list[@]}" -gt 0 ] || return 1
	local sums
	sums="$(cd "$folder" && printf '%s\0' "${list[@]}" | /usr/bin/xargs -0 "${program[sha256sum]}" --)" || return 1
	local hash path
	while IFS= read -r line; do
		[[ "$line" =~ ^([0-9a-f]{64})\ [\ \*](.+)$ ]] || return 1
		hash="${BASH_REMATCH[1]}"
		path="${BASH_REMATCH[2]}"
		plain_path "$path" || return 1
		out+="$hash  $path$NL"
	done <<< "$sums"
	printf '%s' "$out" > "$folder/manifest.sha256"
}

# whether a folder is whole against its manifest, every file listed with its hash, nothing else, and no link
manifest_whole() {
	local folder="$1" line path listed=() present=()
	[ -f "$folder/manifest.sha256" ] || return 1
	[ -z "$(/usr/bin/find "$folder" ! -type f ! -type d -print -quit)" ] || return 1
	while IFS= read -r line || [ -n "$line" ]; do
		[[ "$line" =~ ^[0-9a-f]{64}\ \ (.+)$ ]] || return 1
		path="${BASH_REMATCH[1]}"
		plain_path "$path" || return 1
		listed+=("$path")
	done < "$folder/manifest.sha256"
	readarray -d '' -t present < <(cd "$folder" && /usr/bin/find . -type f ! -path ./manifest.sha256 -printf '%P\0' \
		| /usr/bin/sort -z)
	[ "$(printf '%s\n' "${listed[@]}" | /usr/bin/sort)" = "$(printf '%s\n' "${present[@]}")" ] || return 1
	(cd "$folder" && "${program[sha256sum]}" --strict --quiet -c manifest.sha256) > /dev/null 2>&1
}

write_bundle() {
	local record meta path mode kind oid name sources=() file
	for name in "${BUNDLE_SOURCES[@]}"; do
		sources+=("scripts/common/$name")
	done
	"${program[git]}" -C "$CICD_GIT" ls-tree -r -z "$commit" -- "${sources[@]}" > "$run/bundle.list" \
		|| refuse "the commit's bundle files could not be listed"
	/usr/bin/mkdir -p "$run/bundle/$commit" || refuse "the bundle's staging folder could not be made"
	BUNDLE="$run/bundle/$commit"
	while IFS= read -r -d '' record; do
		meta="${record%%"$TAB"*}"
		path="${record#*"$TAB"}"
		read -r mode kind oid <<< "$meta"
		[ "$kind" = blob ] && { [ "$mode" = 100644 ] || [ "$mode" = 100755 ]; } \
			|| refuse "cicd's $path at the commit is not a plain file"
		name="${path#scripts/common/}"
		plain_path "$name" || refuse "cicd's $path is not a path a bundle takes"
		[[ "$name" != */* ]] || /usr/bin/mkdir -p "$BUNDLE/${name%/*}" || refuse "the bundle's folders could not be made"
		"${program[git]}" -C "$CICD_GIT" cat-file blob "$oid" > "$BUNDLE/$name" || refuse "cicd's $path could not be read"
	done < "$run/bundle.list"
	for file in "${BUNDLE_FILES[@]}"; do
		[ -f "$BUNDLE/$file" ] || refuse "the commit holds no scripts/common/$file"
	done
	write_manifest "$BUNDLE" || refuse "the bundle's manifest could not be written"
	say "bundle written from the commit's blobs with its manifest"
}

# one of the Python's pins read from kdf_scan.py's blob by a strict pattern, defined once and well formed
python_pin() {
	local name="$1" value="$2" line count=0 found="" pattern
	pattern="^$name +=  *\"($value)\"$"
	while IFS= read -r line || [ -n "$line" ]; do
		line="${line%"$CR"}"
		[[ "$line" =~ ^$name([^A-Za-z0-9_]|$) ]] || continue
		count=$((count + 1))
		if [[ "$line" =~ $pattern ]]; then
			found="${BASH_REMATCH[1]}"
		fi
	done < "$BUNDLE/kdf_scan.py"
	[ "$count" -eq 1 ] && [ -n "$found" ] \
		|| refuse "kdf_scan.py at the commit defines $name $count times or in a form the install does not take"
	REPLY="$found"
}

read_python_pins() {
	local url_pattern='https://[A-Za-z0-9./_~%+-]+'
	[ -z "$programs" ] || url_pattern='(https://|file:///)[A-Za-z0-9./_~%+:-]+'
	python_pin PYTHON_VERSION '[0-9]+\.[0-9]+\.[0-9]+'
	PYTHON_VERSION="$REPLY"
	python_pin PYTHON_BUILD '[0-9]{8}'
	PYTHON_BUILD="$REPLY"
	python_pin PYTHON_ARCHIVE_SHA256 '[0-9a-f]{64}'
	PYTHON_ARCHIVE_SHA256="$REPLY"
	python_pin PYTHON_ARCHIVE_BASE "$url_pattern"
	PYTHON_ARCHIVE_BASE="$REPLY"
	PYTHON_ARCHIVE_URL="$PYTHON_ARCHIVE_BASE/$PYTHON_BUILD/cpython-$PYTHON_VERSION%2B$PYTHON_BUILD"
	PYTHON_ARCHIVE_URL+="-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
	say "python pins $PYTHON_VERSION build $PYTHON_BUILD read by the strict pattern"
}

# one fetch by curl, -q first so it reads no configuration file, on the allowed protocols alone, redirects included
download() {
	local options=(-q --proto "=$protocols" --proto-redir "=$protocols" -fsSL --retry 2)
	[ -n "$programs" ] || options+=(--cacert "$CA_BUNDLE")
	"${program[curl]}" "${options[@]}" -o "$2" "$1"
}

# ======================================================================================================================
# Each part, kept when it checks whole, else staged and checked
# ======================================================================================================================

# a part found damaged, removed on a first install and refused on any other
damaged() {
	local path="$1" what="$2"
	if [ "$first" = 1 ]; then
		/usr/bin/rm -rf "$path" || refuse "$path could not be removed"
		say "$what at $path an earlier run left was not whole, removed to install again"
	else
		refuse "$what at $path is not whole against its pin, damage on disk, rename it aside and install again"
	fi
}

# the Python staged from its pinned archive on every run, so the owners are read and every check made under a Python
# the folder cannot have changed, and the folder's own copy kept only when its manifest is the archive's and it is
# whole against it, never run by the install
stage_python() {
	local name names=() files=() sums line out=""
	download "$PYTHON_ARCHIVE_URL" "$run/python.tar.gz" || refuse "the Python's archive could not be fetched"
	sha_of "$run/python.tar.gz" && [ "$REPLY" = "$PYTHON_ARCHIVE_SHA256" ] \
		|| refuse "the Python's archive is ${REPLY:-unreadable}, not its pin $PYTHON_ARCHIVE_SHA256"
	say "python archive sha256 ok"
	readarray -t names < <(cd "$run" && "${program[tar]}" --force-local -tzf python.tar.gz)
	[ "${#names[@]}" -gt 0 ] || refuse "the Python's archive lists nothing"
	for name in "${names[@]}"; do
		name="${name%"$CR"}"
		[[ "$name" == python/* ]] && [[ "$name" != */../* ]] && [[ "$name" != *\\* ]] \
			|| refuse "the Python's archive holds $name, outside python/"
		[[ "$name" == */ ]] && continue
		plain_path "${name#python/}" || refuse "the Python's archive holds $name, a path the install does not take"
		files+=("${name#python/}")
	done
	/usr/bin/mkdir -p "$run/unpack" || refuse "the Python's staging folder could not be made"
	(cd "$run" && "${program[tar]}" --force-local -xzf python.tar.gz -C unpack) \
		|| refuse "tar could not unpack the archive"
	[ -z "$(/usr/bin/find "$run/unpack" ! -type f ! -type d -print -quit)" ] || refuse "the archive unpacked a link"
	[ "$(cd "$run/unpack" && /usr/bin/find . -mindepth 1 -maxdepth 1 -printf '%P\n')" = python ] \
		|| refuse "the archive unpacked something beside python/"
	[ "$(cd "$run/unpack/python" && /usr/bin/find . -type f -printf '%P\n' | /usr/bin/sort)" \
		= "$(printf '%s\n' "${files[@]}" | /usr/bin/sort -u)" ] || refuse "the unpacked files are not the archive's listing"
	sums="$(cd "$run/unpack/python" && printf '%s\0' "${files[@]}" | /usr/bin/sort -zu \
		| /usr/bin/xargs -0 "${program[sha256sum]}" --)" || refuse "the Python's files could not be hashed"
	while IFS= read -r line; do
		[[ "$line" =~ ^([0-9a-f]{64})\ [\ \*](.+)$ ]] || refuse "sha256sum named a file the manifest cannot hold"
		out+="${BASH_REMATCH[1]}  ${BASH_REMATCH[2]}$NL"
	done <<< "$sums"
	/usr/bin/mkdir -p "$run/python" && /usr/bin/mv "$run/unpack/python" "$run/python/$PYTHON_VERSION" \
		|| refuse "the Python could not be staged"
	printf '%s' "$out" > "$run/python/$PYTHON_VERSION/manifest.sha256" || refuse "the manifest could not be written"
	manifest_whole "$run/python/$PYTHON_VERSION" || refuse "the staged Python is not whole against its manifest"
	py="$run/python/$PYTHON_VERSION/python.exe"
	say "python $PYTHON_VERSION staged, its manifest written from the archive's listing, ${#files[@]} files"
}

# the folder's own Python kept when it is the staged one's, judged only after the owners are read
place_python() {
	local folder="$root/python/$PYTHON_VERSION"
	if [ -e "$folder" ]; then
		if manifest_whole "$folder" \
			&& [ "$(< "$folder/manifest.sha256")" = "$(< "$run/python/$PYTHON_VERSION/manifest.sha256")" ]; then
			say "python $PYTHON_VERSION in place kept, whole and the pinned archive's own"
			return
		fi
		damaged "$folder" "python $PYTHON_VERSION"
	fi
	moves+=("$run/python/$PYTHON_VERSION|$folder")
}

# every owner and grant under the folder read before the install changes any, by the launcher's own reader from the
# commit's blobs under the Python staged from its archive, so a wrong owner is named with its evidence intact, the owner
# set first only on the staging folder this run wrote
read_owners() {
	local said line
	set_owner "$run" /T || refuse "icacls could not set the owner of the staging folder"
	said="$(acl_check "$BUNDLE/kdf_scan_launcher.py")" || {
		while IFS= read -r line; do say "owner FAIL, ${line%"$CR"}"; done <<< "$said"
		refuse "the folder's owners or grants are not design 5.1's, read before the install changed any, the owner looks"
	}
	say "owners and grants ok before any change, read by the launcher's own reader"
}

read_all_pins() {
	local said line name value url='https://[A-Za-z0-9./_~%+-]+' sha='[0-9a-f]{64}' semver='[0-9]+\.[0-9]+\.[0-9]+'
	[ -z "$programs" ] || url='(https://|file:///)[A-Za-z0-9./_~%+:-]+'
	said="$("$py" -I -S -B "$BUNDLE/kdf_scan.py" --pins)" || refuse "the pinned Python could not print the pins"
	while IFS= read -r line; do
		line="${line%"$CR"}"
		[ -n "$line" ] || continue
		[[ "$line" =~ ^([A-Z][A-Z0-9_]*)=(.*)$ ]] || refuse "--pins printed a line the install does not take"
		name="${BASH_REMATCH[1]}"
		value="${BASH_REMATCH[2]}"
		[ -z "${pin[$name]+x}" ] || refuse "--pins printed $name twice"
		[[ " ${PIN_NAMES[*]} " == *" $name "* ]] || refuse "--pins printed $name, which the install does not know"
		pin[$name]="$value"
	done <<< "$said"
	for name in "${PIN_NAMES[@]}"; do
		[ -n "${pin[$name]+x}" ] || refuse "--pins printed no $name"
	done
	held() { [[ "${pin[$1]}" =~ ^($2)$ ]] || refuse "--pins printed $1 as ${pin[$1]}, not a value the install takes"; }
	held OPENGREP_VERSION "v$semver"
	held OPENGREP_ASSET '[A-Za-z0-9._-]+'
	held OPENGREP_IDENTITY 'https://github\.com/[A-Za-z0-9._/-]+@refs/[A-Za-z0-9._/-]+'
	held OPENGREP_ISSUER 'https://token\.actions\.githubusercontent\.com'
	held ZIZMOR_VERSION "$semver"
	held COSIGN_VERSION "v$semver"
	held RULES_COMMIT '[0-9a-f]{40}'
	for name in OPENGREP_SHA256 ZIZMOR_WHEEL_SHA256 ZIZMOR_SHA256 COSIGN_SHA256 RULES_DIGEST PYTHON_ARCHIVE_SHA256; do
		held "$name" "$sha"
	done
	for name in OPENGREP_URL ZIZMOR_WHEEL_URL COSIGN_URL RULES_REPO RULES_LICENSE_URL PYTHON_ARCHIVE_BASE; do
		held "$name" "$url"
	done
	[ "${pin[PYTHON_VERSION]}" = "$PYTHON_VERSION" ] && [ "${pin[PYTHON_BUILD]}" = "$PYTHON_BUILD" ] \
		&& [ "${pin[PYTHON_ARCHIVE_SHA256]}" = "$PYTHON_ARCHIVE_SHA256" ] \
		&& [ "${pin[PYTHON_ARCHIVE_BASE]}" = "$PYTHON_ARCHIVE_BASE" ] \
		&& [ "${pin[PYTHON_ARCHIVE_URL]}" = "$PYTHON_ARCHIVE_URL" ] \
		|| refuse "--pins names a Python other than the strict pattern read, so neither is trusted"
	say "pins ${#pin[@]} printed by the pinned Python, each well formed, the Python's matching the pattern ok"
}

# on a first install, every version folder but the pinned ones an earlier run left, and anything else there, removed
clear_first_install() {
	local kind wanted entry
	[ "$first" = 1 ] || return 0
	shopt -s nullglob dotglob
	for kind in opengrep zizmor python bundles rules; do
		case "$kind" in
			opengrep) wanted="${pin[OPENGREP_VERSION]}" ;;
			zizmor) wanted="${pin[ZIZMOR_VERSION]}" ;;
			python) wanted="$PYTHON_VERSION" ;;
			bundles) wanted="$commit" ;;
			rules) wanted="semgrep-rules.git" ;;
		esac
		for entry in "$root/$kind"/*; do
			case "${entry##*/}" in
				"$wanted") continue ;;
				semgrep-rules-license-*.html) [ "$kind" = rules ] && continue ;;
			esac
			/usr/bin/rm -rf "$entry" || refuse "$entry could not be removed"
			say "$entry an earlier run left removed, a first install keeps only the pinned versions"
		done
	done
	shopt -u nullglob dotglob
}

stage_opengrep() {
	local version="${pin[OPENGREP_VERSION]}" folder staged cosign
	folder="$root/opengrep/$version"
	if [ -e "$folder" ]; then
		if [ "$(cd "$folder" && /usr/bin/find . -mindepth 1 -printf '%P\n')" = opengrep.exe ] \
			&& [ ! -L "$folder/opengrep.exe" ] && sha_of "$folder/opengrep.exe" && [ "$REPLY" = "${pin[OPENGREP_SHA256]}" ]; then
			say "opengrep $version kept, its sha256 the pin's"
			return
		fi
		damaged "$folder" "opengrep $version"
	fi
	/usr/bin/mkdir -p "$run/cosign" "$run/opengrep/$version" "$run/signature" || refuse "staging could not be made"
	cosign="$run/cosign/cosign.exe"
	download "${pin[COSIGN_URL]}" "$cosign" || refuse "cosign could not be fetched"
	sha_of "$cosign" && [ "$REPLY" = "${pin[COSIGN_SHA256]}" ] \
		|| refuse "cosign is ${REPLY:-unreadable}, not its pin ${pin[COSIGN_SHA256]}"
	# curl writes no execute bit, which Linux needs and Git for Windows' noacl mount ignores
	/usr/bin/chmod 0755 "$cosign" || refuse "cosign could not be made runnable"
	say "cosign ${pin[COSIGN_VERSION]} sha256 ok, run from staging"
	staged="$run/opengrep/$version/opengrep.exe"
	download "${pin[OPENGREP_URL]}" "$staged" || refuse "Opengrep's asset could not be fetched"
	download "${pin[OPENGREP_URL]}.cert" "$run/signature/opengrep.cert" || refuse "Opengrep's .cert could not be fetched"
	download "${pin[OPENGREP_URL]}.sig" "$run/signature/opengrep.sig" || refuse "Opengrep's .sig could not be fetched"
	sha_of "$staged" && [ "$REPLY" = "${pin[OPENGREP_SHA256]}" ] \
		|| refuse "Opengrep's asset is ${REPLY:-unreadable}, not its pin ${pin[OPENGREP_SHA256]}"
	say "opengrep $version sha256 ok"
	"$cosign" verify-blob --certificate "$run/signature/opengrep.cert" --signature "$run/signature/opengrep.sig" \
		--certificate-identity "${pin[OPENGREP_IDENTITY]}" --certificate-oidc-issuer "${pin[OPENGREP_ISSUER]}" \
		"$staged" || refuse "cosign did not verify Opengrep's signature as ${pin[OPENGREP_IDENTITY]}"
	say "opengrep signature verified, identity ${pin[OPENGREP_IDENTITY]}"
	moves+=("$run/opengrep/$version|$folder")
}

stage_zizmor() {
	local version="${pin[ZIZMOR_VERSION]}" folder inside
	folder="$root/zizmor/$version"
	if [ -e "$folder" ]; then
		if [ "$(cd "$folder" && /usr/bin/find . -type f -printf '%P\n')" = Scripts/zizmor.exe ] \
			&& [ -z "$(/usr/bin/find "$folder" ! -type f ! -type d -print -quit)" ] \
			&& sha_of "$folder/Scripts/zizmor.exe" && [ "$REPLY" = "${pin[ZIZMOR_SHA256]}" ]; then
			say "zizmor $version kept, its sha256 the pin's"
			return
		fi
		damaged "$folder" "zizmor $version"
	fi
	download "${pin[ZIZMOR_WHEEL_URL]}" "$run/zizmor.whl" || refuse "zizmor's wheel could not be fetched"
	sha_of "$run/zizmor.whl" && [ "$REPLY" = "${pin[ZIZMOR_WHEEL_SHA256]}" ] \
		|| refuse "zizmor's wheel is ${REPLY:-unreadable}, not its pin ${pin[ZIZMOR_WHEEL_SHA256]}"
	(cd "$run" && "$py" -I -S -B -m zipfile -e zizmor.whl wheel) || refuse "zizmor's wheel could not be opened"
	inside="$run/wheel/zizmor-$version.data/scripts/zizmor.exe"
	[ -f "$inside" ] && [ ! -L "$inside" ] || refuse "zizmor's wheel holds no zizmor-$version.data/scripts/zizmor.exe"
	sha_of "$inside" && [ "$REPLY" = "${pin[ZIZMOR_SHA256]}" ] \
		|| refuse "the wheel's zizmor.exe is ${REPLY:-unreadable}, not its pin ${pin[ZIZMOR_SHA256]}"
	/usr/bin/mkdir -p "$run/zizmor/$version/Scripts" && /usr/bin/mv "$inside" "$run/zizmor/$version/Scripts/zizmor.exe" \
		|| refuse "zizmor could not be staged"
	say "zizmor $version taken out of its wheel, both sha256 ok"
	moves+=("$run/zizmor/$version|$folder")
}

rules_digest_of() {
	local said
	said="$("$py" -I -S -B "$BUNDLE/kdf_scan.py" --rules-digest "$1" --git "${program[gitpy]}")" || return 1
	REPLY="${said%%"$CR"*}"
}

stage_rules() {
	local folder="$root/rules/semgrep-rules.git" target staged="$run/rules/semgrep-rules.git" licence date
	local wanted="${pin[RULES_COMMIT]}"
	target="$folder"
	if [ -e "$folder" ]; then
		if [ -n "$(/usr/bin/find "$folder" ! -type f ! -type d -print -quit)" ]; then
			damaged "$folder" "the rules clone"
		elif "${program[git]}" -C "$folder" cat-file -e "$wanted^{commit}" 2>/dev/null; then
			if rules_digest_of "$folder" && [ "$REPLY" = "${pin[RULES_DIGEST]}" ]; then
				say "rules $wanted kept, the digest the pin's"
				staged=""
			else
				damaged "$folder" "the rules clone"
			fi
		else
			"${program[git]}" -C "$folder" "${git_fetch_options[@]}" fetch -q --no-tags --depth 1 "${pin[RULES_REPO]}" \
				"$wanted" && "${program[git]}" -C "$folder" update-ref "refs/kdf-scan/rules/$wanted" "$wanted" \
				|| refuse "the rules at $wanted could not be fetched into $folder"
			rules_digest_of "$folder" && [ "$REPLY" = "${pin[RULES_DIGEST]}" ] \
				|| refuse "the rules' digest at $wanted is ${REPLY:-unreadable}, not the pin ${pin[RULES_DIGEST]}"
			say "rules $wanted fetched beside the earlier commits, the digest the pin's"
			staged=""
		fi
	fi
	if [ -n "$staged" ] && [ ! -e "$folder" ]; then
		"${program[git]}" init -q --bare --template= "$staged" || refuse "a bare repo for the rules could not be made"
		"${program[git]}" -C "$staged" "${git_fetch_options[@]}" fetch -q --no-tags --depth 1 "${pin[RULES_REPO]}" \
			"$wanted" || refuse "the rules at $wanted could not be fetched from ${pin[RULES_REPO]}"
		"${program[git]}" -C "$staged" update-ref "refs/kdf-scan/rules/$wanted" "$wanted" \
			|| refuse "the rules' commit could not be kept by a ref"
		rules_digest_of "$staged" && [ "$REPLY" = "${pin[RULES_DIGEST]}" ] \
			|| refuse "the rules' digest at $wanted is ${REPLY:-unreadable}, not the pin ${pin[RULES_DIGEST]}"
		say "rules $wanted fetched, the digest the pin's"
		moves+=("$staged|$target")
	fi
	date="$(/usr/bin/date +%F)"
	licence="$root/rules/semgrep-rules-license-$date.html"
	if [ ! -e "$licence" ]; then
		/usr/bin/mkdir -p "$run/licence" || refuse "the licence page's staging folder could not be made"
		download "${pin[RULES_LICENSE_URL]}" "$run/licence/semgrep-rules-license-$date.html" \
			&& [ -s "$run/licence/semgrep-rules-license-$date.html" ] \
			|| refuse "the rules' licence page could not be saved from ${pin[RULES_LICENSE_URL]}, so the terms are not kept"
		moves+=("$run/licence/semgrep-rules-license-$date.html|$licence")
		say "rules' licence page saved with its date, $date"
	fi
}

stage_bundle() {
	local folder="$root/bundles/$commit"
	if [ -e "$folder" ]; then
		if manifest_whole "$folder" && [ "$(< "$folder/manifest.sha256")" = "$(< "$BUNDLE/manifest.sha256")" ]; then
			say "bundle $commit kept, whole and the commit's own"
			return
		fi
		damaged "$folder" "the bundle $commit"
	fi
	moves+=("$BUNDLE|$folder")
}

# ======================================================================================================================
# Into place, the owner set, the read back, then current
# ======================================================================================================================

move_into_place() {
	local move staged target moved=0
	for move in "${moves[@]}"; do
		staged="${move%%|*}"
		target="${move#*|}"
		[ ! -e "$target" ] || fail "$target appeared while the install ran"
		/usr/bin/mkdir -p "${target%/*}" || fail "${target%/*} could not be made"
		/usr/bin/mv "$staged" "$target" || fail "$staged could not be moved to $target"
		set_owner "$target" /T || fail "icacls could not set the owner of $target"
		moved=$((moved + 1))
		say "moved into place, ${target#"$root"/}"
	done
	[ "$moved" -gt 0 ] || say "nothing new to move, every part already in place"
}

set_owner() {
	windows_path "$1"
	MSYS_NO_PATHCONV=1 "${program[icacls]}" "$REPLY" /setowner "$ADMINISTRATORS" "${@:2}" /C /Q > /dev/null
}

acl_check() {
	if [ -n "$programs" ]; then
		"${program[aclcheck]}" "$1" "$root"
	else
		"$py" -I -S -B -c "$ACL_CODE" "$1" "$root"
	fi
}

read_back() {
	local launcher="$root/bundles/$commit/kdf_scan_launcher.py" said line
	py="$root/python/$PYTHON_VERSION/python.exe"
	# the read back's own file made before the staging folder's owner is set, so it too is owned by Administrators
	# whatever owner Windows gives a new file, and nothing outside what this run wrote has its owner changed
	: > "$run/acl.read" || fail "the permission's read back could not be written"
	set_owner "$run" /T || fail "icacls could not set the owner of the staging folder"
	say "owner Administrators set on everything this run wrote"
	check_permission "$run/acl.read" || fail "the permission read back is not design 5.1's"
	said="$(acl_check "$launcher")" || {
		while IFS= read -r line; do say "permission FAIL, ${line%"$CR"}"; done <<< "$said"
		fail "the launcher's reader refused the folder's owners or grants"
	}
	say "owners and grants ok by the launcher's own reader, no link or junction"
	manifest_whole "$root/python/$PYTHON_VERSION" || fail "the Python in place is not whole against its manifest"
	manifest_whole "$root/bundles/$commit" || fail "the bundle in place is not whole against its manifest"
	sha_of "$root/opengrep/${pin[OPENGREP_VERSION]}/opengrep.exe" && [ "$REPLY" = "${pin[OPENGREP_SHA256]}" ] \
		|| fail "Opengrep in place is not its pin"
	sha_of "$root/zizmor/${pin[ZIZMOR_VERSION]}/Scripts/zizmor.exe" && [ "$REPLY" = "${pin[ZIZMOR_SHA256]}" ] \
		|| fail "zizmor in place is not its pin"
	say "python and bundle whole against their manifests, both executables their pins"
}

# a file replaced by a new one in the same folder renamed over it, tried again while a scan holds it open
replace_file() {
	local new="$1" target="$2" tries=0
	set_owner "$new" || fail "icacls could not set the owner of $new"
	until /usr/bin/mv -f "$new" "$target" 2>/dev/null; do
		tries=$((tries + 1))
		[ "$tries" -lt 20 ] || fail "$target stayed held open, so it was not replaced"
		say "$target is held open, trying again"
		/usr/bin/sleep 1
	done
}

replace_current() {
	local launcher="$root/bundles/$commit/kdf_scan_launcher.py" named="" wanted
	sha_of "$launcher" || fail "the bundle's launcher could not be hashed"
	wanted="$REPLY"
	if [ -f "$root/kdf-scan.py" ] && sha_of "$root/kdf-scan.py" && [ "$REPLY" = "$wanted" ]; then
		say "kdf-scan.py already the bundle's launcher"
	else
		/usr/bin/cp "$launcher" "$root/kdf-scan.py.new.$$" || fail "the launcher could not be written"
		replace_file "$root/kdf-scan.py.new.$$" "$root/kdf-scan.py"
		say "kdf-scan.py replaced by the bundle's launcher"
	fi
	[ ! -f "$root/current" ] || named="$(< "$root/current")"
	if [ "${named%%[!0-9a-f]*}" = "$commit" ]; then
		say "current already names $commit"
		return
	fi
	printf '%s\n' "$commit" > "$root/current.new.$$" || fail "current's new file could not be written"
	replace_file "$root/current.new.$$" "$root/current"
	say "current names $commit"
}

# ======================================================================================================================
# The two runs, outside the clean room and in it
# ======================================================================================================================

outer_main() {
	local prefix=""
	[ -z "$programs" ] || prefix="TEST RUN with stand ins from $programs, never an install, "
	say "${prefix}installing cicd $commit into $root"
	[[ $- == *p* ]] || refuse "run it with Git's bash and its privileged mode, bash -p, so no BASH_ENV reaches it"
	self="${BASH_SOURCE[0]}"
	absolute "$self" || refuse "run the script by its full path"
	[ -z "$programs" ] || refuse_if_elevated
	set_programs
	check_account
	check_git_root
	check_uac
	check_elevated
	check_startup_files
	check_folder_before_writing
	rerun_clean
}

inner_main() {
	run="$inner"
	run_owned=1
	self="${BASH_SOURCE[0]}"
	check_clean_room
	export GIT_CONFIG_GLOBAL="$run/empty.gitconfig" GIT_CONFIG_NOSYSTEM=1 GIT_NO_REPLACE_OBJECTS=1
	export GIT_NO_LAZY_FETCH=1 GIT_TERMINAL_PROMPT=0 GIT_OPTIONAL_LOCKS=0
	: > "$GIT_CONFIG_GLOBAL"
	set_programs
	check_account
	check_git_root
	check_uac
	check_elevated
	take_lock
	[ -e "$root/current" ] || first=1
	fetch_cicd
	write_bundle
	read_python_pins
	stage_python
	read_owners
	read_all_pins
	clear_first_install
	place_python
	stage_opengrep
	stage_zizmor
	stage_rules
	stage_bundle
	move_into_place
	read_back
	replace_current
}

main() {
	trap finish EXIT
	parse_args "$@"
	if [ -n "$inner" ]; then
		inner_main
	else
		outer_main
	fi
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
	main "$@"
fi
