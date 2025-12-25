# Validator Unjail Troubleshooting: Tx Accepted but Not Included

This guide covers a common failure mode where an unjail transaction appears to be accepted by the mempool, but it never shows up in a block.

### Symptoms

- Validator shows `jailed: true`
- An unjail transaction returns a mempool acceptance code, but you cannot find it by hash later
- The validator remains jailed after multiple block intervals

### Common causes

### 1) Wrong account sequence

Cosmos SDK transactions are sequence-checked. If you sign with the wrong sequence, the tx will be rejected.

**Norm:** query the on-chain account sequence immediately before signing, and use exactly that value. Do not guess and do not add 1.

### 2) Broadcasting to the wrong endpoint

If you broadcast to a node that is catching up, misconfigured, or partitioned, the tx may not propagate well.

**Norm:** broadcast to a healthy RPC endpoint for a validator that is fully caught up.

### 3) Unjail is not yet allowed

If the `jailed_until` time has not elapsed, unjail attempts will fail.

**Norm:** check `jailed_until` first, then submit.

### 4) Slow or missing tx indexing

Some environments have slow indexing or indexing disabled. In that case, looking up a tx by hash may fail even if the state change succeeded.

**Norm:** verify the result by checking state, not only by searching tx hashes.

### Checklist (generic)

Set these:

```bash
RPC="tcp://127.0.0.1:26657"
VALOPER="<YOUR_VALOPER_ADDRESS>"
```

1) Confirm the node is caught up:

```bash
miraged status --node "${RPC}" | jq -r '.SyncInfo.catching_up'
```

2) Check the validator state, including `jailed` and `jailed_until`:

```bash
miraged q staking validator "${VALOPER}" --node "${RPC}" -o json | jq '.validator | {jailed, jailed_until, status}'
```

3) If the tx lookup is unreliable, confirm success via state:

- If `jailed` flips to `false`, the unjail succeeded.
- If it stays `true`, fix sequence, endpoint health, or timing, then retry.

### Related

- `scripts/unjail_validator.sh`
- `docs/troubleshooting/common-issues.md`


