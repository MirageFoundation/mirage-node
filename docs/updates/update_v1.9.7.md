# Mirage v1.9.7 Release Notes

### Overview

v1.9.7 hardens the outbound bridge to make stuck burns a thing of the past. The orchestrator now replays pending burns on startup, so a temporary outage or low SOL balance no longer leaves transfers in limbo.

We also simplified fee handling to reduce chain state complexity and make burn accounting deterministic. The result is a cleaner bridge flow with fewer moving parts and clearer APIs for operators and integrators.

---

### Bridge Reliability

- Orchestrator replays pending outbound burns on startup
- Automatic recovery after RPC outages or low SOL incidents
- Fail‑fast if tx indexing is disabled (prevents silent replay gaps)

---

### Fee Simplification

- Bridge fee is burned immediately at `MsgBridgeBurn`
- Removes module escrow and burn‑on‑confirm path
- Less state churn and simpler accounting

---

### Bug fixes

- Consistent bridge query naming (`GetBridgeMint` / `GetBridgeBurn`)
- REST path aligned with CLI naming (`/bridge/mint/...`)

---

### For developers

- **Upgrade name:** `v1.9.7-bridge-replay`
- **REST:** `GET /mirage/core/v1/bridge/mint/{destination_chain}/{burn_id}`
- **CLI:** `miraged q bridge mint [destination_chain] [burn_id]`
- **Config:** CometBFT `tx_index = "on"` is required for replay
- **Deploy migration:** `v1_9_7_tx_index`
