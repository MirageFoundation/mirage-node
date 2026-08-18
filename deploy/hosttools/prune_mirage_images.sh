#!/usr/bin/env bash
# Delete unreferenced ghcr.io/miragefoundation/mirage-node images except
# active, staged, previous, and any forensic/recovery tags.
set -euo pipefail

STATE_FILE=/var/lib/mirage/update/state.json
keep=()
if [[ -f "$STATE_FILE" ]]; then
  while IFS= read -r d; do
    [[ -n "$d" ]] && keep+=("$d")
  done < <(python3 -c 'import json,sys
s=json.load(open(sys.argv[1]))
for k in ("active","staged","previous"):
    v=s.get(k) or ""
    if v: print(v)
' "$STATE_FILE")
fi

running=$(docker inspect mirage --format '{{.Image}}' 2>/dev/null || true)
[[ -n "$running" ]] && keep+=("$running")

is_kept() {
  local img="$1"
  local k
  for k in "${keep[@]}"; do
    [[ -z "$k" ]] && continue
    if [[ "$img" == *"$k"* || "$k" == *"$img"* ]]; then
      return 0
    fi
  done
  return 1
}

while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  id=${line%% *}
  ref=${line#* }
  if [[ "$ref" == *forensic* || "$ref" == *recovery* || "$ref" == *divergence* ]]; then
    continue
  fi
  if is_kept "$ref" || is_kept "$id"; then
    continue
  fi
  echo "removing $ref $id"
  docker rmi "$id" >/dev/null || true
done < <(docker images --format '{{.ID}} {{.Repository}}:{{.Tag}}' | grep -E 'miragefoundation/mirage-node|mirage:local' || true)
