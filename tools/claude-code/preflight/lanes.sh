#!/usr/bin/env bash
# lanes.sh, the Linux pre-flight's lane runner (D-072, D-078), run by the image's lanes stage alone, never by hand.
#
#   bash lanes.sh [--setup <target>] [--mirrors <folder>] <work folder> <results file> <seconds a lane takes> <lane>...
#   bash lanes.sh --tails <results file> <run id>
#
# Runs the repo's setup target first when one is named, then each lane named in the commit's tree in the work folder,
# in the order given, each under timeout, and writes "<lane> <status>" for each to the results file once every lane has
# run, 124 for a lane that ran out of time, so a lane's stray write there never changes a status. The image keeps this
# script and the commit's tar as root's, so no lane changes the script its last step runs. It reads the lanes of the
# owner's own repos truly, and does not isolate one lane from another, since every lane runs in the same work tree as
# the same user, so a lane written to deceive could change what a later lane runs, and CI on GitHub stays the gate. A
# lane is a make target, or actionlint, the image's actionlint over the repo's workflows, which is red, 127, when no
# shellcheck is on the PATH, since actionlint then skips every run: script. Each lane's output, stdout and stderr in
# order, goes to a file of its own in lanes/ beside the results file and is printed when the lane ends, so a process a
# lane leaves running never holds the step open past the lane's timeout, and the status read is the lane's own. It
# exits 0 whatever the lanes did, so a red lane never stops the ones after it and the build goes on to the step that
# prints the results, which kdf-preflight.sh reads, and 1 only when it cannot write the statuses whole, which stops the
# build before that step. The build's arguments are dropped before setup starts, so neither setup nor a lane meets the
# run id in its own environment, though one that reads its parent's from /proc could, which the wrapper's reading does
# not rely on, and so are the base image's own Python variables, which GitHub's runner does not have.
#
# Setup (D-078). Each mirror the wrapper fetched, <folder>/<repo>.git, is read through CI's own rewrite of the repo's
# https URL to the mirror on disk, GIT_CONFIG_COUNT and each GIT_CONFIG_KEY_<n> and GIT_CONFIG_VALUE_<n>, the lines
# CI's step "Point git at the private mirrors" writes, set for setup and every lane, and none with no mirror. Setup runs
# under the same timeout, its output in setup.log beside the results file and printed when it ends. A green setup is
# followed by the removal of every file named .env* in the work tree that git does not track and that is no
# .env*.example, each named, since CI's checkout has none and a lane would otherwise read an example's values. A file
# that cannot be removed, or a list git cannot give, records setup red, 1. A red setup records each make lane skipped
# and still runs actionlint, which needs no setup. Setup's "<target> <status>" goes in the file setup beside the
# results, written once every lane has run by the same remove, write and read back as the statuses, so no lane can
# forge it, and with no setup no such file is left.
#
# --tails prints to stderr, first the last 50 lines of a red setup's own output, each after
# "KDF-PREFLIGHT-SETUP-TAIL <run id> ", then for each lane the results file records as failed, never one skipped, the
# last 50 lines of its own output, each after "KDF-PREFLIGHT-TAIL <run id> <lane> ". Each line is cut to 300 bytes and
# all of them to 64 KiB, with a notice where the budget runs out. The image prints them in its last step, after the
# results, so BuildKit clipping a noisy lanes step never takes a failed lane's reason with it, and an excerpt clipped
# in turn never takes a result. It always exits 0.
set -u
export LC_ALL=C

notice=" [the excerpts stop here, their 65536 bytes spent]"

