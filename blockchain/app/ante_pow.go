package app

import (
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"math/big"
	"strings"

	cryptotypes "github.com/cosmos/cosmos-sdk/crypto/keys/secp256k1"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/cosmos/cosmos-sdk/types/bech32"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"

	corekeeper "mirage/x/core/keeper"
	coretypes "mirage/x/core/types"

	"golang.org/x/crypto/argon2"
)

// PowDecorator enforces PoW for custom posts messages.
// For each custom message (CreateUser, CreatePost, CreateVote), it checks:
//
//	challenge = Argon2id(canonical_without_signature || ":" || pow, salt=last_block_hash)
//	int(challenge) <= base_target * 1000 / (1000 * (1 + pow_factor)^difficulty)
//	last_block_hash matches the current LastBlockId or one of the last Window
//	committed block hashes recorded in the on-chain window (case-insensitive)
//	difficulty >= current dynamic difficulty (prevents spam with artificially low difficulty)
//
// DETERMINISM CONTRACT: the recent-block-hash acceptance window is read from
// on-chain state (types.RecentBlockHashesKey, written by BeginBlock). This is
// IDENTICAL across all peers and across process restarts — eliminating the
// per-process cache that previously caused restart-vs-warm-node divergence:
// a freshly-restarted node had an empty cache and would reject envelopes
// referencing block hashes within the window, while peers (with full caches)
// would accept them, producing per-node tx-acceptance divergence ->
// app-hash divergence.
//
// The last_block_hash equality check is skipped for CheckTx (mempool) where header info may be
// unavailable; it is enforced during DeliverTx.
type PowDecorator struct {
	// MinFee, when provided in the tx fee with same denom and amount >=, skips PoW entirely
	MinFee sdk.Coin
	// Keeper provides access to dynamic difficulty, params, and the on-chain
	// recent-block-hash window.
	Keeper corekeeper.Keeper
}

// recentHashSeen returns true if `hash` (lowercase hex) appears in the
// on-chain recent-block-hashes window. The window is written by BeginBlock
// before any tx in the current block runs, so by the time this is called the
// window contains the previous BlockHashWindow committed block hashes.
//
// Decode/store errors propagate so the caller can reject the tx; silent
// "false" would route a legitimate tx to rejection on this node only and
// produce divergence on the very thing this refactor is fixing.
func (d *PowDecorator) recentHashSeen(ctx sdk.Context, hash string) (bool, error) {
	cmp := strings.ToLower(strings.TrimSpace(hash))
	if cmp == "" {
		return false, nil
	}
	hashes, err := d.Keeper.GetRecentBlockHashes(ctx)
	if err != nil {
		return false, err
	}
	for _, h := range hashes {
		if h == cmp {
			return true, nil
		}
	}
	return false, nil
}

// getUserLevel returns the user level for the address derived from pubkey.
//
// FAIL-FAST CONTRACT: any error reading or decoding the stored ProfileCore is
// returned to the caller — silently treating a corrupt profile as level=0
// routes the tx through the free-tier PoW branch on this node while peers
// route it through the paid-reserve branch, producing a per-node app-hash
// divergence (different events emitted, different state mutations). A
// returned error must reject the tx; the same corrupt bytes on all peers
// reject it identically, so consensus is preserved without silent skew.
//
// Profile not found is NOT an error: it is the legitimate state of a
// brand-new account, which is free-tier by definition.
func (d *PowDecorator) getUserLevel(ctx sdk.Context, pubkey []byte) (level int, addr string, err error) {
	if len(pubkey) != 33 {
		return 0, "", nil
	}
	var cpk cryptotypes.PubKey
	cpk.Key = pubkey
	addrBytes := sdk.AccAddress(cpk.Address())
	addr, _ = bech32.ConvertAndEncode(AccountAddressPrefix, addrBytes)

	bz, found, gerr := d.Keeper.GetProfileCore(ctx, addr)
	if gerr != nil {
		return 0, addr, fmt.Errorf("CONSENSUS_FATAL:PROFILE_GET addr=%s: %w", addr, gerr)
	}
	if !found {
		return 0, addr, nil
	}
	var core coretypes.ProfileCore
	if err := json.Unmarshal(bz, &core); err != nil {
		return 0, addr, fmt.Errorf("CONSENSUS_FATAL:PROFILE_DECODE addr=%s bytes=%d: %w", addr, len(bz), err)
	}
	return int(core.Level), addr, nil
}

