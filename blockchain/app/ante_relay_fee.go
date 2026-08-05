package app

import (
	"fmt"

	sdkmath "cosmossdk.io/math"
	sdk "github.com/cosmos/cosmos-sdk/types"

	corekeeper "mirage/x/core/keeper"
)

// checkRelayGasPayment enforces floor and ceiling on the Cosmos gas payment (Fee field).
//
// Floor: when minPrices is non-zero (CheckTx), offered must be >= gas * minPrices.
// Ceiling (C-1): offered umirage must not exceed gas * relayMinGasPrice, hard-capped at
// relayMaxGasFee. Bound is deterministic across CheckTx and Finalize.
func checkRelayGasPayment(
	gas uint64,
	offered sdk.Coins,
	minPrices sdk.DecCoins,
	relayMinGasPrice uint64,
	relayMaxGasFee uint64,
) error {
	if !minPrices.IsZero() {
		required := sdk.NewCoins()
		for _, gp := range minPrices {
			amt := gp.Amount.MulInt64(int64(gas)).Ceil().TruncateInt()
			if amt.IsPositive() {
				required = required.Add(sdk.NewCoin(gp.Denom, amt))
			}
		}
		if !offered.IsAnyGTE(required) {
			return fmt.Errorf(
				"insufficient fee: got %s required any >= %s (minGasPrices=%s, gas=%d)",
				offered, required, minPrices, gas,
			)
		}
	}

	var maxAmt uint64
	if gas > 0 && relayMinGasPrice > 0 && gas > ^uint64(0)/relayMinGasPrice {
		maxAmt = relayMaxGasFee
	} else {
		maxAmt = gas * relayMinGasPrice
		if relayMaxGasFee > 0 && maxAmt > relayMaxGasFee {
			maxAmt = relayMaxGasFee
		}
	}
	if maxAmt == 0 {
		return nil
	}
	maxCoin := sdk.NewCoin("umirage", sdkmath.NewIntFromUint64(maxAmt))
	for _, c := range offered {
		if c.Denom != "umirage" {
			return fmt.Errorf("relay fee: unsupported denom %s (want umirage)", c.Denom)
		}
		if c.Amount.GT(maxCoin.Amount) {
			return fmt.Errorf(
				"fee too high: got %s max %s (gas=%d relay_min_gas_price=%d relay_max_gas_fee=%d)",
				c.String(), maxCoin.String(), gas, relayMinGasPrice, relayMaxGasFee,
			)
		}
	}
	return nil
}

// makeRelayTxFeeChecker returns a TxFeeChecker for relay transactions.
// The Cosmos Fee field is the gas payment; this does not introduce an application fee.
func makeRelayTxFeeChecker(k corekeeper.Keeper) func(ctx sdk.Context, tx sdk.Tx) (sdk.Coins, int64, error) {
	return func(ctx sdk.Context, tx sdk.Tx) (sdk.Coins, int64, error) {
		ftx, ok := tx.(sdk.FeeTx)
		if !ok {
			return nil, 0, fmt.Errorf("relay fee: expected FeeTx")
		}
		gas := ftx.GetGas()
		offered := ftx.GetFee()
		params := k.GetParams(ctx)

		if err := checkRelayGasPayment(gas, offered, ctx.MinGasPrices(), params.RelayMinGasPrice, params.RelayMaxGasFee); err != nil {
			ctx.Logger().Warn("relay gas payment rejected", "err", err.Error(), "gas", gas, "offered", offered.String())
			return nil, 0, err
		}

		priority := int64(0)
		if !offered.IsZero() {
			priority = offered.AmountOf("umirage").Int64()
			if priority < 0 {
				priority = 0
			}
		}
		return offered, priority, nil
	}
}
