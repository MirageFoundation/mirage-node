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

# Upstream paths the vendored modules deliberately do not carry: documentation,
# CI configuration, editor settings and test fixtures, none of which are linked
# by Mirage.
#
# LICENSE is deliberately NOT in this list. Both forks are redistributed in a
# public repository under Apache-2.0, so a missing licence file is a compliance
# gap rather than a tidiness one, and this check is what catches it.
INTENTIONALLY_OMITTED=(
  'docs/*'
  '.github/*'
  '.vscode/*'
  'testdata/*'
  '*.md'
  '*.yml'
  '*.yaml'
  '.gitignore'
  '.golangci.yml'
  'Makefile'
  'POEM'
  'mockgen.sh'
)

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

  # dotglob: without it a dot-prefixed file added anywhere inside either fork is
  # invisible to the whole scan below.
  shopt -s globstar nullglob dotglob
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
  # Every upstream file, not just *.go. Restricting this loop to Go source is how
  # the absent iavl LICENSE went unnoticed — an Apache-2.0 redistribution gap in
  # a public repository, which no amount of Go-only checking would ever surface.
  for file in "$upstream"/**; do
    [[ -f "$file" ]] || continue
    rel="${file#"$upstream"/}"
    [[ "$rel" == *_test.go ]] && continue
    [[ "$rel" == cmd/* || "$rel" == benchmarks/* ]] && continue
    for skipped_rel in "${INTENTIONALLY_OMITTED[@]}"; do
      if [[ "$rel" == $skipped_rel ]]; then
        continue 2
      fi
    done
    if [[ ! -f "$fork/$rel" ]]; then
      echo "FATAL: $name is missing upstream file: $rel" >&2
      exit 1
    fi
  done
  shopt -u globstar nullglob dotglob
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
  iterator.go \
  import.go \
  batch.go \
  consensus_fatal.go \
  consensus_fatal_test.go \
  batch_flush_error_test.go \
  fastnode_import_test.go \
  nodedb_prune_fail_fast_test.go

check_fork \
  "cosmos-sdk-store-v2" \
  "$STORE_UPSTREAM" \
  "$BC/patches/cosmos-sdk-store-v2" \
  go.mod \
  go.sum \
  rootmulti/store.go \
  rootmulti/commit_info_prune_test.go \
  cachekv/internal/mergeiterator.go \
  iavl/store.go

echo "Consensus patch provenance verified"