// canUsePoW checks whether a user may use PoW instead of paying relayed gas.
// Only free tier (level 0) may use PoW; paid users (>=1) must use reserve.
//
// Decode errors from getUserLevel propagate; callers MUST reject the tx on
// non-nil err to avoid silent free-tier routing on a corrupt profile.
func (d *PowDecorator) canUsePoW(ctx sdk.Context, pubkey []byte) (allowed bool, reason string, err error) {
	level, addr, lerr := d.getUserLevel(ctx, pubkey)
	if lerr != nil {
		return false, "", lerr
	}
	if level == 0 {
		return true, "free tier", nil
	}
	return false, fmt.Sprintf("paid user (level=%d) must use reserve for gas, addr=%s", level, addr), nil
}

// routePoWTx unifies the canUsePoW + checkReserveOrDowngrade decision used by
// every PoW-eligible message branch in AnteHandle.
//
// Returns (canPoW, err):
//   - err != nil: tx must be rejected (decode failure or insufficient reserve).
//     The error string is logged with msgName context for triage.
//   - canPoW == true: caller must run validatePoWBytesArgon2.
//   - canPoW == false, err == nil: caller must skip PoW (paid path covered
//     by reserve, gas will be deducted by the message handler).
func (d *PowDecorator) routePoWTx(ctx sdk.Context, pubkey []byte, params coretypes.Params, msgName string) (canPoW bool, err error) {
	allowed, _, lerr := d.canUsePoW(ctx, pubkey)
	if lerr != nil {
		ctx.Logger().Error("PoW: profile decode failure (rejecting tx, peers will reject identically)",
			"msg", msgName, "err", lerr.Error())
		return false, lerr
	}
	if !allowed {
		if rerr := d.checkReserveOrDowngrade(ctx, pubkey, params); rerr != nil {
			ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", msgName, "err", rerr.Error())
			return false, rerr
		}
		return false, nil
	}
	return true, nil
}

