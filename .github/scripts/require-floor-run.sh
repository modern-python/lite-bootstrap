#!/usr/bin/env bash
set -euo pipefail

WORKFLOW="scheduled.yml"
CANDIDATE_LIMIT=30

tag_sha=$(git rev-parse HEAD)
tag_name=${GITHUB_REF_NAME:-$tag_sha}

# "The most recent run is green" would not have held 1.8.0 back: the newest floors run at that
# moment WAS green, because it predated the commit that broke the floor. So the run has to have
# tested code that already contains this tag, i.e. the tagged commit is an ancestor of (or equal
# to) the commit the floors ran on.
candidate_shas=$(
  gh run list --workflow "$WORKFLOW" --status success --limit "$CANDIDATE_LIMIT" --json headSha --jq '.[].headSha'
)

while read -r candidate_sha; do
  [ -n "$candidate_sha" ] || continue
  # A run dispatched by hand counts as much as a scheduled one; it verifies the same thing. Its
  # commit may not be here yet, and may not be fetchable at all if its branch is gone.
  git cat-file -e "${candidate_sha}^{commit}" 2>/dev/null \
    || git fetch --quiet --no-tags origin "$candidate_sha" 2>/dev/null \
    || continue
  if git merge-base --is-ancestor "$tag_sha" "$candidate_sha"; then
    echo "Dependency floors verified by $WORKFLOW at $candidate_sha, which contains $tag_sha."
    exit 0
  fi
done <<< "$candidate_shas"

cat >&2 <<MSG
::error::No successful $WORKFLOW run has tested the code in $tag_name, so the declared dependency
floors are unverified. Checked the last $CANDIDATE_LIMIT successful runs. Nothing was published.

Run the floors against this commit, then re-push the tag once they are green:

  gh workflow run $WORKFLOW --ref $tag_sha
  gh run watch "\$(gh run list --workflow $WORKFLOW --limit 1 --json databaseId --jq '.[0].databaseId')" --exit-status
  git push --delete origin $tag_name && git push origin $tag_name
MSG
exit 1
