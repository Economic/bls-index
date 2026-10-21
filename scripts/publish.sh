#!/usr/bin/env bash
# Publish a built catalog as a GitHub Release (design.md, "Publication").
#
#   scripts/publish.sh RUN_DIR TAG TARGET_SHA REPO
#
# RUN_DIR holds bls_index.parquet and latest.json. A TAG starting with "test-" makes a
# prerelease that never becomes "latest". The release stays a draft, invisible to
# clients, until GitHub's SHA-256 digests of both uploaded files match the local files.
set -euo pipefail

run_dir=$1 tag=$2 target=$3 repo=$4
keep=12
files=(bls_index.parquet latest.json)
test_run=false
[[ $tag == test-* ]] && test_run=true

releases() { gh api "repos/$repo/releases?per_page=100"; }

delete_release() { # id tag; returns nonzero if the release could not be deleted
  gh api -X DELETE "repos/$repo/releases/$1" >/dev/null || return 1
  gh api -X DELETE "repos/$repo/git/refs/tags/$2" >/dev/null 2>&1 || true # drafts have no tag
}

release_id() { releases | jq -r --arg tag "$tag" '.[] | select(.tag_name == $tag) | .id'; }

# 1. Leftovers from earlier runs: our own drafts, and test prereleases.
releases | jq -r '.[] | select((.tag_name | test("^(catalog|test)-"))
                              and (.draft or (.tag_name | startswith("test-"))))
                       | "\(.id) \(.tag_name)"' |
  while read -r id old; do
    echo "Deleting leftover release $old"
    delete_release "$id" "$old" || echo "::warning::Could not delete leftover release $old"
  done

# 2. A draft with both files.
args=(--repo "$repo" --draft --target "$target" --title "$tag"
      --notes "BLS series catalog built $(jq -r .built_at "$run_dir/latest.json").")
$test_run && args+=(--prerelease)
gh release create "$tag" "${args[@]}" "${files[@]/#/$run_dir/}" >/dev/null
id=$(release_id)
[[ -n $id ]] || { echo "Draft release $tag not found after upload" >&2; exit 1; }

# 3. GitHub's digests and sizes must match the local files.
for name in "${files[@]}"; do
  expected="$(stat -c %s "$run_dir/$name") sha256:$(sha256sum "$run_dir/$name" | cut -d' ' -f1)"
  actual=$(releases | jq -r --arg tag "$tag" --arg name "$name" \
    '.[] | select(.tag_name == $tag) | .assets[] | select(.name == $name) | "\(.size) \(.digest)"')
  if [[ $actual != "$expected" ]]; then
    echo "Uploaded $name does not match the local file (expected $expected, got ${actual:-nothing}); deleting the draft" >&2
    delete_release "$id" "$tag"
    exit 1
  fi
done

# 4. Publish the draft; a real run also becomes the latest release.
latest=true
$test_run && latest=false
if ! gh api -X PATCH "repos/$repo/releases/$id" -F draft=false -f make_latest="$latest" >/dev/null; then
  draft=$(gh api "repos/$repo/releases/$id" --jq .draft 2>/dev/null || echo unknown)
  newest=$(gh api "repos/$repo/releases/latest" --jq .tag_name 2>/dev/null || echo unknown)
  if [[ $draft != false ]] || { ! $test_run && [[ $newest != "$tag" ]]; }; then
    echo "Publishing $tag failed; deleting the draft" >&2
    delete_release "$id" "$tag"
    exit 1
  fi
  echo "The publish response was lost, but $tag is published"
fi
echo "Published $tag"

# 5. Keep the newest catalog releases. A failed deletion only warns: the catalog is
#    already published, and the next publish tries again. Sort by tag, which holds the
#    build time: GitHub's created_at is the target commit's date, which weekly releases
#    from an unchanged commit share.
$test_run && exit 0
releases | jq -r '[.[] | select((.tag_name | startswith("catalog-")) and (.draft | not))]
                  | sort_by(.tag_name) | reverse | .['"$keep"':][] | "\(.id) \(.tag_name)"' |
  while read -r id old; do
    echo "Deleting old release $old"
    delete_release "$id" "$old" || echo "::warning::Could not delete old release $old"
  done
