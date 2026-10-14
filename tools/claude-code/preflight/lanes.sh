#!/usr/bin/env bash
# lanes.sh, the Linux pre-flight's lane runner (D-072), run by the image's lanes stage alone, never by hand.
#
#   bash lanes.sh <work folder> <results file> <seconds a lane may take> <lane>...
#   bash lanes.sh --tails <results file> <run id>
#
# Runs each lane named in the commit's tree in the work folder, in the order given, each under timeout, and appends
# "<lane> <status>" to the results file, 124 for a lane that ran out of time. A lane is a make target, or actionlint,
# the image's actionlint over the repo's workflows, which is red, 127, when no shellcheck is on the PATH, since
# actionlint then skips every run: script. Each lane's output, stdout and stderr in order, goes to a file of its own in
# lanes/ beside the results file and is printed when the lane ends, so a process a lane leaves running never holds the
# step open past the lane's timeout, and the status read is the lane's own. It always exits 0, so a red lane never
# stops the ones after it and the build goes on to the step that prints the results, which kdf-preflight.sh reads. The
# build's arguments are dropped before a lane starts, so no lane can print a line with this run's id, and so are the
# base image's own Python variables, which GitHub's runner does not have.
#
# --tails prints to stderr, for each lane the results file records as failed, the last 50 lines of its own output,
# each cut to 300 bytes and all of them to 64 KiB, with a notice where the budget runs out, each line after
# "KDF-PREFLIGHT-TAIL <run id> <lane> ". The image prints them in its last step, after the results, so BuildKit
# clipping a noisy lanes step never takes a failed lane's reason with it, and an excerpt clipped in turn never takes a
# result. It always exits 0.
set -u
export LC_ALL=C

if [ "${1:-}" = --tails ]; then
	results="$2" id="$3" budget=65536
	outputs="$(dirname "$results")/lanes"
	while read -r lane status; do
		[ "$status" != 0 ] && [ -f "$outputs/$lane.log" ] || continue
		while IFS= read -r line; do
			if [ "$budget" -le 0 ]; then
				printf 'KDF-PREFLIGHT-TAIL %s %s [the excerpts stop here, their 65536 bytes spent]\n' "$id" "$lane" >&2
				exit 0
			fi
			# the whole line counts, its marker too, since BuildKit's limit counts what reaches the log
			line="KDF-PREFLIGHT-TAIL $id $lane $line"
			printf '%s\n' "$line" >&2
			budget=$((budget - ${#line} - 1))
		done < <(tail -n 50 "$outputs/$lane.log" | cut -b 1-300)
	done < "$results"
	exit 0
fi

work="$1" results="$2" limit="$3"
shift 3
# the build's arguments, and the base image's own PYTHON_VERSION and PYTHON_SHA256, which GitHub's runner never sets
# and which a Makefile's PYTHON_VERSION ?= would take, as cicd's took 3.14.7 and looked for python3.14.7
unset RUN_ID LANE_TIMEOUT LANES PYTHON_VERSION PYTHON_SHA256
# the results file and the outputs folder are named from where the script starts, so both are made whole before the
# lanes change folder
case "$results" in /*) ;; *) results="$PWD/$results" ;; esac
outputs="$(dirname "$results")/lanes"
: > "$results"
mkdir -p "$outputs" || exit 0
cd "$work" || exit 0

for lane in "$@"; do
	output="$outputs/$lane.log"
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
	printf '%s %s\n' "$lane" "$status" >> "$results"
done
exit 0