// checkReserveOrDowngrade checks if a paid user has sufficient reserve for gas.
// If reserve is insufficient, downgrades user to free tier and returns an error.
// Returns nil if user has sufficient reserve or is already free tier.
func (d *PowDecorator) checkReserveOrDowngrade(ctx sdk.Context, pubkey []byte, params coretypes.Params) error {
	if len(pubkey) != 33 {
		return nil
	}
	var cpk cryptotypes.PubKey
	cpk.Key = pubkey
	addrBytes := sdk.AccAddress(cpk.Address())
	addr, _ := bech32.ConvertAndEncode(AccountAddressPrefix, addrBytes)

	bz, found, gerr := d.Keeper.GetProfileCore(ctx, addr)
	if gerr != nil {
		return fmt.Errorf("CONSENSUS_FATAL:PROFILE_GET addr=%s: %w", addr, gerr)
	}
	if !found {
		return nil
	}

	var core coretypes.ProfileCore
	if err := json.Unmarshal(bz, &core); err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:PROFILE_DECODE addr=%s bytes=%d: %w", addr, len(bz), err)
	}

	// Free users don't need reserve check
	if core.Level == 0 {
		return nil
	}

	// Admins (level >= 100) don't need reserve, they're manually appointed
	if core.Level >= 100 {
		return nil
	}

	// Calculate minimum required reserve (at least one tx worth)
	minReserve := params.RelayMinGasPrice // Minimum 1 gas unit worth
	if minReserve == 0 {
		minReserve = 1
	}

	if core.ReserveFunds >= minReserve {
		return nil // Sufficient reserve
	}

	// Insufficient reserve - downgrade to free tier
	previousLevel := core.Level
	ctx.Logger().Warn("checkReserveOrDowngrade: insufficient reserve, downgrading to free tier",
		"owner", addr,
		"level", core.Level,
		"reserve", core.ReserveFunds,
		"min_required", minReserve)

	// Remove subscription index
	if core.SubscriptionExpiry > 0 {
		if err := d.Keeper.RemoveSubscription(ctx, addr, core.SubscriptionExpiry); err != nil {
			return fmt.Errorf("checkReserveOrDowngrade: remove subscription failed: %w", err)
		}
	}

	// Burn any remaining reserve
	if core.ReserveFunds > 0 {
		if err := d.Keeper.BurnFromModuleAmount(ctx, core.ReserveFunds); err != nil {
			return fmt.Errorf("checkReserveOrDowngrade: burn reserve failed: %w", err)
		}
	}

	// Downgrade to free tier
	core.Level = 0
	core.ReserveFunds = 0
	core.SubscriptionExpiry = 0
	core.AutoRenew = false

	// Save updated profile
	newBz, err := json.Marshal(core)
	if err != nil {
		return fmt.Errorf("failed to marshal profile: %w", err)
	}
	if err := d.Keeper.SetProfileCore(ctx, addr, newBz); err != nil {
		return fmt.Errorf("failed to save profile: %w", err)
	}

	// Emit event for indexer
	ctx.EventManager().EmitEvent(
		sdk.NewEvent(
			"subscription_expired",
			sdk.NewAttribute("address", addr),
			sdk.NewAttribute("previous_level", fmt.Sprintf("%d", previousLevel)),
			sdk.NewAttribute("reason", "insufficient_reserve"),
		),
	)

	return fmt.Errorf("insufficient reserve (%d < %d), subscription terminated - please use PoW or top up", core.ReserveFunds, minReserve)
}

