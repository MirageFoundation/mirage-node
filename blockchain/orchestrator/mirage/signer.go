package mirage

import (
	"context"
	"encoding/hex"
	"fmt"
	"strconv"
	"strings"
	"time"

	sdkmath "cosmossdk.io/math"
	"github.com/cosmos/cosmos-sdk/client"
	"github.com/cosmos/cosmos-sdk/client/tx"
	sdk "github.com/cosmos/cosmos-sdk/types"
	txtypes "github.com/cosmos/cosmos-sdk/types/tx"

	"mirage/orchestrator/chains"
	coretypes "mirage/x/core/types"
)

// unorderedTxTimeout is the timeout duration for unordered transactions.
// Must be under the chain's max TTL (10m). Using 5m for safety margin.
const unorderedTxTimeout = 5 * time.Minute

// gasBufferMultiplier is the safety margin applied to simulated gas.
// With inline fee burning, the variance is small (only the threshold-crossing tx
// burns the fee). 1.5x covers the difference between a normal attestation and
// the one that triggers the burn.
const gasBufferMultiplier = 1.5

// simulationGasLimit is a high gas limit used only for simulation.
const simulationGasLimit = 1_000_000

func (c *Client) SubmitBridgeAttest(ctx context.Context, burn chains.ExternalBurnEvent) error {
	burnID := strings.ToLower(strings.TrimSpace(burn.BurnID))
	msg := &coretypes.MsgBridgeAttestBurned{
		Validator:       c.FromAddress(),
		SourceChain:     burn.SourceChain,
		BurnId:          burnID,
		MirageRecipient: burn.MirageRecipient,
		Amount:          burn.Amount,
	}

	txBytes, feeUmirage, err := c.buildTxBytesWithSimulation(ctx, msg)
	if err != nil {
		return err
	}
	txClient := txtypes.NewServiceClient(c.grpcConn)
	resp, err := txClient.BroadcastTx(ctx, &txtypes.BroadcastTxRequest{
		TxBytes: txBytes,
		Mode:    txtypes.BroadcastMode_BROADCAST_MODE_SYNC,
	})
	if err != nil {
		return fmt.Errorf("broadcast tx failed: %w", err)
	}
	if resp.TxResponse == nil {
		return fmt.Errorf("broadcast tx response missing")
	}
	if resp.TxResponse.Code != 0 {
		return fmt.Errorf("broadcast tx rejected (CheckTx): code=%d raw_log=%s", resp.TxResponse.Code, resp.TxResponse.RawLog)
	}

	txHash := resp.TxResponse.TxHash
	c.logger.Printf("DEBUG attestation broadcast accepted burn_id=%s txhash=%s (waiting for confirmation...)", burnID, txHash)

	// Wait for tx to be included in a block and verify execution succeeded
	if err := c.waitForTx(ctx, txHash, 30*time.Second); err != nil {
		c.logger.Printf("ERROR attestation tx FAILED burn_id=%s txhash=%s error=%v", burnID, txHash, err)
		return fmt.Errorf("attestation tx failed: %w", err)
	}

	c.logger.Printf("INFO  [FEES] attestation gas_fee=%.2f MIRAGE burn_id=%s txhash=%s",
		float64(feeUmirage)/1_000_000, burnID, txHash)
	return nil
}

