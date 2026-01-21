package core

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
