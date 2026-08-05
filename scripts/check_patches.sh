#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BC="$ROOT/blockchain"
PATCHES_MD="$BC/patches/PATCHES.md"
GO="${GO:-go}"

[[ -f "$PATCHES_MD" ]] || { echo "FATAL: missing $PATCHES_MD" >&2; exit 1; }
command -v "$GO" >/dev/null 2>&1 || { echo "FATAL: Go toolchain not found: $GO" >&2; exit 1; }

for pin in \
  45196a8322a03bf2ef3888e314e24f2b3bcb49bb \
  f45bfa5c9d80112a0bd55c9a671ca0759941f7b9
do
  if ! grep -q "$pin" "$PATCHES_MD"; then
    echo "FATAL: PATCHES.md is missing upstream commit $pin" >&2
    exit 1
  fi
done

module_dir() {
  "$GO" mod download -json "$1" | python3 -c \
    'import json, sys; data = json.load(sys.stdin); print(data["Dir"])'
}

check_fork() {
  local name="$1"
  local upstream="$2"
  local fork="$3"
  shift 3
  local -a allowed=("$@")
  local file rel upstream_file permitted

  shopt -s globstar nullglob
  for file in "$fork"/**; do
    [[ -f "$file" ]] || continue
    rel="${file#"$fork"/}"
    permitted=0
    for allowed_rel in "${allowed[@]}"; do
      if [[ "$rel" == "$allowed_rel" ]]; then
        permitted=1
        break
      fi
    done
    if [[ "$permitted" -eq 1 ]]; then
      continue
    fi
    upstream_file="$upstream/$rel"
    if [[ ! -f "$upstream_file" ]]; then
      echo "FATAL: $name has undocumented added file: $rel" >&2
      exit 1
    fi
    if ! cmp -s "$upstream_file" "$file"; then
      echo "FATAL: $name has undocumented change: $rel" >&2
      exit 1
    fi
  done
  for file in "$upstream"/**/*.go; do
    [[ -f "$file" ]] || continue
    rel="${file#"$upstream"/}"
    [[ "$rel" == *_test.go ]] && continue
    [[ "$rel" == cmd/* || "$rel" == benchmarks/* ]] && continue
    if [[ ! -f "$fork/$rel" ]]; then
      echo "FATAL: $name is missing upstream production file: $rel" >&2
      exit 1
    fi
  done
  shopt -u globstar nullglob
  echo "$name provenance diff OK"
}

IAVL_UPSTREAM="$(module_dir github.com/cosmos/iavl@v1.2.8)"
STORE_UPSTREAM="$(module_dir github.com/cosmos/cosmos-sdk/store/v2@v2.0.0)"

check_fork \
  "iavl" \
  "$IAVL_UPSTREAM" \
  "$BC/patches/iavl" \
  immutable_tree.go \
  mutable_tree.go \
  nodedb.go \
  consensus_fatal.go \
  consensus_fatal_test.go \
  fastnode_import_test.go \
  nodedb_prune_fail_fast_test.go

check_fork \
  "cosmos-sdk-store-v2" \
  "$STORE_UPSTREAM" \
  "$BC/patches/cosmos-sdk-store-v2" \
  go.mod \
  go.sum \
  rootmulti/store.go \
  rootmulti/commit_info_prune_test.go

echo "Consensus patch provenance verified"
