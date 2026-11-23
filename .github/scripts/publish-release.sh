#!/usr/bin/env bash
set -euo pipefail

tag=$1
endpoint="repos/$GH_REPO/releases"
release=$(gh api --paginate --slurp "$endpoint?per_page=100" | jq -c --arg tag "$tag" '
  [.[][] | select(.tag_name == $tag)]
  | if length <= 1 then .[0] else error("Multiple releases have the same tag") end
')

if [[ $2 == --lookup ]]; then
  jq -r '.id // empty' <<< "$release"
  exit 0
fi

commit=$2
cd "$3"

arm="onair-${tag}-darwin-arm64.tar.gz"
intel="onair-${tag}-darwin-amd64.tar.gz"
shasum -a 256 "$arm" "$intel" > SHA256SUMS

read_tag() {
  local refs
  refs=$(git ls-remote --tags origin "refs/tags/$tag" "refs/tags/$tag^{}")
  # An annotated tag has a peeled commit in addition to the tag object.
  awk '$2 ~ /\^\{\}$/ { peeled = $1; next } { ref = $1 } END { print (peeled ? peeled : ref) }' <<< "$refs"
}

verify_tag() {
  tag_commit=$(read_tag)
  if [[ -n $tag_commit && $tag_commit != "$commit" ]]; then
    echo "Tag $tag already points to $tag_commit, expected $commit." >&2
    exit 1
  fi
}

verify_tag

if [[ $release == null ]]; then
  echo "Release Please did not create draft release $tag." >&2
  exit 1
elif [[ $(jq -r .draft <<< "$release") == false ]]; then
  if [[ $tag_commit == "$commit" ]]; then
    echo "Release $tag is already published for $commit."
    exit 0
  fi
  echo "Release $tag exists without the expected tag." >&2
  exit 1
fi

if [[ $(jq -r .target_commitish <<< "$release") != "$commit" ]]; then
  echo "Draft release $tag targets a different commit." >&2
  exit 1
fi

for asset in "$arm" "$intel" SHA256SUMS; do
  existing=$(jq -r --arg asset "$asset" '.assets[] | select(.name == $asset) | .digest // "unavailable"' <<< "$release")
  hash=$(shasum -a 256 "$asset")
  if [[ -z $existing ]]; then
    gh release upload "$tag" "$asset"
  elif [[ $existing != "sha256:${hash%% *}" ]]; then
    echo "Draft release $tag already has a different $asset." >&2
    exit 1
  fi
done

verify_tag
release_id=$(jq -er .id <<< "$release")
gh api --method PATCH "$endpoint/$release_id" -F draft=false --jq .html_url
