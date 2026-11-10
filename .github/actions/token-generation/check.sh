#!/usr/bin/env bash
# The deployment token's generation compare (the secrets fence, step 10, ADR D-100). Reads TOKEN, the job's own
# VERCEL_DEPLOYMENT_TOKEN, LOCAL, its environment's VERCEL_TOKEN_GENERATION, `G<n>:<16 hex>`, and EXPECTED, the
# generation the verifier was told, empty for a deploy. Prints one line and never fails, since the deploy's own call
# to Vercel proves the token works. It prints no for a missing or malformed variable or a token whose fingerprint
# differs, and stale when the local pair matches but is not the expected generation, so an older pair is never
# reported as the expected one. The fingerprint is the first 16 hex digits of the SHA256 of the trimmed token.
set -u

token="$(printf '%s' "${TOKEN:-}" | tr -d '[:space:]')"
local_value="$(printf '%s' "${LOCAL:-}" | tr -d '[:space:]')"
expected="$(printf '%s' "${EXPECTED:-}" | tr -d '[:space:]')"

generation=none
want=
if [[ "$local_value" =~ ^(G[1-9][0-9]*):([0-9a-f]{16})$ ]]; then
  generation="${BASH_REMATCH[1]}"
  want="${BASH_REMATCH[2]}"
fi

result=no
if [ -n "$want" ] && [ -n "$token" ]; then
  have="$(printf '%s' "$token" | sha256sum | cut -c 1-16)"
  if [ "$have" = "$want" ]; then
    result=yes
  fi
fi

if [ -z "$expected" ]; then
  echo "token generation=$generation result=$result"
  exit 0
fi

if ! [[ "$expected" =~ ^G[1-9][0-9]*$ ]]; then
  echo "token generation=$generation expected=invalid result=no"
  exit 0
fi

if [ "$result" = yes ] && [ "$generation" != "$expected" ]; then
  result=stale
fi
echo "token generation=$generation expected=$expected result=$result"
