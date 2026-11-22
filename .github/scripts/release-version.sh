#!/usr/bin/env bash
set -euo pipefail

before=$1
commit=$2

# A branch creation event has no previous commit to compare.
if [[ $before != 0000000000000000000000000000000000000000 ]]; then
  changed=$(git diff --name-only "$before" "$commit" -- VERSION)
  if [[ -z $changed ]]; then
    exit 0
  fi
fi

tag=$(git show "$commit:VERSION")
if [[ ! $tag =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
  echo 'VERSION must contain a stable version such as v2.0.0.' >&2
  exit 1
fi

printf 'tag=%s\n' "$tag"
