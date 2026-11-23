#!/usr/bin/env bash
set -euo pipefail

before=$1
commit=$2
manifest=.release-please-manifest.json

if [[ $before == 0000000000000000000000000000000000000000 ]]; then
  exit 0
fi

changed=$(git diff --name-only "$before" "$commit" -- "$manifest")
if [[ -z $changed ]]; then
  exit 0
fi

version=$(git show "$commit:$manifest" | jq -er '.["."] | strings')
if [[ ! $version =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
  echo 'The Release Please manifest must contain a stable version such as 2.0.0.' >&2
  exit 1
fi

# Adding the manifest establishes the baseline for the first release PR.
if [[ -z $(git ls-tree --name-only "$before" -- "$manifest") ]]; then
  exit 0
fi

previous=$(git show "$before:$manifest" | jq -er '.["."] | strings')
if [[ $version != "$previous" ]]; then
  printf 'tag=v%s\n' "$version"
fi
