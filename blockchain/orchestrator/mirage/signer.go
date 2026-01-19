package mirage

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/cosmos/cosmos-sdk/client/tx"
	sdk "github.com/cosmos/cosmos-sdk/types"
	txtypes "github.com/cosmos/cosmos-sdk/types/tx"

	"mirage/orchestrator/chains"
	coretypes "mirage/x/core/types"
)

// unorderedTxTimeout is the timeout duration for unordered transactions.
// Must be long enough to allow tx propagation and inclusion.
const unorderedTxTimeout = 10 * time.Minute

func (c *Client) SubmitBridgeAttest(ctx context.Context, burn chains.ExternalBurnEvent) error {
	burnID := strings.ToLower(strings.TrimSpace(burn.BurnID))
	msg := &coretypes.MsgBridgeAttest{
		Validator:       c.valoperFromAcc(),
		SourceChain:     burn.SourceChain,
		BurnId:          burnID,
		MirageRecipient: burn.MirageRecipient,
		Amount:          burn.Amount,
	}

	txBytes, err := c.buildTxBytes(ctx, msg)
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

func (c *Client) buildTxBytes(ctx context.Context, msg sdk.Msg) ([]byte, error) {
	clientCtx := c.ClientContext()
	fromAddr := clientCtx.GetFromAddress()
	accNum, accSeq, err := c.accountRetriever.GetAccountNumberSequence(clientCtx, fromAddr)
	if err != nil {
		return nil, fmt.Errorf("failed to query account info: %w", err)
	}

	// Use unordered transaction with timeout timestamp per cursor.md rules
	timeout := time.Now().Add(unorderedTxTimeout)

	// Build fee string like "1000umirage"
	feeStr := fmt.Sprintf("%d%s", c.cfg.Mirage.FeeAmount, c.cfg.Mirage.FeeDenom)
	feeCoins, err := sdk.ParseCoinsNormalized(feeStr)
	if err != nil {
		return nil, fmt.Errorf("failed to parse fee coins: %w", err)
	}

	txf := tx.Factory{}.
		WithTxConfig(clientCtx.TxConfig).
		WithChainID(c.cfg.Mirage.ChainID).
		WithKeybase(c.keyring).
		WithAccountNumber(accNum).
		WithSequence(accSeq).
		WithGas(c.cfg.Mirage.GasLimit).
		WithFees(feeStr).
		WithUnordered(true).
		WithTimeoutTimestamp(timeout)

	txBuilder := clientCtx.TxConfig.NewTxBuilder()
	if err := txBuilder.SetMsgs(msg); err != nil {
		return nil, fmt.Errorf("failed to set tx messages: %w", err)
	}
	txBuilder.SetGasLimit(c.cfg.Mirage.GasLimit)
	txBuilder.SetFeeAmount(feeCoins)
	txBuilder.SetUnordered(true)
	txBuilder.SetTimeoutTimestamp(timeout)

	if err := tx.Sign(ctx, txf, c.cfg.Mirage.KeyName, txBuilder, true); err != nil {
		return nil, err
	}
	return clientCtx.TxConfig.TxEncoder()(txBuilder.GetTx())
}

func (c *Client) valoperFromAcc() string {
	return c.ValoperAddress()
}

// ValoperAddress returns the validator operator address for this client's key.
func (c *Client) ValoperAddress() string {
	addr := c.ClientContext().GetFromAddress()
	valAddr := sdk.ValAddress(addr)
	return valAddr.String()
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

