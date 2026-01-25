# Mirage v1.9.1 Release Notes

### Overview

v1.9.1 is a maintenance release that fixes bridge query endpoints and improves deployment reliability. The primary fixes address the CLI and REST endpoints for querying bridge mint attestation status, which are essential for the frontend to display attestation progress during bridging operations.

**Upgrade Name:** `v1.9.1-query-fix`

---

### Bug Fixes

#### Bridge Query Endpoints

1. **CLI Fix**: `miraged q bridge mint` now correctly accepts both required parameters
   - **Before**: `miraged q bridge mint [burn_id]` (broken - missing destination_chain)
   - **After**: `miraged q bridge mint [destination_chain] [burn_id]`
   
2. **REST Gateway Fix**: Added missing `GetBridgeMint` handler to REST gateway
   - Endpoint: `GET /mirage/core/v1/bridge/mint/{destination_chain}/{burn_id}`
   - Previously returned "Not Implemented" error
   
3. **Proto Response Fix**: `QueryBridgeMintResponse` now includes all attestation progress fields
   - `found` - whether attestation record exists
   - `attestors` - list of validators who have attested
   - `attested_power` - total voting power attested
   - `required_power` - voting power needed to confirm

These fixes enable the frontend to properly poll and display attestation progress (e.g., "2 validators attested (45.2% power, need 66.7%)").

---

### Deployment Improvements

- **Always prune on remote deploys**: `deploy.sh` now always runs `docker system prune -af` and clears `/tmp` for remote deployments
- Removed `--prune` and `--no-prune` options - pruning is no longer optional for remote deploys
- Local deploys continue to skip pruning by default

---

### Verification Script Updates

- Updated `scripts/verify_upgrade.py` to check for correct message class names:
  - `MsgBridgeAttestBurned` (was incorrectly checking for `MsgBridgeAttest`)
  - `MsgBridgeAttestBurnedResponse`
  - `MsgBridgeAttestMinted`
  - `MsgBridgeAttestMintedResponse`

---

### File Changes

**Modified:**
- `blockchain/x/core/module/cli_bridge.go` - CLI fix for destination_chain parameter
- `blockchain/x/core/types/query.pb.gw.go` - REST gateway handler for GetBridgeMint
- `blockchain/proto/mirage/core/v1/query.proto` - Added attestation fields to response
- `blockchain/app/upgrades.go` - Added v1.9.1-query-fix upgrade handler
- `deploy/deploy.sh` - Always prune on remote deploys
- `scripts/verify_upgrade.py` - Fixed message class name checks

---

### Upgrade Instructions

**Binary Upgrade Required**: This release requires deploying new binaries to fix the query endpoints.

1. Build new binaries:
   ```bash
   cd blockchain && make build-all
   ```

2. Deploy to validators:
   ```bash
   ./deploy/deploy.sh root@<server> --update
   ```
   
   Note: This will automatically prune Docker and clear `/tmp`.

3. Verify upgrade:
   ```bash
   python3 scripts/verify_upgrade.py --phase post
   ```

---

### Validator Requirements

No additional setup required beyond deploying the new binary. The upgrade handler is a no-op that simply bumps the version.

---

### Breaking Changes

- `miraged q bridge mint` CLI command now requires two arguments instead of one
  - **Before**: `miraged q bridge mint 104`
  - **After**: `miraged q bridge mint solana 104`

---

### API Changes

**REST Endpoint (Fixed):**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/mirage/core/v1/bridge/mint/{destination_chain}/{burn_id}` | GET | Query mint attestation status |

**Response Fields (Added):**
```json
{
  "minted": true,
  "destination_chain": "solana",
  "destination_tx": "43M6crq...",
  "found": true,
  "attestors": ["miragevaloper1..."],
  "attested_power": "10000000000000",
  "required_power": "9990004000000"
}
```
