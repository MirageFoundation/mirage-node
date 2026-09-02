# Signed installer manifests

`network.json` is the signed network/economic policy. Increment `generation`,
update its validity window, and re-sign it whenever peers or policy change:

```bash
conda activate mirage-node
python deploy/release_verify.py sign \
  --manifest release/network.json \
  --privkey .release_signing.pem
```

`manifest.json` must never be written before its image exists. The normal release
path is local: use the existing local GHCR login to build and push the reviewed
commit, resolve its registry digest, and create the unsigned candidate:

```bash
conda activate mirage-node
git diff --quiet && git diff --cached --quiet
python deploy/release_verify.py verify \
  --manifest release/network.json \
  --pubkey deploy/hosttools/pubkey.pem
deploy/deploy.sh --build-only

commit="$(git rev-parse HEAD)"
tag="ghcr.io/miragefoundation/mirage-node:$(git rev-parse --short HEAD)"
digest="$(docker buildx imagetools inspect "$tag" --format '{{json .Manifest}}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["digest"])')"
COMMIT="$commit" DIGEST="$digest" ACTIVATION=upgrade-halt \
UPGRADE_NAME=v1.39.0 CONSENSUS_BREAKING=true python - <<'PY'
import json
import os
from pathlib import Path

version = Path("VERSION").read_text(encoding="utf-8").strip()
major, minor, patch = map(int, version.removeprefix("v").split("."))
release_id = major * 1_000_000 + minor * 1_000 + patch
previous = json.loads(Path("release/manifest.json").read_text(encoding="utf-8"))
if release_id <= int(previous["release_id"]):
    raise SystemExit("release_id must be strictly greater than the published manifest")
activation = os.environ["ACTIVATION"]
upgrade_name = os.environ["UPGRADE_NAME"]
consensus_breaking = os.environ["CONSENSUS_BREAKING"].lower() == "true"
candidate = {
    "version": version,
    "release_id": release_id,
    "commit": os.environ["COMMIT"],
    "image": f"ghcr.io/miragefoundation/mirage-node@{os.environ['DIGEST']}",
    "activation": activation,
    "upgrade_name": upgrade_name,
    "rollback_safe": False,
    "consensus_breaking": consensus_breaking,
}
Path("release-manifest.candidate.json").write_text(
    json.dumps(candidate, indent=2) + "\n", encoding="utf-8"
)
PY

python scripts/finalize_release_manifest.py release-manifest.candidate.json
```

For an ordinary non-consensus release, use `ACTIVATION=ordinary`,
`UPGRADE_NAME=''`, and `CONSENSUS_BREAKING=false`. A blockchain upgrade must pass
the complete `scripts/test_upgrade.sh` rehearsal before release; ordinary
releases run the tests relevant to their changed components.

The finalizer checks the registry digest, image version, required installer and
host-tool files, network manifest/signature, candidate commit, and offline key
signature before atomically writing `release/manifest.json` and
`release/manifest.json.sig`. Commit those two files to dev only after it
succeeds. `/prod-release` then promotes the code and its already-signed digest
manifest and creates the tag once. Nodes install this upgrade-halt release with
`mirage-upgrade`; ordinary releases use `mirage-update`.

The optional `release-candidate` workflow may produce the same unsigned
candidate, but CI availability and package permissions are not release gates.