func (c *Client) SubmitBridgeMinted(ctx context.Context, burnID, destChain, destTx string, bridgeFeeUmirage uint64, mirageTxHash string) error {
	burnID = strings.ToLower(strings.TrimSpace(burnID))
	msg := &coretypes.MsgBridgeAttestMinted{
		Validator:        c.FromAddress(),
		BurnId:           burnID,
		DestinationChain: strings.TrimSpace(destChain),
		DestinationTx:    strings.TrimSpace(destTx),
		MirageTxHash:     strings.ToUpper(strings.TrimSpace(mirageTxHash)),
	}

	txBytes, gasFeeUmirage, err := c.buildTxBytesWithSimulation(ctx, msg)
	if err != nil {
		return err
	}
	txClient := txtypes.NewServiceClient(c.grpcConn)
	resp, err := txClient.BroadcastTx(ctx, &txtypes.BroadcastTxRequest{
		TxBytes: txBytes,
		Mode:    txtypes.BroadcastMode_BROADCAST_MODE_SYNC,
	})
	if err != nil {
		return fmt.Errorf("broadcast tx failed: %w", err)
	}
	if resp.TxResponse == nil {
		return fmt.Errorf("broadcast tx response missing")
	}
	if resp.TxResponse.Code != 0 {
		return fmt.Errorf("broadcast tx rejected (CheckTx): code=%d raw_log=%s", resp.TxResponse.Code, resp.TxResponse.RawLog)
	}

	txHash := resp.TxResponse.TxHash
	c.logger.Printf("DEBUG bridge_minted broadcast accepted burn_id=%s txhash=%s (waiting for confirmation...)", burnID, txHash)

	// Wait for tx to be included in a block and verify execution succeeded
	if err := c.waitForTx(ctx, txHash, 30*time.Second); err != nil {
		c.logger.Printf("ERROR bridge_minted tx FAILED burn_id=%s txhash=%s error=%v", burnID, txHash, err)
		return fmt.Errorf("bridge_minted tx failed: %w", err)
	}

	netProfit := float64(int64(bridgeFeeUmirage)-int64(gasFeeUmirage)) / 1_000_000
	c.logger.Printf("INFO  [FEES] bridge_minted gas_fee=%.2f MIRAGE bridge_fee_received=%.2f MIRAGE net_profit=%.2f MIRAGE burn_id=%s txhash=%s",
		float64(gasFeeUmirage)/1_000_000, float64(bridgeFeeUmirage)/1_000_000, netProfit, burnID, txHash)
	return nil
}

// buildTxBytesWithSimulation builds tx bytes using simulation to determine gas.
// Returns the tx bytes and the fee amount in umirage.
func (c *Client) buildTxBytesWithSimulation(ctx context.Context, msg sdk.Msg) ([]byte, uint64, error) {
	clientCtx := c.ClientContext()
	fromAddr := clientCtx.GetFromAddress()
	accNum, _, err := c.accountRetriever.GetAccountNumberSequence(clientCtx, fromAddr)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to query account info: %w", err)
	}

	// Build UNORDERED tx for simulation - must match broadcast tx structure
	// to get accurate gas estimation (unordered txs have different ante handler paths)
	// Timeout must be under the chain TTL limit (10m).
	simTimeout := time.Now().Add(unorderedTxTimeout)
	simFeeCoins := sdk.NewCoins(sdk.NewCoin(c.cfg.Mirage.FeeDenom, sdkmath.NewInt(0)))
	simTxBytes, err := c.buildUnorderedTx(clientCtx, msg, accNum, simTimeout, simulationGasLimit, simFeeCoins)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to build simulation tx: %w", err)
	}

	// Simulate to get gas used
	txClient := txtypes.NewServiceClient(c.grpcConn)
	simResp, err := txClient.Simulate(ctx, &txtypes.SimulateRequest{TxBytes: simTxBytes})
	if err != nil {
		return nil, 0, fmt.Errorf("simulation failed: %w", err)
	}
	if simResp.GasInfo == nil {
		return nil, 0, fmt.Errorf("simulation returned no gas info")
	}

	gasUsed := simResp.GasInfo.GasUsed
	gasLimit := uint64(float64(gasUsed) * gasBufferMultiplier)
	c.logger.Printf("DEBUG simulation gas_used=%d gas_limit=%d", gasUsed, gasLimit)

	// Calculate fee: gas_limit * min_gas_price
	// min_gas_price is 5000umirage per cursor.md
	minGasPrice := sdkmath.NewInt(5000)
	feeAmount := minGasPrice.MulRaw(int64(gasLimit))
	feeCoins := sdk.NewCoins(sdk.NewCoin(c.cfg.Mirage.FeeDenom, feeAmount))

	// Build final UNORDERED tx with correct gas and fee for broadcast
	timeout := time.Now().Add(unorderedTxTimeout)
	txBytes, err := c.buildUnorderedTx(clientCtx, msg, accNum, timeout, gasLimit, feeCoins)
	if err != nil {
		return nil, 0, err
	}
	return txBytes, feeAmount.Uint64(), nil
}

