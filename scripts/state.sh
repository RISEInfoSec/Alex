#!/usr/bin/env bash
# Pipeline working state lives on the `pipeline-state` branch, not main.
#
# The intermediate CSVs below are rewritten wholesale every run and grew past
# GitHub's 100 MiB per-file limit in 2026-07, which blocked every push. They
# are stored gzipped as a single parentless commit that each push replaces,
# so their history stays bounded; the state being replaced is kept at
# `pipeline-state-prev` for a one-step rollback.
#
#   scripts/state.sh pull            fetch state into data/ (fails if missing)
#   scripts/state.sh push "message"  publish data/ state (no-op if unchanged)
#
# Rollback: git push -f origin origin/pipeline-state-prev:refs/heads/pipeline-state
set -euo pipefail

BRANCH="${STATE_BRANCH:-pipeline-state}"
REMOTE="${STATE_REMOTE:-origin}"
FILES=(
  discovery_candidates.csv
  quality_metrics.csv
  rejected_candidates.csv
  accepted_candidates.csv
  rescore_metrics.csv
)

cd "$(git rev-parse --show-toplevel)"
BASE_FILE="$(git rev-parse --git-dir)/alex-state-base"

pull() {
  local rc=0
  git ls-remote --exit-code --heads "$REMOTE" "$BRANCH" >/dev/null || rc=$?
  if [ "$rc" -eq 2 ]; then
    # A missing branch must not read as "empty state": discover would start
    # from zero and the next push would overwrite the real corpus history.
    echo "state: $REMOTE/$BRANCH does not exist; seed it with 'scripts/state.sh push'" >&2
    exit 1
  elif [ "$rc" -ne 0 ]; then
    exit "$rc"
  fi
  git fetch --quiet --depth=1 "$REMOTE" "refs/heads/$BRANCH"
  local base
  base="$(git rev-parse FETCH_HEAD)"
  mkdir -p data
  for f in "${FILES[@]}"; do
    if git cat-file -e "$base:$f.gz" 2>/dev/null; then
      git cat-file blob "$base:$f.gz" | gunzip > "data/$f"
    fi
  done
  echo "$base" > "$BASE_FILE"
  echo "state: pulled $BRANCH@${base:0:7}"
}

push() {
  local msg="${1:-Update pipeline state}" base="" tmp tree commit
  [ -f "$BASE_FILE" ] && base="$(cat "$BASE_FILE")"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  export GIT_INDEX_FILE="$tmp/index"
  # Start from the pulled tree so a file this job never produced is carried
  # over rather than dropped.
  if [ -n "$base" ]; then git read-tree "$base"; else git read-tree --empty; fi
  for f in "${FILES[@]}"; do
    [ -f "data/$f" ] || continue
    gzip -n -c "data/$f" > "$tmp/$f.gz"  # -n: no timestamp, so unchanged => same blob
    git update-index --add --cacheinfo "100644,$(git hash-object -w "$tmp/$f.gz"),$f.gz"
  done
  tree="$(git write-tree)"
  unset GIT_INDEX_FILE
  if [ -n "$base" ] && [ "$(git rev-parse "$base^{tree}")" = "$tree" ]; then
    echo "state: unchanged"
    return
  fi
  commit="$(git commit-tree "$tree" -m "$msg")"
  # --force-with-lease against the pulled commit: a concurrent writer makes
  # this fail instead of being silently overwritten. Empty lease = "must not
  # exist yet" (first seed).
  local refs=("$commit:refs/heads/$BRANCH")
  [ -n "$base" ] && refs+=("+$base:refs/heads/$BRANCH-prev")
  git push --quiet --atomic --force-with-lease="refs/heads/$BRANCH:$base" "$REMOTE" "${refs[@]}"
  echo "$commit" > "$BASE_FILE"
  echo "state: pushed $BRANCH@${commit:0:7} ($msg)"
}

case "${1:-}" in
  pull) pull ;;
  push) push "${2:-}" ;;
  *) echo "usage: $0 pull | push \"message\"" >&2; exit 2 ;;
esac
