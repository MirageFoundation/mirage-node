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
// Must be long enough to allow tx propagation and inclusion.
const unorderedTxTimeout = 10 * time.Minute

// gasBufferMultiplier is the safety margin applied to simulated gas.
const gasBufferMultiplier = 1.3

// simulationGasLimit is a high gas limit used only for simulation.
const simulationGasLimit = 1_000_000

func (c *Client) SubmitBridgeAttest(ctx context.Context, burn chains.ExternalBurnEvent) error {
	burnID := strings.ToLower(strings.TrimSpace(burn.BurnID))
	msg := &coretypes.MsgBridgeAttest{
		Validator:       c.FromAddress(),
		SourceChain:     burn.SourceChain,
		BurnId:          burnID,
		MirageRecipient: burn.MirageRecipient,
		Amount:          burn.Amount,
	}

	txBytes, err := c.buildTxBytesWithSimulation(ctx, msg)
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

	c.logger.Printf("DEBUG attestation submitted burn_id=%s txhash=%s", burnID, resp.TxResponse.TxHash)
	return nil
}

func (c *Client) SubmitBridgeMinted(ctx context.Context, burnID, destChain, destTx string) error {
	burnID = strings.ToLower(strings.TrimSpace(burnID))
	msg := &coretypes.MsgBridgeMinted{
		Authority:        c.FromAddress(),
		BurnId:           burnID,
		DestinationChain: strings.TrimSpace(destChain),
		DestinationTx:    strings.TrimSpace(destTx),
	}

	txBytes, err := c.buildTxBytesWithSimulation(ctx, msg)
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

	c.logger.Printf("DEBUG bridge minted submitted burn_id=%s dest_tx=%s txhash=%s", burnID, destTx, resp.TxResponse.TxHash)
	return nil
}

// buildTxBytesWithSimulation builds tx bytes using simulation to determine gas.
func (c *Client) buildTxBytesWithSimulation(ctx context.Context, msg sdk.Msg) ([]byte, error) {
	clientCtx := c.ClientContext()
	fromAddr := clientCtx.GetFromAddress()
	accNum, accSeq, err := c.accountRetriever.GetAccountNumberSequence(clientCtx, fromAddr)
	if err != nil {
		return nil, fmt.Errorf("failed to query account info: %w", err)
	}

	timeout := time.Now().Add(unorderedTxTimeout)

	// Build tx for simulation with high gas limit
	simTxBytes, err := c.buildTxBytesInternal(clientCtx, msg, accNum, accSeq, timeout, simulationGasLimit, sdk.NewCoins())
	if err != nil {
		return nil, fmt.Errorf("failed to build simulation tx: %w", err)
	}

	// Simulate to get gas used
	txClient := txtypes.NewServiceClient(c.grpcConn)
	simResp, err := txClient.Simulate(ctx, &txtypes.SimulateRequest{TxBytes: simTxBytes})
	if err != nil {
		return nil, fmt.Errorf("simulation failed: %w", err)
	}
	if simResp.GasInfo == nil {
		return nil, fmt.Errorf("simulation returned no gas info")
	}

	gasUsed := simResp.GasInfo.GasUsed
	gasLimit := uint64(float64(gasUsed) * gasBufferMultiplier)
	c.logger.Printf("DEBUG simulation gas_used=%d gas_limit=%d", gasUsed, gasLimit)

	// Calculate fee: gas_limit * min_gas_price
	// min_gas_price is 5000umirage per cursor.md
	minGasPrice := sdkmath.NewInt(5000)
	feeAmount := minGasPrice.MulRaw(int64(gasLimit))
	feeCoins := sdk.NewCoins(sdk.NewCoin(c.cfg.Mirage.FeeDenom, feeAmount))

	// Build final tx with correct gas and fee
	return c.buildTxBytesInternal(clientCtx, msg, accNum, accSeq, timeout, gasLimit, feeCoins)
}

func (c *Client) buildTxBytesInternal(
	clientCtx client.Context,
	msg sdk.Msg,
	accNum, accSeq uint64,
	timeout time.Time,
	gasLimit uint64,
	feeCoins sdk.Coins,
) ([]byte, error) {
	txf := tx.Factory{}.
		WithTxConfig(clientCtx.TxConfig).
		WithChainID(c.cfg.Mirage.ChainID).
		WithKeybase(c.keyring).
		WithAccountNumber(accNum).
		WithSequence(accSeq).
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