func (d *PowDecorator) AnteHandle(ctx sdk.Context, tx sdk.Tx, simulate bool, next sdk.AnteHandler) (sdk.Context, error) {
	// Refresh params from the blockchain state.
	params := d.Keeper.GetParams(ctx)

	// chainLastID is the hash of the immediately-previous committed block.
	// This is always accepted by the equality branch of the PoW validator;
	// it is also already prepended to the on-chain recent-block-hashes
	// window by BeginBlock so older envelopes within the window pass the
	// list-check branch.
	chainLastID := strings.ToLower(hex.EncodeToString(ctx.BlockHeader().LastBlockId.Hash))

	// lookupHash queries the on-chain recent-block-hashes window. The
	// closure captures the ABCI context so the validator stays a pure
	// function of (canonical bytes, header, on-chain state).
	lookupHash := func(h string) (bool, error) { return d.recentHashSeen(ctx, h) }

	// Enforce last_block_hash even in CheckTx so stale/invalid PoW fails fast and doesn't linger
	skipHashCheck := false

	// Current and previous difficulty steps and grace period
	currentDifficulty := d.Keeper.GetCurrentDifficulty(ctx)
	prevDifficulty := d.Keeper.GetPreviousDifficulty(ctx)
	lastChange := d.Keeper.GetLastDifficultyChangeHeight(ctx)
	gracePeriod := params.PowDifficultyAllowance
	baseBits := params.MinDifficulty
	powFactor := params.PowDifficultyStep

	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()

	for _, msg := range tx.GetMsgs() {
		switch m := msg.(type) {
		case *coretypes.MsgSubscribe:
			// MsgSubscribe NEVER allows PoW - must pay with tokens
			if m.EnvelopePow > 0 {
				ctx.Logger().Error("PoW: MsgSubscribe cannot use PoW, must pay with tokens")
				return ctx, fmt.Errorf("MsgSubscribe cannot use PoW, must pay with tokens")
			}
			// Skip PoW validation entirely for subscribe (handled by handler)

		case *coretypes.MsgSetAutoRenewal:
			if m.Authority == govAuthority {
				continue
			}
			// MsgSetAutoRenewal NEVER allows PoW - must pay with reserve
			if m.EnvelopePow > 0 {
				ctx.Logger().Error("PoW: MsgSetAutoRenewal cannot use PoW, must pay with reserve")
				return ctx, fmt.Errorf("MsgSetAutoRenewal cannot use PoW, must pay with reserve")
			}
			// Paid users must have sufficient reserve for relayed gas
			if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
				ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgSetAutoRenewal", "err", err.Error())
				return ctx, err
			}
			// Skip PoW validation entirely for set_auto_renewal; gas is covered via reserve

		case *coretypes.MsgPost:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgPost")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForPost(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgPost", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgVote:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgVote")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForVote(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgVote", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgEdit:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgEdit")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForEdit(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgEdit", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgAnnotate:
			if m.Authority == govAuthority {
				continue
			}
			if m.EnvelopeDifficulty > 0 || m.EnvelopePow > 0 {
				ctx.Logger().Error("PoW: MsgAnnotate cannot use PoW")
				return ctx, fmt.Errorf("MsgAnnotate cannot use PoW")
			}
			if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
				ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgAnnotate", "err", err.Error())
				return ctx, err
			}

		case *coretypes.MsgSetUsername:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgSetUsername")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForSetUsername(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgSetUsername", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgSetBiography:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgSetBiography")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForSetBiography(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgSetBiography", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgDelete:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgDelete")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForDelete(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgDelete", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgDeleteUser:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgDeleteUser")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForDeleteUser(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgDeleteUser", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgSendTokens:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgSendTokens")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForSendTokens(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgSendTokens", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgAward:
			if m.Authority == govAuthority {
				continue
			}
			if m.EnvelopePow > 0 || m.EnvelopeDifficulty > 0 {
				return ctx, fmt.Errorf("MsgAward cannot use PoW")
			}

		case *coretypes.MsgBridgeBurn:
			if m.Authority == govAuthority {
				continue
			}
			if m.EnvelopePow > 0 || m.EnvelopeDifficulty > 0 {
				ctx.Logger().Error("PoW: MsgBridgeBurn cannot use PoW", "pow", m.EnvelopePow, "difficulty", m.EnvelopeDifficulty)
				return ctx, fmt.Errorf("MsgBridgeBurn cannot use PoW")
			}
			ctx.Logger().Debug("PoW: skipped for MsgBridgeBurn", "owner", deriveAddrFromPubKey(m.EnvelopePubkey), "dest_chain", m.DestinationChain)

		case *coretypes.MsgEnableAgent:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgEnableAgent")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForEnableAgent(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgEnableAgent", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgDisableAgent:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgDisableAgent")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForDisableAgent(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgDisableAgent", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgSetAgents:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgSetAgents")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForSetAgents(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgSetAgents", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgFollowUser:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgFollowUser")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForFollowUser(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgFollowUser", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgUnfollowUser:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgUnfollowUser")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForUnfollowUser(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgUnfollowUser", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgFollowTopic:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgFollowTopic")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForFollowTopic(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgFollowTopic", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgUnfollowTopic:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgUnfollowTopic")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForUnfollowTopic(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgUnfollowTopic", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgBlockPost:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgBlockPost")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForBlockPost(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgBlockPost", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgUnblockPost:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgUnblockPost")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForUnblockPost(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgUnblockPost", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgBlockUser:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgBlockUser")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForBlockUser(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgBlockUser", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgUnblockUser:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgUnblockUser")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForUnblockUser(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgUnblockUser", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgBlockTopic:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgBlockTopic")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForBlockTopic(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgBlockTopic", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		case *coretypes.MsgUnblockTopic:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgUnblockTopic")
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForUnblockTopic(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, lookupHash, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(), baseBits, powFactor); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgUnblockTopic", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
				}
			}

		default:
			// ignore others
		}
	}

	return next(ctx, tx, simulate)
}

// (legacy helpers removed)

