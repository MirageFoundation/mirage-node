package mirage

import (
	"context"
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
// Unordered tx gas can vary slightly with ante path and state reads.
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
		return fmt.Errorf("broadcast tx failed code=%d raw_log=%s", resp.TxResponse.Code, resp.TxResponse.RawLog)
	}

	c.logger.Printf("INFO  [FEES] attestation gas_fee=%.2f MIRAGE burn_id=%s txhash=%s",
		float64(feeUmirage)/1_000_000, burnID, resp.TxResponse.TxHash)
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
		return fmt.Errorf("broadcast tx failed code=%d raw_log=%s", resp.TxResponse.Code, resp.TxResponse.RawLog)
	}

	netProfit := float64(int64(bridgeFeeUmirage)-int64(gasFeeUmirage)) / 1_000_000
	c.logger.Printf("INFO  [FEES] bridge_minted gas_fee=%.2f MIRAGE bridge_fee_received=%.2f MIRAGE net_profit=%.2f MIRAGE burn_id=%s txhash=%s",
		float64(gasFeeUmirage)/1_000_000, float64(bridgeFeeUmirage)/1_000_000, netProfit, burnID, resp.TxResponse.TxHash)
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
