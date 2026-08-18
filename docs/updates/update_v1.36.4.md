# Mirage v1.36.4 Release Notes

### Run a validator with one command

Mirage now has a public, provider-independent installer for a clean Ubuntu server. It checks the machine, hardens SSH and the firewall, verifies the release, imports an existing funded account, starts the node and keeps retrying validator enrollment until the chain is synced. Operators no longer need a prepared image or a provider-specific setup path.

### Signed from policy to image

Every public install is anchored to an offline signing key. Network addresses, minimum balances and staking requirements live in an expiring signed policy, while the release itself names an immutable container digest. A node refuses missing signatures, stale policy generations, incompatible versions, altered bootstrap helpers and images carrying a different trust key.

### Clear validator economics

Activation requires ten million MIRAGE: five million is self-delegated and five million remains liquid. The node treats one million liquid MIRAGE as the operating floor for fees and refuses additional self-delegation that would cross it. The status dashboard reports the same signed limits rather than maintaining its own copy.

### Safer updates and recovery

Release checks run hourly, but ordinary activation remains an operator decision. Updates refuse downgrade replays, incompatible starting versions, imminent governance halts and unsafe rollbacks. Hosts receive refreshed tools from each verified image, preserve the previous image when rollback is explicitly allowed, and retain the forensic safeguards used when recovering diverged state.

### An honest custody tradeoff

The installer uses the account’s existing twelve-word seed and stores it in the node’s plaintext test keyring so enrollment, fees and self-delegation can run unattended. Root access to the validator therefore means control of that account. Operators who require hardware-backed or password-gated custody should not use this installer until a separate host-key design is available.

### Tested as a real deployment

The release checks truncation safety, signature tampering, policy expiry, peer pagination, transaction ordering, updater rollback rules, mirror completeness and Docker build-secret exclusion. The complete local release rehearsal also rebuilds and deploys the container, verifies chain and indexer progress, and runs both integration suites before publication.