func deriveAddrFromPubKey(pk []byte) string {
	if len(pk) != 33 {
		return ""
	}
	var cpk cryptotypes.PubKey
	cpk.Key = pk
	addr, err := bech32.ConvertAndEncode(AccountAddressPrefix, sdk.AccAddress(cpk.Address()))
	if err != nil {
		return ""
	}
	return addr
}

// New PoW helpers that build canonical bytes (reuse canonWriter from ante_metasig.go)
func buildCanonForPost(m *coretypes.MsgPost) []byte {
	cw := newCanonWriter("MsgPost")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	// envelope_pow (field 5) is NOT included - it's appended separately during PoW validation
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	cw.writeString(101, m.Topic)
	cw.writeString(102, m.Title)
	cw.writeString(103, m.Content)
	cw.writeString(104, m.Tag)
	for _, media := range m.Media {
		cw.writeString(105, media)
	}
	return cw.buf
}

func buildCanonForVote(m *coretypes.MsgVote) []byte {
	cw := newCanonWriter("MsgVote")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	// envelope_pow (field 5) is NOT included - it's appended separately during PoW validation
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	cw.writeUvarint(101, uint64(uint32(m.Direction)))
	return cw.buf
}

func buildCanonForSetUsername(m *coretypes.MsgSetUsername) []byte {
	cw := newCanonWriter("MsgSetUsername")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	// envelope_pow (field 5) is NOT included - it's appended separately during PoW validation
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	cw.writeString(101, m.Username)
	return cw.buf
}

func buildCanonForSetBiography(m *coretypes.MsgSetBiography) []byte {
	cw := newCanonWriter("MsgSetBiography")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	cw.writeString(101, m.Biography)
	return cw.buf
}

func buildCanonForDelete(m *coretypes.MsgDelete) []byte {
	cw := newCanonWriter("MsgDelete")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	// envelope_pow (field 5) is NOT included - it's appended separately during PoW validation
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	return cw.buf
}

func buildCanonForDeleteUser(m *coretypes.MsgDeleteUser) []byte {
	cw := newCanonWriter("MsgDeleteUser")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	return cw.buf
}

func buildCanonForSendTokens(m *coretypes.MsgSendTokens) []byte {
	cw := newCanonWriter("MsgSendTokens")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	// envelope_pow (field 5) is NOT included - it's appended separately during PoW validation
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Sender)
	cw.writeString(101, m.Target)
	cw.writeUvarint(102, m.Amount)
	return cw.buf
}

func buildCanonForAward(m *coretypes.MsgAward) []byte {
	cw := newCanonWriter("MsgAward")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	cw.writeString(101, m.AwardType)
	return cw.buf
}

func buildCanonForBridgeBurn(m *coretypes.MsgBridgeBurn) []byte {
	cw := newCanonWriter("MsgBridgeBurn")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	// envelope_pow (field 5) is NOT included - it's appended separately during PoW validation
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.DestinationChain)
	cw.writeString(101, m.DestinationAddress)
	cw.writeUvarint(102, m.Amount)
	return cw.buf
}

func buildCanonForEnableAgent(m *coretypes.MsgEnableAgent) []byte {
	cw := newCanonWriter("MsgEnableAgent")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	cw.writeString(101, m.Agent)
	return cw.buf
}

func buildCanonForDisableAgent(m *coretypes.MsgDisableAgent) []byte {
	cw := newCanonWriter("MsgDisableAgent")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	cw.writeString(101, m.Agent)
	return cw.buf
}

func buildCanonForSetAgents(m *coretypes.MsgSetAgents) []byte {
	cw := newCanonWriter("MsgSetAgents")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	for _, agent := range m.Agents {
		cw.writeString(101, agent)
	}
	return cw.buf
}

func buildCanonForFollowUser(m *coretypes.MsgFollowUser) []byte {
	cw := newCanonWriter("MsgFollowUser")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	cw.writeString(101, m.User)
	return cw.buf
}

func buildCanonForUnfollowUser(m *coretypes.MsgUnfollowUser) []byte {
	cw := newCanonWriter("MsgUnfollowUser")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	cw.writeString(101, m.User)
	return cw.buf
}

