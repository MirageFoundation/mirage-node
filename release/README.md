# Signed installer manifests

`network.json` is the signed network/economic policy. Increment `generation`,
update its validity window, and re-sign it whenever peers or policy change:

```bash
conda activate mirage-node
python deploy/release_verify.py sign \
  --manifest release/network.json \
  --privkey .release_signing.pem
```

`manifest.json` must never be written before its image exists. Manually run the
release-candidate workflow on the reviewed dev commit. It pushes a digest-pinned
candidate, signs the image with Sigstore, and uploads
`release-manifest.candidate.json`. Download that artifact while `HEAD` is still
the commit it names, then run:

```bash
conda activate mirage-node
python scripts/finalize_release_manifest.py release-manifest.candidate.json
```

The finalizer checks the registry digest, image version, required installer and
host-tool files, network manifest/signature, candidate commit, and offline key
signature before atomically writing `release/manifest.json` and
`release/manifest.json.sig`. Commit those two files to dev only after this
succeeds. The normal `/prod` release then merges the code and its already-signed
digest manifest together and creates the tag once.
