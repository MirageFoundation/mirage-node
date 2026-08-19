#!/usr/bin/env bash
# Delete unreferenced ghcr.io/miragefoundation/mirage-node images except
# active, staged, previous, and any forensic/recovery tags.
set -euo pipefail

STATE_FILE=/var/lib/mirage/update/state.json
PREPARED_FILE="${HOME:-/root}/.mirage/upgrade/prepared.json"
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

# The image armed for a governed halt is referenced only by prepared.json, not by
# state.json. Deleting it makes the halt unrecoverable without a manual pull: the
# activator refuses to launch a digest it cannot find locally.
if [[ -f "$PREPARED_FILE" ]]; then
  prepared_image=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("image") or "")' "$PREPARED_FILE")
  [[ -n "$prepared_image" ]] && keep+=("$prepared_image")
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
