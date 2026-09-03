package app

import (
	"crypto/sha256"
	"fmt"

	sdk "github.com/cosmos/cosmos-sdk/types"
	banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"

	coretypes "mirage/x/core/types"
)

// LoggingDecorator logs every message in a transaction with high-level details.
type LoggingDecorator struct{}

func (d LoggingDecorator) AnteHandle(ctx sdk.Context, tx sdk.Tx, simulate bool, next sdk.AnteHandler) (sdk.Context, error) {
	logger := ctx.Logger()
	phase := execPhase(ctx)
	hash := txHashHex(ctx)

	// Log fee/gas envelope if present
	if ftx, ok := tx.(sdk.FeeTx); ok {
		payer := ""
		if p := ftx.FeePayer(); p != nil {
			payer = sdk.AccAddress(p).String()
		}
		granter := ""
		if g := ftx.FeeGranter(); g != nil {
			granter = sdk.AccAddress(g).String()
		}
		logger.Info(
			"--> Tx Envelope",
			"phase", phase,
			"tx", hash,
			"gas_provided", ftx.GetGas(),
			"gas_limit_ctx", ctx.GasMeter().Limit(),
			"gas_used_ctx", ctx.GasMeter().GasConsumed(),
			"block_height", ctx.BlockHeight(),
			"fee", ftx.GetFee().String(),
			"fee_payer", payer,
			"fee_granter", granter,
			"min_gas_prices", ctx.MinGasPrices().String(),
		)
	}
	for _, msg := range tx.GetMsgs() {
		switch m := msg.(type) {
		case *banktypes.MsgSend:
			logger.Info("--> Tx MsgSend", "phase", phase, "tx", hash, "from", m.FromAddress, "to", m.ToAddress, "amount", m.Amount.String())
		case *coretypes.MsgSetUsername:
			logger.Info("--> Tx SetUsername", "phase", phase, "tx", hash, "signer", m.Authority, "target", m.Target, "username", m.Username)
		case *coretypes.MsgEnableAgent:
			logger.Info("--> Tx EnableAgent", "phase", phase, "tx", hash, "signer", m.Authority, "target", m.Target, "agent", m.Agent)
		case *coretypes.MsgDisableAgent:
			logger.Info("--> Tx DisableAgent", "phase", phase, "tx", hash, "signer", m.Authority, "target", m.Target, "agent", m.Agent)
		case *coretypes.MsgSetAgents:
			logger.Info("--> Tx SetAgents", "phase", phase, "tx", hash, "signer", m.Authority, "target", m.Target, "count", len(m.Agents))
		case *coretypes.MsgPost:
			logger.Info("--> Tx Post", "phase", phase, "tx", hash, "signer", m.Authority, "community", m.Community, "target", m.Target, "tag", m.Tag)
		case *coretypes.MsgEdit:
			logger.Info("--> Tx Edit", "phase", phase, "tx", hash, "signer", m.Authority, "community", m.Community, "target", m.Target, "tag", m.Tag)
		case *coretypes.MsgVote:
			logger.Info("--> Tx Vote", "phase", phase, "tx", hash, "signer", m.Authority, "target", m.Target, "direction", m.Direction)
		case *coretypes.MsgFollowUser:
			logger.Info("--> Tx FollowUser", "phase", phase, "tx", hash, "signer", m.Authority, "target", m.Target, "user", m.User)
		case *coretypes.MsgUnfollowUser:
			logger.Info("--> Tx UnfollowUser", "phase", phase, "tx", hash, "signer", m.Authority, "target", m.Target, "user", m.User)
		case *coretypes.MsgFollowTopic:
			logger.Info("--> Tx FollowTopic", "phase", phase, "tx", hash, "signer", m.Authority, "target", m.Target, "topic", m.Topic)
		case *coretypes.MsgUnfollowTopic:
			logger.Info("--> Tx UnfollowTopic", "phase", phase, "tx", hash, "signer", m.Authority, "target", m.Target, "topic", m.Topic)
		case *coretypes.MsgBlockTopic:
			logger.Info("legacy_mobile", "phase", phase, "tx", hash, "message", "MsgBlockTopic", "topic", m.Topic)
		case *coretypes.MsgUnblockTopic:
			logger.Info("legacy_mobile", "phase", phase, "tx", hash, "message", "MsgUnblockTopic", "topic", m.Topic)
		case *coretypes.MsgBlockPost:
			logger.Info("--> Tx BlockPost", "phase", phase, "tx", hash, "signer", m.Authority, "target", m.Target)
		case *coretypes.MsgUnblockPost:
			logger.Info("--> Tx UnblockPost", "phase", phase, "tx", hash, "signer", m.Authority, "target", m.Target)
		case *coretypes.MsgBlockUser:
			logger.Info("--> Tx BlockUser", "phase", phase, "tx", hash, "signer", m.Authority, "target", m.Target)
		case *coretypes.MsgUnblockUser:
			logger.Info("--> Tx UnblockUser", "phase", phase, "tx", hash, "signer", m.Authority, "target", m.Target)
		case *coretypes.MsgDelete:
			logger.Info("--> Tx Delete", "phase", phase, "tx", hash, "signer", m.Authority, "target", m.Target)
		case *coretypes.MsgSendTokens:
			logger.Info("--> Tx SendTokens", "phase", phase, "tx", hash, "signer", m.Authority, "sender", m.Sender, "target", m.Target, "amount", m.Amount)
		case *coretypes.MsgSetLevel:
			logger.Info("--> Tx SetLevel", "phase", phase, "tx", hash, "signer", m.Authority, "target", m.Target, "level", m.Level)
		case *coretypes.MsgAward:
			logger.Info("--> Tx Award", "phase", phase, "tx", hash, "signer", m.Authority, "target", m.Target, "award_type", m.AwardType)
		case *coretypes.MsgSetBiography:
			logger.Info("--> Tx SetBiography", "phase", phase, "tx", hash, "signer", m.Authority, "target", m.Target, "bio_len", len(m.Biography))
		default:
			logger.Info("--> Tx Msg", "phase", phase, "tx", hash, "type", sdk.MsgTypeURL(msg))
		}
	}
	newCtx, err := next(ctx, tx, simulate)
	if err != nil {
		// Surface ante rejections prominently with tx hash and phase
		logger.Error("--> Tx rejected in ante", "phase", phase, "tx", hash, "err", err.Error())
	}
	return newCtx, err
}

func txHashHex(ctx sdk.Context) string {
	b := ctx.TxBytes()
	if len(b) == 0 {
		return ""
	}
	sum := sha256.Sum256(b)
	return fmt.Sprintf("%X", sum[:])
}

func execPhase(ctx sdk.Context) string {
	switch ctx.ExecMode() {
	case sdk.ExecModeReCheck:
		return "recheck"
	case sdk.ExecModeFinalize:
		return "deliver"
	case sdk.ExecModeCheck:
		return "check"
	case sdk.ExecModeSimulate:
		return "simulate"
	default:
		return "unknown"
	}
}
