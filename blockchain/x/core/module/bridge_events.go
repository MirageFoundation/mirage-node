package core

// =============================================================================
// DORMANT - Bridge module (offline since v1.20.0)
//
// The Mirage bridge is intentionally OFFLINE. The off-chain orchestrator
// binary is hard-disabled at startup (see blockchain/cmd/orchestrator/main.go)
// and no validator runs it. No bridge_chain is currently enabled in chain
// params either. The event-builder helpers below are still compiled into the
// chain binary, but they are only invoked by the dormant bridge handlers and
// thus do not fire in production.
//
// SECURITY-REVIEW SCOPE: bridge / orchestrator findings are accepted-and-
// deferred. They are tracked in docs/security/blockchain/review-2026-04-24.md
// under "Outstanding bridge-scope" and will be revisited in a dedicated audit
// only when the bridge is reactivated. Do NOT surface findings from this file
// in live remediation queues until that time.
// =============================================================================

import (
	"fmt"

	sdk "github.com/cosmos/cosmos-sdk/types"
)

func buildBridgeBurnEvent(owner, destChain, destAddr string, amount, bridgeFee, sequence uint64) sdk.Event {
	return sdk.NewEvent(
		"bridge_burn",
		sdk.NewAttribute("burn_id", fmt.Sprintf("%d", sequence)),
		sdk.NewAttribute("owner", owner),
		sdk.NewAttribute("destination_chain", destChain),
		sdk.NewAttribute("destination_address", destAddr),
		sdk.NewAttribute("amount", fmt.Sprintf("%d", amount)),
		sdk.NewAttribute("bridge_fee", fmt.Sprintf("%d", bridgeFee)),
		sdk.NewAttribute("sequence", fmt.Sprintf("%d", sequence)),
	)
}
