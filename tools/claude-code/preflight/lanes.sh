#!/usr/bin/env bash
# lanes.sh, the Linux pre-flight's lane runner (D-072), run by the image's lanes stage alone, never by hand.
#
#   bash lanes.sh <work folder> <results file> <seconds a lane may take> <lane>...
#
# Runs each lane named in the commit's tree in the work folder, in the order given, each under timeout, and appends
# "<lane> <status>" to the results file, 124 for a lane that ran out of time. A lane is a make target, or actionlint,
# the image's actionlint over the repo's workflows, which is red, 127, when no shellcheck is on the PATH, since
# actionlint then skips every run: script. It always exits 0, so a red lane never stops the ones after it and
# the build goes on to the step that prints the results, which kdf-preflight.sh reads. The build's arguments are
# dropped before a lane starts, so no lane can print a result line with this run's id, and so are the base image's
# own Python variables, which GitHub's runner does not have.
set -u

work="$1" results="$2" limit="$3"
shift 3
# the build's arguments, and the base image's own PYTHON_VERSION and PYTHON_SHA256, which GitHub's runner never sets
# and which a Makefile's PYTHON_VERSION ?= would take, as cicd's took 3.14.7 and looked for python3.14.7
unset RUN_ID LANE_TIMEOUT LANES PYTHON_VERSION PYTHON_SHA256
# the results file is named from where the script starts, so it is made whole before the lanes change folder
case "$results" in /*) ;; *) results="$PWD/$results" ;; esac
: > "$results"
cd "$work" || exit 0

for lane in "$@"; do
	printf '\n==== kdf-preflight lane %s ====\n' "$lane"
	if [ "$lane" = actionlint ] && ! command -v shellcheck >/dev/null 2>&1; then
		# actionlint skips every run: script without ShellCheck, so a lane that passed here would hide what CI's lint
		# job finds (Round Table 29)
		printf 'kdf-preflight: no shellcheck on the PATH, so the actionlint lane does not run\n'
		(exit 127)
	elif [ "$lane" = actionlint ]; then
		timeout --kill-after=10 "$limit" actionlint
	else
		timeout --kill-after=10 "$limit" make "$lane"
	fi
	status=$?
	printf '==== kdf-preflight lane %s exited %s ====\n' "$lane" "$status"
	printf '%s %s\n' "$lane" "$status" >> "$results"
done
exit 0
