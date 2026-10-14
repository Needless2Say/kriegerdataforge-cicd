#!/usr/bin/env bash
# lanes.sh, the Linux pre-flight's lane runner (D-072), run by the image's lanes stage alone, never by hand.
#
#   bash lanes.sh <results file> <seconds a lane may take> <lane>...
#
# Runs each lane named in the commit's tree at /home/runner/work, in the order given, each under timeout, and appends
# "<lane> <status>" to the results file, 124 for a lane that ran out of time. A lane is a make target, or actionlint,
# the image's actionlint over the repo's workflows. It always exits 0, so a red lane never stops the ones after it and
# the build goes on to the step that prints the results, which kdf-preflight.sh reads. The build's arguments are
# dropped before a lane starts, so no lane can print a result line with this run's id.
set -u

results="$1" limit="$2"
shift 2
unset RUN_ID LANE_TIMEOUT LANES
: > "$results"
cd /home/runner/work || exit 0

for lane in "$@"; do
	printf '\n==== kdf-preflight lane %s ====\n' "$lane"
	if [ "$lane" = actionlint ]; then
		timeout --kill-after=10 "$limit" actionlint
	else
		timeout --kill-after=10 "$limit" make "$lane"
	fi
	status=$?
	printf '==== kdf-preflight lane %s exited %s ====\n' "$lane" "$status"
	printf '%s %s\n' "$lane" "$status" >> "$results"
done
exit 0
