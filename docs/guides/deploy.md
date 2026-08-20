# Deploying a Mirage Node

Anyone with an Ubuntu 24.04 VM and an SSH key can run a validator. The installer is provider-agnostic: a real VM (KVM, Xen, Hyper-V, VMware, or bare metal), not LXC or OpenVZ.

## What you need

1. An account on [mirage.talk](https://mirage.talk) with a username.
2. **10,000,000 MIRAGE** on that account (5,000,000 will be self-delegated; 5,000,000 stays liquid; staking later keeps at least 1,000,000 liquid for fees).
3. An Ubuntu 24.04 LTS VM on **amd64**, sold as at least a 4 GB RAM / 2 vCPU plan (at least 3800 MiB visible inside Ubuntu, since providers reserve some) with at least 20 GiB free disk, and your SSH public key in `/root/.ssh/authorized_keys`. Released images are amd64 only for now, so the installer refuses arm64 rather than failing later at the image pull.

   Those are the numbers the live validators actually run on: a 4 GB / 2 vCPU plan reporting 3915 MiB, the node process at ~1.3 GiB, and ~15 GiB of disk used in total including Ubuntu. 40 GiB of disk is worth paying for because logs and the indexer add a few GiB a month, and the installer warns below that, but it will not block you.
4. The **12-word** recovery phrase for that funded account.

The installer imports that phrase into `keyring-backend test` on the host. Anyone who roots the box can take over the account. That is an accepted operator risk; see [`docs/security/open-items.md`](../security/open-items.md).

## Install

```bash
ssh root@YOUR_IP
curl -fsSL https://raw.githubusercontent.com/MirageFoundation/mirage-node/prod/deploy/install.sh | bash
# optional: bash -s -- --domain example.com
```

The installer updates Ubuntu, applies a noninteractive full upgrade, and installs the host baseline before starting Mirage. If Ubuntu requires a reboot, the installer stops before launching the node; reboot and run the same command again to resume.

The 12-word mnemonic, pasted on one line with a space between each word, is the only thing the installer asks for. Everything else takes the default that suits a new public node, and the install prints each decision as it makes it:

| Setting | Default | Environment variable | What it sets |
| --- | --- | --- | --- |
| Validator name | your username | `MIRAGE_MONIKER` | `MONIKER`, recorded on-chain when the node registers |
| Domain | none | `MIRAGE_DOMAIN` | `DOMAIN`; HTTPS is requested at startup |
| Media uploads | off | `MIRAGE_MEDIA_UPLOADS` | `MEDIA_UPLOADS_ENABLED` |

Set any of those variables to install with a different answer; an empty value is a real answer. Add a domain later with `mirage-domain --set example.com`, which requests the certificate and binds the name. Turn uploads on only if a scanning edge fronts this node, because uploads are stored on its disk and nothing else inspects them.

Nodes installed this way recover from a divergence on their own (`WATCHDOG_AUTORECOVER=true`), which suits an operator who is not watching at 04:00. The diverged state is snapshotted before recovery touches anything either way.

The node comes up on HTTP at `http://YOUR_IP` immediately. It state-syncs, then registers itself as a validator. Do not run create-validator by hand.

If GitHub is unreachable, any already-running node serves the script, its hash-pinned bootstrap helpers, and signed manifests. Use one node consistently:

```bash
MIRROR=https://<that-node>/.well-known/mirage
curl -fsSL "$MIRROR/install.sh" | MIRAGE_MANIFEST_MIRROR="$MIRROR" bash
```

Integrity is the embedded signing key and bootstrap hashes, not the mirror origin. The public key fingerprint is `679a39294dc9639170ca9cb4010c44cc71dd153fa2029f2e73969bff6d86c0a8` (raw Ed25519, SHA-256 of `deploy/hosttools/pubkey.pem`'s raw key). Confirm it with:

```
openssl pkey -pubin -in deploy/hosttools/pubkey.pem -outform DER | tail -c 32 | od -An -v -tx1 | tr -d ' \n'
```

Do not eyeball a downloaded script. For a node-served copy, check it against GitHub with `sha256sum -c`. See [`SECURITY.md`](../../SECURITY.md).

### HTTPS later

Point an A/AAAA record at the VM, then:

```bash
mirage-domain --set example.com
```

Wallet features that need a secure origin wait until this step.

### Day-to-day

```bash
mirage-status                  # live dashboard, Ctrl+C exits
mirage-status --once           # one snapshot
mirage-status --json           # machine-readable health
mirage-update                  # activate a staged ordinary release
mirage-update --prepare        # verify, pull and arm a governed halt
mirage-update --status         # active/staged/prepared, no changes
mirage-update --rollback       # only when the signed release permits rollback
mirage-backup                  # online backup; copy the archive off-server
mirage-restore BACKUP          # restore local data; miraged keeps signing
mirage-logs                    # follow service logs
mirage-restart                 # whole-container restart when it is safe
docker logs -f mirage          # container stdout (bootstrap / supervisord)
# persistent logs: ~/.mirage/logs/{node,indexer,backend,caddy,postgres,supervisor,deploy}/

# Only when this node's own tooling is too old to accept the current manifest:
# it rejects every release and cannot update its way out. The digest comes from
# release/manifest.json, and an image whose signing key differs from this host's
# trust anchor is refused.
mirage-update --refresh-hosttools --image ghcr.io/miragefoundation/mirage-node@sha256:...
```

The node never fetches or stages a release automatically. Run `mirage-update` to verify, pull and activate an ordinary release. Before submitting a software-upgrade proposal, run `mirage-update --prepare` to verify its signed release, pull the digest and record the upgrade name. Only the local halt activator is automatic: it cannot fetch anything, and it recreates the container only from that prepared digest after the node writes a halt marker with the same name and the governed height. A release is refused if the network manifest went backwards a generation, or if an ordinary activation is attempted within 500 blocks of a governance halt. Being several releases behind is not a reason for refusal: the new image applies every deploy migration the node has not run yet, so a node that missed updates catches up in one step. Rollback is available only when the active signed manifest explicitly marks it safe and the release is not consensus-breaking.

If this seed is already a validator on a machine that is gone for good, the installer asks you to type exactly `replace`. That writes a signing watermark above the live chain height so the new host cannot double-sign. The old VM must never be started again. Replacement discards local indexer, backend, and media history; `mirage-backup` is the way to keep that data, and it does not take the validator down.

Archives from `mirage-backup` are secret operational material. Keep a copy off the server.

## What the installer will refuse

- Ubuntu other than 24.04, or any architecture other than amd64
- Container virtualization (LXC, OpenVZ, Docker-in-Docker)
- No SSH public key in `/root/.ssh/authorized_keys` (it will not disable password auth and lock you out)
- A mnemonic that is not exactly 12 BIP-39 English words
- An account with no username, or with less than 10,000,000 MIRAGE (it prints the actual balance)
- A seed whose consensus key is already a validator on another host, unless you type exactly `replace` after the old machine is permanently gone

- A network manifest with no persistent peers, an expired one, or a signature that does not match the pinned key
- A release older than the network manifest's `min_release`
- A pulled image whose `RepoDigest` does not match the signed manifest
- An image carrying a different release signing key than the one embedded in the installer

The installer also gives each host its own weekly container-restart and OS-upgrade windows, derived from the machine ID, so a public fleet does not reboot in lockstep.

Re-running the installer on the same host with the same seed is idempotent: existing key files are left untouched.

## Existing operators

Laptop-driven deploys (`deploy/deploy.sh root@host --init`) still work for the current fleet. New nodes should use `install.sh`. `deploy.sh` no longer installs `docker.io` as a fallback and no longer asks for a consensus derivation index (always 0).

Host baseline details remain in [`server_setup.md`](server_setup.md).

### State-sync and history

Nodes retain roughly a week of blocks, and genesis begins at height 2096156, so there is no one left to serve the millions of blocks in between. A new node state-syncs to a recent snapshot. The indexer starts at the snapshot height and records the blocks before it as a permanent gap (`history_complete: false`). That is accurate rather than broken.

## Need help?

Join the conversation on [mirage.talk/t/mirage](https://mirage.talk/t/mirage).