func buildCanonForFollowTopic(m *coretypes.MsgFollowTopic) []byte {
	cw := newCanonWriter("MsgFollowTopic")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	cw.writeString(101, m.Topic)
	return cw.buf
}

func buildCanonForUnfollowTopic(m *coretypes.MsgUnfollowTopic) []byte {
	cw := newCanonWriter("MsgUnfollowTopic")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	cw.writeString(101, m.Topic)
	return cw.buf
}

func buildCanonForBlockPost(m *coretypes.MsgBlockPost) []byte {
	cw := newCanonWriter("MsgBlockPost")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	return cw.buf
}

func buildCanonForUnblockPost(m *coretypes.MsgUnblockPost) []byte {
	cw := newCanonWriter("MsgUnblockPost")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	return cw.buf
}

func buildCanonForBlockUser(m *coretypes.MsgBlockUser) []byte {
	cw := newCanonWriter("MsgBlockUser")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	return cw.buf
}

func buildCanonForUnblockUser(m *coretypes.MsgUnblockUser) []byte {
	cw := newCanonWriter("MsgUnblockUser")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	return cw.buf
}

func buildCanonForBlockTopic(m *coretypes.MsgBlockTopic) []byte {
	cw := newCanonWriter("MsgBlockTopic")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	cw.writeString(101, m.Topic)
	return cw.buf
}

func buildCanonForUnblockTopic(m *coretypes.MsgUnblockTopic) []byte {
	cw := newCanonWriter("MsgUnblockTopic")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	cw.writeString(101, m.Topic)
	return cw.buf
}

func buildCanonForEdit(m *coretypes.MsgEdit) []byte {
	cw := newCanonWriter("MsgEdit")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	// envelope_pow (field 5) is NOT included - it's appended separately during PoW validation
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeString(100, m.Target)
	cw.writeString(101, m.Topic)
	cw.writeString(102, m.Title)
	cw.writeString(103, m.Content)
	cw.writeString(104, m.Tag)
	cw.writeString(105, m.Override)
	for _, mediaItem := range m.Media {
		cw.writeString(106, mediaItem)
	}
	return cw.buf
}

func buildCanonForSubscribe(m *coretypes.MsgSubscribe) []byte {
	cw := newCanonWriter("MsgSubscribe")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	// envelope_pow (field 5) is NOT used for subscribe (no PoW allowed)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(7, m.EnvelopeNonce)
	cw.writeUvarint(100, uint64(m.Level))
	if m.Target != "" {
		cw.writeString(101, m.Target)
	}
	return cw.buf
}

// bigOne and bigBaseFactor are pre-allocated for target computation.
var (
	bigOne        = big.NewInt(1)
	bigBaseFactor = big.NewInt(int64(corekeeper.BaseDifficultyFactor))
	bigMaxHash    = new(big.Int).Lsh(bigOne, 256) // 2^256 (used as shift base)
)

func computeDifficultyFactor(powFactor float64, difficultySteps uint64) (uint64, error) {
	if math.IsNaN(powFactor) || math.IsInf(powFactor, 0) || powFactor <= 0 || powFactor > 1 {
		return 0, fmt.Errorf("invalid pow_factor: %v", powFactor)
	}
	if corekeeper.BaseDifficultyFactor == 0 {
		return 0, fmt.Errorf("invalid base difficulty factor")
	}
	if difficultySteps == 0 {
		return corekeeper.BaseDifficultyFactor, nil
	}
	if difficultySteps > corekeeper.MaxSafeDifficultySteps {
		return corekeeper.MaxSafeDifficultyFactor, nil
	}
	pow := math.Pow(1+powFactor, float64(difficultySteps))
	if math.IsNaN(pow) || math.IsInf(pow, 0) {
		return corekeeper.MaxSafeDifficultyFactor, nil
	}
	factorFloat := float64(corekeeper.BaseDifficultyFactor) * pow
	if factorFloat > float64(corekeeper.MaxSafeDifficultyFactor) {
		return corekeeper.MaxSafeDifficultyFactor, nil
	}
	factor := uint64(math.Round(factorFloat))
	if factor < corekeeper.BaseDifficultyFactor {
		return corekeeper.BaseDifficultyFactor, nil
	}
	return factor, nil
}