// buildUnorderedTx builds an unordered tx with timeout for actual broadcast.
// Unordered txs must NOT have a sequence number (SDK rejects sequence != 0).
func (c *Client) buildUnorderedTx(
	clientCtx client.Context,
	msg sdk.Msg,
	accNum uint64,
	timeout time.Time,
	gasLimit uint64,
	feeCoins sdk.Coins,
) ([]byte, error) {
	txf := tx.Factory{}.
		WithTxConfig(clientCtx.TxConfig).
		WithChainID(c.cfg.Mirage.ChainID).
		WithKeybase(c.keyring).
		WithAccountNumber(accNum).
		WithSequence(0). // Unordered txs must have sequence = 0
		WithGas(gasLimit).
		WithUnordered(true).
		WithTimeoutTimestamp(timeout)

	txBuilder := clientCtx.TxConfig.NewTxBuilder()
	if err := txBuilder.SetMsgs(msg); err != nil {
		return nil, fmt.Errorf("failed to set tx messages: %w", err)
	}
	txBuilder.SetGasLimit(gasLimit)
	txBuilder.SetFeeAmount(feeCoins)
	txBuilder.SetUnordered(true)
	txBuilder.SetTimeoutTimestamp(timeout)

	if err := tx.Sign(context.Background(), txf, c.cfg.Mirage.KeyName, txBuilder, true); err != nil {
		return nil, err
	}
	return clientCtx.TxConfig.TxEncoder()(txBuilder.GetTx())
}

// QueryBridgeMinted queries existing mint attestation for a burn.
// Used to find the destination_tx that should be used for attestation.
func (c *Client) QueryBridgeMinted(ctx context.Context, destChain, burnID string) (*coretypes.QueryBridgeMintedResponse, error) {
	queryClient := coretypes.NewQueryClient(c.grpcConn)
	resp, err := queryClient.GetBridgeMinted(ctx, &coretypes.QueryBridgeMintedRequest{
		DestinationChain: strings.TrimSpace(destChain),
		BurnId:           strings.ToLower(strings.TrimSpace(burnID)),
	})
	if err != nil {
		return nil, fmt.Errorf("query bridge minted failed: %w", err)
	}
	return resp, nil
}

func parseUint64(raw string, field string) (uint64, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return 0, fmt.Errorf("%s is empty", field)
	}
	value, err := strconv.ParseUint(raw, 10, 64)
	if err != nil {
		return 0, fmt.Errorf("invalid %s: %w", field, err)
	}
	return value, nil
}

// waitForTx waits for a transaction to be included in a block and verifies execution success.
//
// This is critical because BROADCAST_MODE_SYNC only confirms CheckTx passed (tx accepted into
// mempool), not that DeliverTx succeeded (tx executed in block). Without this verification,
// a tx that passes CheckTx but fails during block execution (e.g., out of gas) would
// appear successful in logs but actually fail silently.
//
// Returns nil if tx executed successfully (TxResponse.Code == 0).
// Returns error if:
//   - tx is not found within maxWait (not included in any block)
//   - tx execution failed (TxResponse.Code != 0, e.g., out of gas)
//   - context is cancelled
func (c *Client) waitForTx(ctx context.Context, txHash string, maxWait time.Duration) error {
	txClient := txtypes.NewServiceClient(c.grpcConn)

	// Convert hex string to bytes for the query
	hashBytes, err := hex.DecodeString(strings.TrimPrefix(strings.ToUpper(txHash), "0X"))
	if err != nil {
		return fmt.Errorf("invalid tx hash: %w", err)
	}

	deadline := time.Now().Add(maxWait)
	pollInterval := 500 * time.Millisecond

	for time.Now().Before(deadline) {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		resp, err := txClient.GetTx(ctx, &txtypes.GetTxRequest{Hash: fmt.Sprintf("%X", hashBytes)})
		if err != nil {
			// Tx not found yet, keep polling
			time.Sleep(pollInterval)
			continue
		}

		if resp.TxResponse == nil {
			time.Sleep(pollInterval)
			continue
		}

		// Tx found - check result
		if resp.TxResponse.Code != 0 {
			return fmt.Errorf("tx execution failed: code=%d raw_log=%s", resp.TxResponse.Code, resp.TxResponse.RawLog)
		}

		// Success
		return nil
	}

	return fmt.Errorf("tx not confirmed within %v", maxWait)
}
