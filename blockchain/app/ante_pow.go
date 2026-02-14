package app

import (
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math/big"
	"strings"
	"sync"

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
//	leading zero bits(challenge) >= difficulty
//	last_block_hash matches one of the last Window committed block hashes (case-insensitive)
//	difficulty >= current dynamic difficulty (prevents spam with artificially low difficulty)
//
// The last_block_hash equality check is skipped for CheckTx (mempool) where header info may be
// unavailable; it is enforced during DeliverTx.
type PowDecorator struct {
	// Window is how many recent committed block hashes to accept (from params)
	Window uint32
	// DefaultDifficulty is the fallback difficulty from params
	DefaultDifficulty uint64
	// MinFee, when provided in the tx fee with same denom and amount >=, skips PoW entirely
	MinFee sdk.Coin
	// Keeper provides access to dynamic difficulty and params
	Keeper corekeeper.Keeper

	mu     sync.Mutex
	recent []string // most-recent-first, lowercase hex strings of block IDs
}

func (d *PowDecorator) remember(hashLower string) {
	d.mu.Lock()
	defer d.mu.Unlock()
	if hashLower == "" {
		return
	}
	if len(d.recent) == 0 || d.recent[0] != hashLower {
		// prepend newest
		d.recent = append([]string{hashLower}, d.recent...)
		// trim
		limit := int(d.Window)
		if limit <= 0 {
			limit = 60
		}
		if len(d.recent) > limit {
			d.recent = d.recent[:limit]
		}
	}
}

func (d *PowDecorator) seen(hash string) bool {
	cmp := strings.ToLower(strings.TrimSpace(hash))
	if cmp == "" {
		return false
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	for _, h := range d.recent {
		if h == cmp {
			return true
		}
	}
	return false
}

// getUserLevel returns user level for the address derived from pubkey
func (d *PowDecorator) getUserLevel(ctx sdk.Context, pubkey []byte) (level int, addr string) {
	if len(pubkey) != 33 {
		return 0, ""
	}
	var cpk cryptotypes.PubKey
	cpk.Key = pubkey
	addrBytes := sdk.AccAddress(cpk.Address())
	addr, _ = bech32.ConvertAndEncode(AccountAddressPrefix, addrBytes)

	// Get profile core for level (only need Level, avoid loading lists)
	if bz, found, _ := d.Keeper.GetProfileCore(ctx, addr); found {
		var core coretypes.ProfileCore
		if err := json.Unmarshal(bz, &core); err == nil {
			level = int(core.Level)
		}
	}

	return level, addr
}

// canUsePoW checks if a user can use PoW instead of gas fees
// Returns true if PoW is allowed, false if user must pay gas
// Only free tier (level 0) can use PoW; paid users use their escrowed reserve for gas
func (d *PowDecorator) canUsePoW(ctx sdk.Context, pubkey []byte) (allowed bool, reason string) {
	level, addr := d.getUserLevel(ctx, pubkey)

	// Free users (level 0) can always use PoW
	if level == 0 {
		return true, "free tier"
	}

	// Paid users (level >= 1) must use their reserve for gas, not PoW
	return false, fmt.Sprintf("paid user (level=%d) must use reserve for gas, addr=%s", level, addr)
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

	bz, found, _ := d.Keeper.GetProfileCore(ctx, addr)
	if !found {
		return nil // No profile, treat as free tier
	}

	var core coretypes.ProfileCore
	if err := json.Unmarshal(bz, &core); err != nil {
		return nil
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
	ctx.Logger().Warn("checkReserveOrDowngrade: insufficient reserve, downgrading to free tier",
		"owner", addr,
		"level", core.Level,
		"reserve", core.ReserveFunds,
		"min_required", minReserve)

	// Remove subscription index
	if core.SubscriptionExpiry > 0 {
		_ = d.Keeper.RemoveSubscription(ctx, addr, core.SubscriptionExpiry)
	}

	// Burn any remaining reserve
	if core.ReserveFunds > 0 {
		_ = d.Keeper.BurnFromModuleAmount(ctx, core.ReserveFunds)
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
			sdk.NewAttribute("previous_level", fmt.Sprintf("%d", core.Level)),
			sdk.NewAttribute("reason", "insufficient_reserve"),
		),
	)

	return fmt.Errorf("insufficient reserve (%d < %d), subscription terminated - please use PoW or top up", core.ReserveFunds, minReserve)
}

func (d *PowDecorator) AnteHandle(ctx sdk.Context, tx sdk.Tx, simulate bool, next sdk.AnteHandler) (sdk.Context, error) {
	// Refresh params from the blockchain state
	params := d.Keeper.GetParams(ctx)
	d.Window = uint32(params.BlockHashWindow)
	// Use current dynamic difficulty factor (1000 = base)
	d.DefaultDifficulty = d.Keeper.GetCurrentDifficulty(ctx)

	// derive last committed block id hash from header and remember it
	chainLastID := strings.ToLower(hex.EncodeToString(ctx.BlockHeader().LastBlockId.Hash))
	d.remember(chainLastID)

	// Enforce last_block_hash even in CheckTx so stale/invalid PoW fails fast and doesn't linger
	skipHashCheck := false

	// Current and previous difficulty factor and allowance
	currentDifficulty := d.Keeper.GetCurrentDifficulty(ctx)
	prevDifficulty := d.Keeper.GetPreviousDifficulty(ctx)
	lastChange := d.Keeper.GetLastDifficultyChangeHeight(ctx)
	allowance := params.PowDifficultyAllowance
	minDiffBits := params.MinDifficulty

	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()

	for _, msg := range tx.GetMsgs() {
		switch m := msg.(type) {
		case *coretypes.MsgUpgradeLevel:
			// MsgUpgradeLevel NEVER allows PoW - must pay with tokens
			if m.EnvelopePow > 0 {
				ctx.Logger().Error("PoW: MsgUpgradeLevel cannot use PoW, must pay with tokens")
				return ctx, fmt.Errorf("MsgUpgradeLevel cannot use PoW, must pay with tokens")
			}
			// Skip PoW validation entirely for upgrade level (handled by handler)

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
			// Check if user can use PoW based on tier/balance
			if allowed, _ := d.canUsePoW(ctx, m.EnvelopePubkey); !allowed {
				// Paid user - check reserve before allowing tx
				if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
					ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgPost", "err", err.Error())
					return ctx, err
				}
				continue // Skip PoW validation, user pays gas from reserve
			}
			canon := buildCanonForPost(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, d, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, allowance, ctx.BlockHeight(), minDiffBits); err != nil {
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
			if allowed, _ := d.canUsePoW(ctx, m.EnvelopePubkey); !allowed {
				if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
					ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgVote", "err", err.Error())
					return ctx, err
				}
				continue
			}
			canon := buildCanonForVote(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, d, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, allowance, ctx.BlockHeight(), minDiffBits); err != nil {
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
			if allowed, _ := d.canUsePoW(ctx, m.EnvelopePubkey); !allowed {
				if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
					ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgEdit", "err", err.Error())
					return ctx, err
				}
				continue
			}
			canon := buildCanonForEdit(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, d, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, allowance, ctx.BlockHeight(), minDiffBits); err != nil {
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

		case *coretypes.MsgSetUsername:
			if m.Authority == govAuthority {
				continue
			}
			if allowed, _ := d.canUsePoW(ctx, m.EnvelopePubkey); !allowed {
				if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
					ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgSetUsername", "err", err.Error())
					return ctx, err
				}
				continue
			}
			canon := buildCanonForSetUsername(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, d, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, allowance, ctx.BlockHeight(), minDiffBits); err != nil {
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

		case *coretypes.MsgDelete:
			if m.Authority == govAuthority {
				continue
			}
			if allowed, _ := d.canUsePoW(ctx, m.EnvelopePubkey); !allowed {
				if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
					ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgDelete", "err", err.Error())
					return ctx, err
				}
				continue
			}
			canon := buildCanonForDelete(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, d, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, allowance, ctx.BlockHeight(), minDiffBits); err != nil {
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

		case *coretypes.MsgSendTokens:
			if m.Authority == govAuthority {
				continue
			}
			if allowed, _ := d.canUsePoW(ctx, m.EnvelopePubkey); !allowed {
				if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
					ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgSendTokens", "err", err.Error())
					return ctx, err
				}
				continue
			}
			canon := buildCanonForSendTokens(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, d, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, allowance, ctx.BlockHeight(), minDiffBits); err != nil {
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

		case *coretypes.MsgBridgeBurn:
			if m.Authority == govAuthority {
				continue
			}
		if m.EnvelopePow > 0 || m.EnvelopeDifficulty > 0 {
			ctx.Logger().Error("PoW: MsgBridgeBurn cannot use PoW", "pow", m.EnvelopePow, "difficulty", m.EnvelopeDifficulty)
			return ctx, fmt.Errorf("MsgBridgeBurn cannot use PoW")
		}
		ctx.Logger().Debug("PoW: skipped for MsgBridgeBurn", "owner", deriveAddrFromPubKey(m.EnvelopePubkey), "dest_chain", m.DestinationChain)

		case *coretypes.MsgFollowModerator:
			if m.Authority == govAuthority {
				continue
			}
			if allowed, _ := d.canUsePoW(ctx, m.EnvelopePubkey); !allowed {
				if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
					ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgFollowModerator", "err", err.Error())
					return ctx, err
				}
				continue
			}
			canon := buildCanonForFollowModerator(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, d, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, allowance, ctx.BlockHeight(), minDiffBits); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgFollowModerator", "err", err.Error())
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

		case *coretypes.MsgUnfollowModerator:
			if m.Authority == govAuthority {
				continue
			}
			if allowed, _ := d.canUsePoW(ctx, m.EnvelopePubkey); !allowed {
				if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
					ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgUnfollowModerator", "err", err.Error())
					return ctx, err
				}
				continue
			}
			canon := buildCanonForUnfollowModerator(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, d, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, allowance, ctx.BlockHeight(), minDiffBits); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgUnfollowModerator", "err", err.Error())
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
			if allowed, _ := d.canUsePoW(ctx, m.EnvelopePubkey); !allowed {
				if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
					ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgFollowUser", "err", err.Error())
					return ctx, err
				}
				continue
			}
			canon := buildCanonForFollowUser(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, d, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, allowance, ctx.BlockHeight(), minDiffBits); err != nil {
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
			if allowed, _ := d.canUsePoW(ctx, m.EnvelopePubkey); !allowed {
				if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
					ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgUnfollowUser", "err", err.Error())
					return ctx, err
				}
				continue
			}
			canon := buildCanonForUnfollowUser(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, d, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, allowance, ctx.BlockHeight(), minDiffBits); err != nil {
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
			if allowed, _ := d.canUsePoW(ctx, m.EnvelopePubkey); !allowed {
				if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
					ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgFollowTopic", "err", err.Error())
					return ctx, err
				}
				continue
			}
			canon := buildCanonForFollowTopic(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, d, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, allowance, ctx.BlockHeight(), minDiffBits); err != nil {
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
			if allowed, _ := d.canUsePoW(ctx, m.EnvelopePubkey); !allowed {
				if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
					ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgUnfollowTopic", "err", err.Error())
					return ctx, err
				}
				continue
			}
			canon := buildCanonForUnfollowTopic(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, d, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, allowance, ctx.BlockHeight(), minDiffBits); err != nil {
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
			if allowed, _ := d.canUsePoW(ctx, m.EnvelopePubkey); !allowed {
				if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
					ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgBlockPost", "err", err.Error())
					return ctx, err
				}
				continue
			}
			canon := buildCanonForBlockPost(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, d, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, allowance, ctx.BlockHeight(), minDiffBits); err != nil {
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
			if allowed, _ := d.canUsePoW(ctx, m.EnvelopePubkey); !allowed {
				if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
					ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgUnblockPost", "err", err.Error())
					return ctx, err
				}
				continue
			}
			canon := buildCanonForUnblockPost(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, d, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, allowance, ctx.BlockHeight(), minDiffBits); err != nil {
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
			if allowed, _ := d.canUsePoW(ctx, m.EnvelopePubkey); !allowed {
				if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
					ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgBlockUser", "err", err.Error())
					return ctx, err
				}
				continue
			}
			canon := buildCanonForBlockUser(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, d, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, allowance, ctx.BlockHeight(), minDiffBits); err != nil {
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
			if allowed, _ := d.canUsePoW(ctx, m.EnvelopePubkey); !allowed {
				if err := d.checkReserveOrDowngrade(ctx, m.EnvelopePubkey, params); err != nil {
					ctx.Logger().Error("PoW: paid user has insufficient reserve", "msg", "MsgUnblockUser", "err", err.Error())
					return ctx, err
				}
				continue
			}
			canon := buildCanonForUnblockUser(m)
			if err := validatePoWBytesArgon2(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, chainLastID, d, skipHashCheck, currentDifficulty, prevDifficulty, lastChange, allowance, ctx.BlockHeight(), minDiffBits); err != nil {
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
	cw.writeString(100, m.Target)
	cw.writeString(101, m.Topic)
	cw.writeString(102, m.Title)
	cw.writeString(103, m.Content)
	cw.writeString(104, m.Tag)
	return cw.buf
}

func buildCanonForVote(m *coretypes.MsgVote) []byte {
	cw := newCanonWriter("MsgVote")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	// envelope_pow (field 5) is NOT included - it's appended separately during PoW validation
	cw.writeUvarint(6, m.EnvelopeTimestamp)
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
	cw.writeString(100, m.Target)
	cw.writeString(101, m.Username)
	return cw.buf
}

func buildCanonForDelete(m *coretypes.MsgDelete) []byte {
	cw := newCanonWriter("MsgDelete")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	// envelope_pow (field 5) is NOT included - it's appended separately during PoW validation
	cw.writeUvarint(6, m.EnvelopeTimestamp)
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
	cw.writeString(100, m.Sender)
	cw.writeString(101, m.Target)
	cw.writeUvarint(102, m.Amount)
	return cw.buf
}

func buildCanonForBridgeBurn(m *coretypes.MsgBridgeBurn) []byte {
	cw := newCanonWriter("MsgBridgeBurn")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	// envelope_pow (field 5) is NOT included - it's appended separately during PoW validation
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeString(100, m.DestinationChain)
	cw.writeString(101, m.DestinationAddress)
	cw.writeUvarint(102, m.Amount)
	return cw.buf
}

func buildCanonForFollowModerator(m *coretypes.MsgFollowModerator) []byte {
	cw := newCanonWriter("MsgFollowModerator")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	// envelope_pow (field 5) is NOT included - it's appended separately during PoW validation
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeString(100, m.Target)
	cw.writeString(101, m.Moderator)
	return cw.buf
}

func buildCanonForUnfollowModerator(m *coretypes.MsgUnfollowModerator) []byte {
	cw := newCanonWriter("MsgUnfollowModerator")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	// envelope_pow (field 5) is NOT included - it's appended separately during PoW validation
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeString(100, m.Target)
	cw.writeString(101, m.Moderator)
	return cw.buf
}

func buildCanonForFollowUser(m *coretypes.MsgFollowUser) []byte {
	cw := newCanonWriter("MsgFollowUser")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
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
	cw.writeString(100, m.Target)
	return cw.buf
}

func buildCanonForUnblockPost(m *coretypes.MsgUnblockPost) []byte {
	cw := newCanonWriter("MsgUnblockPost")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeString(100, m.Target)
	return cw.buf
}

func buildCanonForBlockUser(m *coretypes.MsgBlockUser) []byte {
	cw := newCanonWriter("MsgBlockUser")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeString(100, m.Target)
	return cw.buf
}

func buildCanonForUnblockUser(m *coretypes.MsgUnblockUser) []byte {
	cw := newCanonWriter("MsgUnblockUser")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeString(100, m.Target)
	return cw.buf
}

func buildCanonForEdit(m *coretypes.MsgEdit) []byte {
	cw := newCanonWriter("MsgEdit")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	// envelope_pow (field 5) is NOT included - it's appended separately during PoW validation
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeString(100, m.Target)
	cw.writeString(101, m.Topic)
	cw.writeString(102, m.Title)
	cw.writeString(103, m.Content)
	cw.writeString(104, m.Tag)
	cw.writeString(105, m.Override)
	return cw.buf
}

func buildCanonForUpgradeLevel(m *coretypes.MsgUpgradeLevel) []byte {
	cw := newCanonWriter("MsgUpgradeLevel")
	cw.writeBytes(2, m.EnvelopePubkey)
	cw.writeBytes(3, m.EnvelopeBlockHash)
	cw.writeUvarint(4, m.EnvelopeDifficulty)
	// envelope_pow (field 5) is NOT used for upgrade level (no PoW allowed)
	cw.writeUvarint(6, m.EnvelopeTimestamp)
	cw.writeUvarint(100, uint64(m.Level))
	return cw.buf
}

// bigOne and big1000 are pre-allocated for target computation.
var (
	bigOne     = big.NewInt(1)
	big1000    = big.NewInt(1000)
	bigMaxHash = new(big.Int).Lsh(bigOne, 256) // 2^256 (used as shift base)
)

// computeTarget returns base_target * 1000 / difficultyFactor where base_target = 2^(256-minDiffBits).
func computeTarget(minDiffBits uint64, difficultyFactor uint64) *big.Int {
	if difficultyFactor < corekeeper.BaseDifficulty {
		difficultyFactor = corekeeper.BaseDifficulty
	}
	baseTarget := new(big.Int).Rsh(bigMaxHash, uint(minDiffBits))
	effTarget := new(big.Int).Mul(baseTarget, big1000)
	effTarget.Div(effTarget, new(big.Int).SetUint64(difficultyFactor))
	return effTarget
}

// validatePoWBytesArgon2 computes Argon2id(password=canonical||":"||uvarint(pow), salt=last_block_hash bytes)
// and requires hash <= target derived from difficulty factor and min_difficulty bits (with allowance window).
func validatePoWBytesArgon2(canonical []byte, lastBlockHash []byte, difficulty uint64, pow uint64, currentLastID string, ring interface{ seen(string) bool }, skipHashCheck bool, required uint64, prev uint64, lastChange int64, allowance uint64, currentHeight int64, minDiffBits uint64) error {
	if difficulty < corekeeper.BaseDifficulty {
		return fmt.Errorf("invalid difficulty: must be >= %d", corekeeper.BaseDifficulty)
	}
	if difficulty > corekeeper.MaxSafeDifficulty {
		return fmt.Errorf("invalid difficulty: exceeds max safe value")
	}
	minRequired := required
	if allowance > 0 && lastChange > 0 && currentHeight-lastChange <= int64(allowance) {
		if prev < minRequired {
			minRequired = prev
		}
	}
	// Effective threshold is the max of declared difficulty factor and chain-required minimum
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
	// Target-based comparison: hash must be <= base_target * 1000 / effectiveRequired
	effTarget := computeTarget(minDiffBits, effectiveRequired)
	hashInt := new(big.Int).SetBytes(sum)
	if hashInt.Cmp(effTarget) > 0 {
		return fmt.Errorf("insufficient pow: hash exceeds target (declared=%d, chain_min=%d, prev=%d, allowance=%d, last_change=%d, current_height=%d, pow=%d, hash_hex=%x, salt_hex=%x)",
			difficulty, required, prev, allowance, lastChange, currentHeight, pow, sum, salt)
	}
	if skipHashCheck || strings.TrimSpace(currentLastID) == "" {
		return nil
	}
	// Compare block hash as lowercase hex
	lb := strings.ToLower(hex.EncodeToString(lastBlockHash))
	if lb != strings.ToLower(currentLastID) && !ring.seen(lb) {
		return fmt.Errorf("invalid last_block_hash")
	}
	return nil
}