// computeTarget returns base_target * base_factor / effective_factor where base_target = 2^(256-pow_base_bits).
func computeTarget(baseBits uint64, difficultySteps uint64, powFactor float64) (*big.Int, error) {
	difficultyFactor, err := computeDifficultyFactor(powFactor, difficultySteps)
	if err != nil {
		return nil, err
	}
	baseTarget := new(big.Int).Rsh(bigMaxHash, uint(baseBits))
	effTarget := new(big.Int).Mul(baseTarget, bigBaseFactor)
	effTarget.Div(effTarget, new(big.Int).SetUint64(difficultyFactor))
	return effTarget, nil
}

// validatePoWBytesArgon2 computes Argon2id(password=canonical||":"||uvarint(pow), salt=last_block_hash bytes)
// and requires hash <= target derived from difficulty steps and pow_base_bits (with grace period).
//
// The last_block_hash check accepts:
//   1. Equality with the current LastBlockId (most common path), OR
//   2. Membership in the on-chain recent-block-hashes window via lookupHash.
//
// lookupHash MUST be a deterministic, state-derived predicate (not a process-
// local cache) to ensure all peers and restarted nodes agree on acceptance.
// Errors from lookupHash propagate so callers can reject the tx; a silent
// "false" would mask a state-read failure and produce divergence.
func validatePoWBytesArgon2(canonical []byte, lastBlockHash []byte, difficulty uint64, pow uint64, currentLastID string, lookupHash func(string) (bool, error), skipHashCheck bool, required uint64, prev uint64, lastChange int64, gracePeriod uint64, currentHeight int64, baseBits uint64, powFactor float64) error {
	if difficulty > corekeeper.MaxSafeDifficultySteps {
		return fmt.Errorf("invalid difficulty: exceeds max safe value")
	}
	minRequired := required
	if gracePeriod > 0 && lastChange > 0 && currentHeight-lastChange <= int64(gracePeriod) {
		if prev < minRequired {
			minRequired = prev
		}
	}
	// Effective threshold is the max of declared difficulty steps and chain-required minimum
	effectiveRequired := difficulty
	if effectiveRequired < minRequired {
		effectiveRequired = minRequired
	}
	var tmp [10]byte
	n := binary.PutUvarint(tmp[:], pow)
	guess := make([]byte, 0, len(canonical)+1+n)
	guess = append(guess, canonical...)
	guess = append(guess, ':')
	guess = append(guess, tmp[:n]...)
	// Salt is the raw block hash bytes
	salt := lastBlockHash
	if len(salt) == 0 {
		salt = []byte{}
	}
	// Parameters tuned for mobile/browser parity
	sum := argon2.IDKey(guess, salt, 1, 4096, 1, 32)
	// Target-based comparison: hash must be <= base_target * base_factor / effectiveRequired
	effTarget, err := computeTarget(baseBits, effectiveRequired, powFactor)
	if err != nil {
		return err
	}
	hashInt := new(big.Int).SetBytes(sum)
	if hashInt.Cmp(effTarget) > 0 {
		return fmt.Errorf("insufficient proof of work")
	}
	if skipHashCheck || strings.TrimSpace(currentLastID) == "" {
		return nil
	}
	// Compare block hash as lowercase hex
	lb := strings.ToLower(hex.EncodeToString(lastBlockHash))
	if lb == strings.ToLower(currentLastID) {
		return nil
	}
	if lookupHash == nil {
		return fmt.Errorf("invalid last_block_hash")
	}
	seen, lerr := lookupHash(lb)
	if lerr != nil {
		return fmt.Errorf("recent-block-hash window read failed: %w", lerr)
	}
	if !seen {
		return fmt.Errorf("invalid last_block_hash")
	}
	return nil
}
