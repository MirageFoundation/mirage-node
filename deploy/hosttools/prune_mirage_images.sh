#!/usr/bin/env bash
# Delete unreferenced ghcr.io/miragefoundation/mirage-node images except
# active, staged, previous, and any forensic/recovery tags.
set -euo pipefail

STATE_FILE="${MIRAGE_UPDATE_STATE_FILE:-/var/lib/mirage/update/state.json}"
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

# Walk every image, tagged or not, and judge each one against `keep` above.
#
# Both deploy.sh and mirage-update fetch releases by digest, and a digest pull
# leaves the image with an empty RepoTags. So a sweep that reads only
# {{.Repository}}:{{.Tag}} matched no release image at all, which is why nothing
# was ever reclaimed. `docker image prune` is not the answer either: Docker calls
# any untagged image dangling, so on these hosts that means every release image,
# and prune does not consult `keep`. It would delete the rollback target, a
# release staged but not yet activated, and the image armed for a governed halt
# -- the last of which strands the upgrade, because the activator refuses a
# digest it cannot find locally.
#
# Matching on RepoDigests instead of tags identifies the release an image
# actually is, which is the same form `keep` holds.
while IFS= read -r id; do
  [[ -z "$id" ]] && continue
  tags=$(docker image inspect "$id" --format '{{join .RepoTags " "}}' 2>/dev/null || true)
  digests=$(docker image inspect "$id" --format '{{join .RepoDigests " "}}' 2>/dev/null || true)
  refs="$tags $digests"

  if [[ "$refs" == *forensic* || "$refs" == *recovery* || "$refs" == *divergence* ]]; then
    continue
  fi

  if [[ "$refs" == *miragefoundation/mirage-node* || "$refs" == *mirage:local* ]]; then
    :
  elif [[ -z "${tags// /}" && -z "${digests// /}" ]]; then
    # No tag and no digest: the remains of an interrupted or superseded pull,
    # attributable to nothing and reclaimable by no other rule. On val1 these
    # were 3.4 GiB of the disk that filled mid-pull and stopped the validator.
    :
  else
    continue
  fi

  kept=0
  if is_kept "$id"; then
    kept=1
  else
    for ref in $refs; do
      if is_kept "$ref"; then
        kept=1
        break
      fi
    done
  fi
  if [[ "$kept" -eq 1 ]]; then
    continue
  fi

  label=$(echo $refs)
  echo "removing ${label:-<untagged>} $id"
  docker rmi "$id" >/dev/null 2>&1 || true
done < <(docker images -a --no-trunc --format '{{.ID}}')