# the last 50 lines of one output, each cut to 300 bytes and printed after its marker, while the budget leaves room for
# the line and the longest notice, so a later excerpt's notice still fits. Returns 1 once the budget is spent and the
# notice printed
excerpt() {
	local marker="$1" file="$2" line
	while IFS= read -r line; do
		# the whole line counts, its marker too, since BuildKit's limit counts what reaches the log, and the notice
		# always keeps its room, so all of it stays within the budget
		line="$marker $line"
		if [ $(( ${#line} + 1 + room + 1 )) -gt "$budget" ]; then
			printf '%s%s\n' "$marker" "$notice" >&2
			return 1
		fi
		printf '%s\n' "$line" >&2
		budget=$((budget - ${#line} - 1))
	done < <(tail -n 50 "$file" | cut -b 1-300)
	return 0
}

if [ "${1:-}" = --tails ]; then
	results="$2" id="$3" budget=65536
	folder="$(dirname "$results")"
	outputs="$folder/lanes"
	setup_red=0
	if [ -f "$folder/setup" ] && read -r _ status < "$folder/setup" && [ "$status" != 0 ]; then setup_red=1; fi
	# the room the longest notice needs, setup's or a failed lane's
	longest=""
	[ "$setup_red" -eq 0 ] || longest="KDF-PREFLIGHT-SETUP-TAIL $id$notice"
	while read -r lane status; do
		case "$status" in 0|skipped) continue ;; esac
		candidate="KDF-PREFLIGHT-TAIL $id $lane$notice"
		[ "${#candidate}" -le "${#longest}" ] || longest="$candidate"
	done < "$results"
	room=${#longest}
	if [ "$setup_red" -eq 1 ] && [ -f "$folder/setup.log" ]; then
		excerpt "KDF-PREFLIGHT-SETUP-TAIL $id" "$folder/setup.log" || exit 0
	fi
	while read -r lane status; do
		case "$status" in 0|skipped) continue ;; esac
		[ -f "$outputs/$lane.log" ] || continue
		excerpt "KDF-PREFLIGHT-TAIL $id $lane" "$outputs/$lane.log" || exit 0
	done < "$results"
	exit 0
fi

setup="" mirrors=""
while [ $# -gt 0 ]; do
	case "$1" in
		--setup) [ $# -ge 2 ] || exit 1; setup="$2"; shift 2 ;;
		--mirrors) [ $# -ge 2 ] || exit 1; mirrors="$2"; shift 2 ;;
		*) break ;;
	esac
done
work="$1" results="$2" limit="$3"
shift 3
# the build's arguments, and the base image's own PYTHON_VERSION and PYTHON_SHA256, which GitHub's runner never sets
# and which a Makefile's PYTHON_VERSION ?= would take, as cicd's took 3.14.7 and looked for python3.14.7
unset RUN_ID LANE_TIMEOUT LANES SETUP PYTHON_VERSION PYTHON_SHA256
# CI's rewrite of each private repo's https URL to its mirror, read by git in setup and every lane, so pip clones the
# mirror where the repo's requirement files name GitHub (D-035, D-078)
count=0
if [ -n "$mirrors" ]; then
	for mirror in "$mirrors"/*.git; do
		[ -d "$mirror" ] || continue
		repo="$(basename "$mirror" .git)"
		export "GIT_CONFIG_KEY_$count=url.file://$mirror.insteadOf"
		export "GIT_CONFIG_VALUE_$count=https://github.com/Needless2Say/$repo.git"
		count=$((count + 1))
	done
fi
[ "$count" -eq 0 ] || export GIT_CONFIG_COUNT="$count"
# the results file and the outputs folder are named from where the script starts, so both are made whole before the
# lanes change folder
case "$results" in /*) ;; *) results="$PWD/$results" ;; esac
folder="$(dirname "$results")"
outputs="$folder/lanes"
setup_file="$folder/setup" setup_log="$folder/setup.log"
mkdir -p "$outputs" || exit 0
cd "$work" || exit 0

# a line said in the output and kept in setup's own, so a red setup's excerpt carries it
said() {
	printf '%s\n' "$1"
	printf '%s\n' "$1" >> "$setup_log"
}

setup_status=0
if [ -n "$setup" ]; then
	printf '\n==== kdf-preflight setup %s ====\n' "$setup"
	timeout --kill-after=10 "$limit" make "$setup" > "$setup_log" 2>&1
	setup_status=$?
	cat "$setup_log"
	if [ "$setup_status" -eq 0 ]; then
		# CI's checkout has no .env file, so each one setup left that git does not track and that is no example goes,
		# and one that cannot, or a list git cannot give, makes setup red, since no lane runs on a tree unlike CI's
		untracked="$folder/untracked"
		if ! git ls-files -z --others > "$untracked" 2>> "$setup_log"; then
			said "kdf-preflight: git could not list the files setup left, so setup reads red"
			setup_status=1
		fi
		while IFS= read -r -d '' path; do
			name="${path##*/}"
			case "${name,,}" in .env*.example) continue ;; .env*) ;; *) continue ;; esac
			if rm -f -- "$path" 2>/dev/null && [ ! -e "$path" ] && [ ! -L "$path" ]; then
				said "kdf-preflight: removed $path, which setup left and git does not track"
			else
				said "kdf-preflight: $path could not be removed, so setup reads red"
				setup_status=1
			fi
		done < "$untracked"
		rm -f "$untracked"
	fi
	printf '==== kdf-preflight setup %s exited %s ====\n' "$setup" "$setup_status"
fi

# each status kept here and written only after every lane has run, so no lane can rewrite another's
recorded=()
for lane in "$@"; do
	output="$outputs/$lane.log"
	if [ -n "$setup" ] && [ "$setup_status" -ne 0 ] && [ "$lane" != actionlint ]; then
		printf '\n==== kdf-preflight lane %s not run, setup failed ====\n' "$lane"
		recorded+=("$lane skipped")
		continue
	fi
	printf '\n==== kdf-preflight lane %s ====\n' "$lane"
	if [ "$lane" = actionlint ] && ! command -v shellcheck >/dev/null 2>&1; then
		# actionlint skips every run: script without ShellCheck, so a lane that passed here would hide what CI's lint
		# job finds (D-072)
		printf 'kdf-preflight: no shellcheck on the PATH, so the actionlint lane does not run\n' > "$output"
		status=127
	elif [ "$lane" = actionlint ]; then
		timeout --kill-after=10 "$limit" actionlint > "$output" 2>&1
		status=$?
	else
		timeout --kill-after=10 "$limit" make "$lane" > "$output" 2>&1
		status=$?
	fi
	cat "$output"
	printf '==== kdf-preflight lane %s exited %s ====\n' "$lane" "$status"
	recorded+=("$lane $status")
done
# a lane runs as the same user, so it may have written there or locked the files or their folder. All are made the
# script's own again, the old files removed, the statuses and setup's written and read back, and when they cannot be
# written whole, or a setup file stays where no setup ran, the script fails, the build stops before the step that
# prints the results, and the run reads as one that could not complete, never as a status a lane left
written="$(printf '%s\n' "${recorded[@]}")"
chmod u+rwx "$folder" 2>/dev/null
for file in "$results" "$setup_file"; do
	[ ! -e "$file" ] || chmod -R u+rwx "$file" 2>/dev/null
	rm -rf "$file"
done
unwritten() {
	printf 'kdf-preflight: the statuses could not be written whole to %s, so this run cannot be read\n' "$1" >&2
	exit 1
}
if ! printf '%s\n' "$written" > "$results" 2>/dev/null || [ "$(cat "$results" 2>/dev/null)" != "$written" ]; then
	unwritten "$results"
fi
if [ -n "$setup" ]; then
	if ! printf '%s %s\n' "$setup" "$setup_status" > "$setup_file" 2>/dev/null \
		|| [ "$(cat "$setup_file" 2>/dev/null)" != "$setup $setup_status" ]; then
		unwritten "$setup_file"
	fi
elif [ -e "$setup_file" ] || [ -L "$setup_file" ]; then
	unwritten "$setup_file"
fi
exit 0
