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
```

The installer updates Ubuntu, applies a noninteractive full upgrade, and installs the host baseline before starting Mirage. If Ubuntu requires a reboot, the installer stops before launching the node; reboot and run the same command again to resume.

When prompted, paste the 12-word mnemonic on one line with a space between each word. The installer then asks three questions, all of them before it does anything slow:

| Question | Default | What it sets |
| --- | --- | --- |
| Your validator's public name | your username | `MONIKER`, recorded on-chain when the node registers |
| A domain for this node | none | `DOMAIN`; HTTPS is requested at startup |
| Accept media uploads | no | `MEDIA_UPLOADS_ENABLED` |

Answer any of them up front with `MIRAGE_MONIKER`, `MIRAGE_DOMAIN` or `MIRAGE_MEDIA_UPLOADS`; a variable that is set is never asked about, and an empty value is a real answer. Say yes to uploads only if a scanning edge fronts this node, because uploads are stored on its disk and nothing else inspects them.

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
mirage-domain example.com
```

Wallet features that need a secure origin wait until this step.

### Day-to-day

```bash
mirage-status
mirage-update             # activate a staged ordinary release
mirage-update --rollback  # only when the signed release permits rollback
```

The node checks for signed releases hourly. Ordinary releases stage and wait for `mirage-update`. Governance-halt releases also stage, but the host tool refuses to activate them manually; use the governed upgrade procedure at the announced halt. A staged release is refused if this node is too far behind (`min_prior_version`), if the network manifest went backwards a generation, or if a governance halt is within 500 blocks. Rollback is available only when the active signed manifest explicitly marks it safe and the release is not consensus-breaking.

## What the installer will refuse

- Ubuntu other than 24.04, or any architecture other than amd64
- Container virtualization (LXC, OpenVZ, Docker-in-Docker)
- No SSH public key in `/root/.ssh/authorized_keys` (it will not disable password auth and lock you out)
- A mnemonic that is not exactly 12 BIP-39 English words
- An account with no username, or with less than 10,000,000 MIRAGE (it prints the actual balance)
- A seed whose consensus key is already a validator on another host (migrate with `scripts/backup_restore.py --migrate` instead)
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
