# Security Policy

## Reporting a vulnerability

If you believe you have found a security vulnerability in this repository:

- Prefer using the platform's private reporting mechanism (e.g., GitHub Security Advisories) if available.
- If private reporting is not available, open an issue **without** including exploit details, secrets, or sensitive logs. Provide a high-level description and we will follow up.

## Secrets policy (critical)

This project must **never** commit or publish:

- Wallet mnemonics / seed phrases / recovery phrases
- Private keys (validator keys, node keys, SSH keys, TLS keys/certs)
- API tokens (Cloudflare, OpenAI/ChatGPT, etc.)
- Database passwords / connection URLs containing credentials

Notes:

- `.env` files in the repo root are gitignored. Template defaults live in `deploy/templates/env/*.env`.
- For a quick local check, run a secret scanner from the repo root, for example:
  - `gitleaks detect --no-git --source .`

## Trusting the installer

The first fetch of `deploy/install.sh` is trust-on-first-use over TLS from GitHub (`prod` branch), the same model as Electrum. The script cannot verify itself.

Canonical origin:

```
https://raw.githubusercontent.com/MirageFoundation/mirage-node/prod/deploy/install.sh
```

The long-lived offline Ed25519 public key lives in `deploy/hosttools/pubkey.pem` and is inlined in `install.sh`. Fingerprint of the raw 32-byte key:

```
679a39294dc9639170ca9cb4010c44cc71dd153fa2029f2e73969bff6d86c0a8
```

Confirm a checkout with:

```
openssl pkey -pubin -in deploy/hosttools/pubkey.pem -outform DER | tail -c 32 | od -An -v -tx1 | tr -d ' \n'
```

`mirage-verify` must succeed with only this key (no Fulcio/Rekor). Sigstore signatures from GitHub Actions are extra, not required to install.

The key the installer embeds is the anchor for the life of the host. The release image ships a copy so verification works inside the container, but `install.sh` refuses an image whose copy differs, and neither the installer nor `mirage-update` will verify against a key that came out of an image. Signed network manifests carry `issued_at` / `expires_at` and a monotonic `generation`; an expired manifest is rejected even with a valid signature, and the updater refuses a generation older than the one it last accepted, so an old manifest cannot be replayed to pin a node to dead peers.

A node that has already verified a release serves `install.sh`, its hash-pinned bootstrap helpers, and both signed manifests under `/.well-known/mirage/`. Set `MIRAGE_MANIFEST_MIRROR` to that directory when piping the mirrored installer so every fetch uses the same origin. Origin choice is availability; the embedded key, helper hashes, and manifest signatures provide integrity. For a mirror copy, check the installer SHA-256 published in the release notes with `echo "<hash>  install.sh" | sha256sum -c -`. Do not eyeball hex.

## Operator identity on the host

`install.sh` imports the operator's existing 12-word account seed into `keyring-backend test` on the host so the node can pay fees and self-delegate. Compromise of the host is compromise of that account. This is an accepted operator risk, recorded in `docs/security/open-items.md`.


