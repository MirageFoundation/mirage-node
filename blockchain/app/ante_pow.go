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
// The last_block_hash check runs in CheckTx and DeliverTx alike, and acceptance
// comes from the on-chain window rather than the header: ABCI 2.0 gives
// FinalizeBlock no LastBlockId, so the header field is always empty. The only
// case where the check is disabled is a window with no real hash in it, which
// means a chain that has not committed its first block yet, because enforcing
// against an empty window would reject every transaction.
//
// The window must span at least params.MaxEnvelopeAge worth of blocks, or it
// becomes a stricter freshness bound than the envelope age check and rejects
// slow clients whose work is still within the advertised age limit.
type PowDecorator struct {
	// Keeper provides access to dynamic difficulty, params, and the on-chain
	// recent-block-hash window.
	Keeper corekeeper.Keeper
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
		return 0, "", fmt.Errorf("invalid envelope_pubkey length: got %d, want 33", len(pubkey))
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
	_, addr, lerr := d.getUserLevel(ctx, pubkey)
	if lerr != nil {
		return false, "", lerr
	}
	paid, perr := d.Keeper.IsEffectivePaid(ctx, addr)
	if perr != nil {
		return false, "", perr
	}
	if !paid {
		return true, "free path", nil
	}
	return false, fmt.Sprintf("effective_paid user must skip PoW, addr=%s", addr), nil
}

// routePoWTx unifies the canUsePoW + checkReserveOrDowngrade decision used by
// every PoW-eligible message branch in AnteHandle.
//
// Returns (canPoW, err):
//   - err != nil: tx must be rejected (profile decode failure or malformed pubkey).
//     The error string is logged with msgName context for triage.
//   - canPoW == true: caller must run validatePoWBytesArgon2.
//   - canPoW == false, err == nil: caller must skip PoW (paid path; gas deducted
//     by the message handler, which also downgrades on exhausted reserve).
func (d *PowDecorator) routePoWTx(ctx sdk.Context, pubkey []byte, params coretypes.Params, msgName string, msgCount uint64) (canPoW bool, err error) {
	allowed, _, lerr := d.canUsePoW(ctx, pubkey)
	if lerr != nil {
		ctx.Logger().Error("PoW: profile decode failure (rejecting tx, peers will reject identically)",
			"msg", msgName, "err", lerr.Error())
		return false, lerr
	}
	if !allowed {
		if rerr := d.checkReserveOrDowngrade(ctx, pubkey, params, msgCount); rerr != nil {
			ctx.Logger().Error("PoW: reserve/profile check failed", "msg", msgName, "err", rerr.Error())
			return false, rerr
		}
		return false, nil
	}
	return true, nil
}

// checkReserveOrDowngrade checks if a paid user has sufficient reserve for gas.
// Ante must NOT reject on insufficient reserve and must NOT mutate state:
// baseapp discards ante mutations when the ante returns an error, which previously
// wedged paid users (M-5). Insufficient reserve is logged here; the durable
// downgrade lives in deductRelayGasFee on the handler path — so this function
// returns nil for the insufficient-reserve case so the tx reaches the handler.
// Returns an error only for CONSENSUS_FATAL profile failures or malformed pubkey.
func (d *PowDecorator) checkReserveOrDowngrade(ctx sdk.Context, pubkey []byte, params coretypes.Params, msgCount uint64) error {
	if len(pubkey) != 33 {
		return fmt.Errorf("invalid envelope_pubkey length: got %d, want 33", len(pubkey))
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

	// A paid user may submit at most as many messages in one transaction as their
	// reserve can actually pay for.
	//
	// Routing is decided once per message from the level as it stood before any
	// handler ran, and a paid user's PoW is waived at that point. So when message
	// 1 exhausted the reserve, deductRelayGasFee wrote Level = 0 into the shared
	// cache-wrapped store, messages 2..N read level 0 and were charged nothing —
	// while the ante had already waived their proof of work. N was bounded only by
	// transaction size and block gas (review L-5).
	//
	// The single-message case is deliberately left alone: it must still reach the
	// handler so the durable downgrade in deductRelayGasFee can happen. Rejecting
	// it here is what wedged paid users in the earlier M-5, because baseapp
	// discards ante mutations when the ante returns an error. Splitting into
	// separate transactions therefore still works and still downgrades correctly.
	if msgCount > 1 {
		affordable := core.ReserveFunds / minReserve
		if msgCount > affordable {
			ctx.Logger().Error("checkReserveOrDowngrade: transaction carries more messages than the reserve can pay for",
				"owner", addr, "level", core.Level, "reserve", core.ReserveFunds,
				"min_per_msg", minReserve, "messages", msgCount, "affordable", affordable)
			return fmt.Errorf(
				"insufficient reserve: %d messages in one transaction but the reserve covers %d; submit them separately",
				msgCount, affordable)
		}
	}

	if core.ReserveFunds >= minReserve {
		return nil // Sufficient reserve
	}

	ctx.Logger().Warn("checkReserveOrDowngrade: insufficient reserve; allowing tx so handler can downgrade",
		"owner", addr,
		"level", core.Level,
		"reserve", core.ReserveFunds,
		"min_required", minReserve)

	return nil
}

// envelopeMsgCounts counts, per envelope pubkey, how many messages in this
// transaction that pubkey submitted. checkReserveOrDowngrade needs it because
// the reserve is spent per message but routing is decided per message against
// the level before any handler ran (review L-5).
func envelopeMsgCounts(msgs []sdk.Msg) map[string]uint64 {
	counts := make(map[string]uint64, len(msgs))
	for _, m := range msgs {
		carrier, ok := m.(interface{ GetEnvelopePubkey() []byte })
		if !ok {
			continue
		}
		pk := carrier.GetEnvelopePubkey()
		if len(pk) == 0 {
			continue
		}
		counts[string(pk)]++
	}
	return counts
}

func (d *PowDecorator) AnteHandle(ctx sdk.Context, tx sdk.Tx, simulate bool, next sdk.AnteHandler) (sdk.Context, error) {
	// Simulate runs this decorator for its state reads and skips only the Argon2id
	// verification itself, at verifyPoW below.
	//
	// Skipping the whole decorator instead made every gas estimate short by the
	// cost of the reads it performs, so clients sized their gas limit from a
	// simulation that had done less work than execution would and the tx died
	// with "out of gas in location: ReadFlat" in the block. The hashing is the
	// part worth skipping and the part that costs nothing in gas: it is pure CPU.
	//
	// It is worth skipping because Simulate is registered on the gRPC *query*
	// router, so it is reachable via abci_query on the public RPC port whether or
	// not 1317/9090 are published. In simulate mode the SDK installs an infinite
	// gas meter, skips signature verification and deducts no fee, so the request
	// is free. Worse, the nonce is never persisted because the state is discarded
	// — so an attacker computes one set of valid envelopes once and re-simulates
	// it indefinitely, defeating the abort-on-first-failure property that makes
	// the CheckTx path expensive for them and cheap for the node. ~100 messages is
	// ~165ms of CPU and ~400MB of allocation churn per free HTTP request
	// (review M-2).

	// chainLastID is the hash of the immediately-previous committed block, which
	// the equality branch of the PoW validator accepts directly. Under ABCI 2.0
	// it is empty on every path because FinalizeBlock carries no LastBlockId, so
	// acceptance rests entirely on the on-chain window below; the branch is kept
	// because it is correct whenever the field is populated.
	chainLastID := strings.ToLower(hex.EncodeToString(ctx.BlockHeader().LastBlockId.Hash))

	// Refresh params from the blockchain state.
	params := d.Keeper.GetParams(ctx)

	// Read the recent-block-hashes window once per transaction. Reading it here
	// instead of per message keeps the validator a pure function of state that
	// was read exactly once, so every message in a tx is judged against the same
	// window. A read failure propagates: a silent empty window would reject
	// legitimate transactions on this node only, which is the divergence this
	// window exists to prevent.
	recentHashes, err := d.Keeper.GetRecentBlockHashes(ctx)
	if err != nil {
		ctx.Logger().Error("PoW: recent-block-hash window read failed", "height", ctx.BlockHeight(), "err", err)
		return ctx, err
	}
	lookupHash := func(h string) (bool, error) {
		cmp := strings.ToLower(strings.TrimSpace(h))
		if cmp == "" {
			return false, nil
		}
		for _, candidate := range recentHashes {
			if candidate == cmp {
				return true, nil
			}
		}
		return false, nil
	}

	// Staleness is enforced only once the window holds at least one real hash,
	// because enforcing against an empty window would reject every transaction —
	// the failure mode that made the first attempt at this guard unusable. In
	// practice that only covers a chain with no committed block yet: BeginBlock
	// records this block's hash before any tx runs, and it runs after the upgrade
	// handler that clears the stale window (baseapp preBlock precedes
	// beginBlock), so even the upgrade block itself enforces.
	windowReady := false
	for _, h := range recentHashes {
		if strings.TrimSpace(h) != "" {
			windowReady = true
			break
		}
	}
	skipHashCheck := !windowReady
	if skipHashCheck {
		ctx.Logger().Info("PoW: recent-block-hash window empty, last_block_hash not enforced this block",
			"height", ctx.BlockHeight())
	}

	// Current and previous difficulty steps and grace period
	currentDifficulty := d.Keeper.GetCurrentDifficulty(ctx)
	prevDifficulty := d.Keeper.GetPreviousDifficulty(ctx)
	lastChange := d.Keeper.GetLastDifficultyChangeHeight(ctx)
	gracePeriod := params.PowDifficultyAllowance
	baseBits := params.MinDifficulty
	powFactor := params.PowDifficultyStep

	// The one thing simulate does not do. Every read that decides whether PoW is
	// required has already happened by the time this is called, so a simulated
	// transaction is charged exactly what executing it will charge.
	verifyPoW := func(canonical []byte, lastBlockHash []byte, difficulty uint64, pow uint64) error {
		if simulate {
			return nil
		}
		return validatePoWBytesArgon2(canonical, lastBlockHash, difficulty, pow, chainLastID, lookupHash,
			skipHashCheck, currentDifficulty, prevDifficulty, lastChange, gracePeriod, ctx.BlockHeight(),
			baseBits, powFactor)
	}

	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()

	// Reject malformed envelope pubkeys before getUserLevel / PoW routing
	// so we never silently normalize them to free-tier (review L-5).
	// Governance-authority messages skip envelope validation (same as the
	// per-case `continue` below) and may carry empty pubkeys.
	for _, msg := range tx.GetMsgs() {
		if auth, ok := envelopeAuthorityOf(msg); ok && auth == govAuthority {
			continue
		}
		if pk, ok := envelopePubkeyOf(msg); ok {
			if err := requireEnvelopePubkey(pk); err != nil {
				ctx.Logger().Error("PoW: malformed envelope_pubkey", "err", err.Error())
				return ctx, err
			}
		}
	}

	// How many messages each envelope pubkey submitted in this transaction. The
	// reserve is spent per message, but routing is decided per message against the
	// level as it stood before any handler ran, so a paid user could otherwise get
	// every message after the first for free (review L-5).
	msgCounts := envelopeMsgCounts(tx.GetMsgs())

	for _, msg := range tx.GetMsgs() {
		var err error
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
			if m.EnvelopePow > 0 {
				ctx.Logger().Error("PoW: MsgSetAutoRenewal cannot use PoW")
				return ctx, fmt.Errorf("MsgSetAutoRenewal cannot use PoW")
			}
			_, addr, lerr := d.getUserLevel(ctx, m.EnvelopePubkey)
			if lerr != nil {
				ctx.Logger().Error("PoW: profile read failed", "msg", "MsgSetAutoRenewal", "err", lerr.Error())
				return ctx, lerr
			}
			isPaid, perr := d.Keeper.IsEffectivePaid(ctx, addr)
			if perr != nil {
				return ctx, perr
			}
			if !isPaid {
				ctx.Logger().Error("PoW: MsgSetAutoRenewal requires effective_paid", "addr", addr)
				return ctx, fmt.Errorf("MsgSetAutoRenewal requires a subscription")
			}

		case *coretypes.MsgPost:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgPost", msgCounts[string(m.EnvelopePubkey)])
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForPost(m)
			if err := verifyPoW(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgPost", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
					return ctx, err
				}
			}

		case *coretypes.MsgVote:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgVote", msgCounts[string(m.EnvelopePubkey)])
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForVote(m)
			if err := verifyPoW(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgVote", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
					return ctx, err
				}
			}

		case *coretypes.MsgEdit:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgEdit", msgCounts[string(m.EnvelopePubkey)])
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForEdit(m)
			if err := verifyPoW(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgEdit", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
					return ctx, err
				}
			}

		case *coretypes.MsgSetUsername:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgSetUsername", msgCounts[string(m.EnvelopePubkey)])
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForSetUsername(m)
			if err := verifyPoW(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgSetUsername", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
					return ctx, err
				}
			}

		case *coretypes.MsgSetBiography:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgSetBiography", msgCounts[string(m.EnvelopePubkey)])
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForSetBiography(m)
			if err := verifyPoW(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgSetBiography", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
					return ctx, err
				}
			}

		case *coretypes.MsgDelete:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgDelete", msgCounts[string(m.EnvelopePubkey)])
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForDelete(m)
			if err := verifyPoW(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgDelete", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
					return ctx, err
				}
			}

		case *coretypes.MsgDeleteUser:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgDeleteUser", msgCounts[string(m.EnvelopePubkey)])
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForDeleteUser(m)
			if err := verifyPoW(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgDeleteUser", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
					return ctx, err
				}
			}

		case *coretypes.MsgSendTokens:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgSendTokens", msgCounts[string(m.EnvelopePubkey)])
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForSendTokens(m)
			if err := verifyPoW(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgSendTokens", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
					return ctx, err
				}
			}

		case *coretypes.MsgAward:
			if m.Authority == govAuthority {
				continue
			}
			if m.EnvelopePow > 0 || m.EnvelopeDifficulty > 0 {
				return ctx, fmt.Errorf("MsgAward cannot use PoW")
			}

		case *coretypes.MsgFollowUser:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgFollowUser", msgCounts[string(m.EnvelopePubkey)])
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForFollowUser(m)
			if err := verifyPoW(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgFollowUser", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
					return ctx, err
				}
			}

		case *coretypes.MsgUnfollowUser:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgUnfollowUser", msgCounts[string(m.EnvelopePubkey)])
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForUnfollowUser(m)
			if err := verifyPoW(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgUnfollowUser", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
					return ctx, err
				}
			}

		case *coretypes.MsgBlockPost:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgBlockPost", msgCounts[string(m.EnvelopePubkey)])
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForBlockPost(m)
			if err := verifyPoW(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgBlockPost", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
					return ctx, err
				}
			}

		case *coretypes.MsgUnblockPost:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgUnblockPost", msgCounts[string(m.EnvelopePubkey)])
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForUnblockPost(m)
			if err := verifyPoW(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgUnblockPost", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
					return ctx, err
				}
			}

		case *coretypes.MsgBlockUser:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgBlockUser", msgCounts[string(m.EnvelopePubkey)])
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForBlockUser(m)
			if err := verifyPoW(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgBlockUser", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
					return ctx, err
				}
			}

		case *coretypes.MsgUnblockUser:
			if m.Authority == govAuthority {
				continue
			}
			canPoW, err := d.routePoWTx(ctx, m.EnvelopePubkey, params, "MsgUnblockUser", msgCounts[string(m.EnvelopePubkey)])
			if err != nil {
				return ctx, err
			}
			if !canPoW {
				continue
			}
			canon := buildCanonForUnblockUser(m)
			if err := verifyPoW(canon, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow); err != nil {
				ctx.Logger().Error("PoW: validation failed", "msg", "MsgUnblockUser", "err", err.Error())
				return ctx, err
			}
			if ctx.Priority() <= 0 {
				ctx = ctx.WithPriority(int64(1 + m.EnvelopeDifficulty))
			}
			if !ctx.IsCheckTx() && !ctx.IsReCheckTx() {
				if err := d.Keeper.RecordPoWMessage(ctx); err != nil {
					ctx.Logger().Error("PoW: failed to record message", "err", err.Error())
					return ctx, err
				}
			}


		case *coretypes.MsgJoinCommunity:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgJoinCommunity", buildCanonV139("MsgJoinCommunity", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) { w.writeString(100, m.Community) }), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgLeaveCommunity:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgLeaveCommunity", buildCanonV139("MsgLeaveCommunity", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) { w.writeString(100, m.Community) }), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgBlockCommunity:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgBlockCommunity", buildCanonV139("MsgBlockCommunity", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) { w.writeString(100, m.Target); w.writeString(101, m.Community) }), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgUnblockCommunity:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgUnblockCommunity", buildCanonV139("MsgUnblockCommunity", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) { w.writeString(100, m.Target); w.writeString(101, m.Community) }), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgCreateCommunity:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgCreateCommunity", buildCanonV139("MsgCreateCommunity", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeString(101, m.Title); w.writeString(102, m.Description); w.writeString(103, m.OriginalTeamName); w.writeString(104, m.Bio); w.writeString(105, m.Policy)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgSetCommunityMetadata:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgSetCommunityMetadata", buildCanonV139("MsgSetCommunityMetadata", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeString(101, m.Title); w.writeString(102, m.Description)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgTransferCommunity:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgTransferCommunity", buildCanonV139("MsgTransferCommunity", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeString(101, m.NewFounder)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgCreateCurationTeam:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgCreateCurationTeam", buildCanonV139("MsgCreateCurationTeam", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeString(101, m.Name); w.writeString(102, m.Bio); w.writeString(103, m.Policy)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgSetCurationTeamProfile:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgSetCurationTeamProfile", buildCanonV139("MsgSetCurationTeamProfile", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeUvarint(101, m.TeamId); w.writeString(102, m.Name); w.writeString(103, m.Bio); w.writeString(104, m.Policy)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgInviteCurator:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgInviteCurator", buildCanonV139("MsgInviteCurator", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeUvarint(101, m.TeamId); w.writeString(102, m.Target)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgRevokeCuratorInvite:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgRevokeCuratorInvite", buildCanonV139("MsgRevokeCuratorInvite", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeUvarint(101, m.TeamId); w.writeString(102, m.Target)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgAcceptCuratorInvite:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgAcceptCuratorInvite", buildCanonV139("MsgAcceptCuratorInvite", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeUvarint(101, m.TeamId)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgDeclineCuratorInvite:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgDeclineCuratorInvite", buildCanonV139("MsgDeclineCuratorInvite", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeUvarint(101, m.TeamId)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgLeaveCurationTeam:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgLeaveCurationTeam", buildCanonV139("MsgLeaveCurationTeam", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeUvarint(101, m.TeamId)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgRemoveCurator:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgRemoveCurator", buildCanonV139("MsgRemoveCurator", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeUvarint(101, m.TeamId); w.writeString(102, m.Target)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgTransferCurationTeam:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgTransferCurationTeam", buildCanonV139("MsgTransferCurationTeam", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeUvarint(101, m.TeamId); w.writeString(102, m.NewOwner)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgDeleteCurationTeam:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgDeleteCurationTeam", buildCanonV139("MsgDeleteCurationTeam", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeUvarint(101, m.TeamId)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgSetCurationPreference:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgSetCurationPreference", buildCanonV139("MsgSetCurationPreference", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeUvarint(101, uint64(m.Mode)); w.writeUvarint(102, m.PinnedTeamId)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgSetCurationPostHidden:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgSetCurationPostHidden", buildCanonV139("MsgSetCurationPostHidden", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeUvarint(101, m.TeamId); w.writeString(102, m.Target); writeCanonBool(w, 103, m.Hidden)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgSetCurationUserHidden:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgSetCurationUserHidden", buildCanonV139("MsgSetCurationUserHidden", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeUvarint(101, m.TeamId); w.writeString(102, m.Target); writeCanonBool(w, 103, m.Hidden)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgSetCurationThreadLocked:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgSetCurationThreadLocked", buildCanonV139("MsgSetCurationThreadLocked", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeUvarint(101, m.TeamId); w.writeString(102, m.RootHash); writeCanonBool(w, 103, m.Locked)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgSetCurationSubscriberOnly:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgSetCurationSubscriberOnly", buildCanonV139("MsgSetCurationSubscriberOnly", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				w.writeString(100, m.Community); w.writeUvarint(101, m.TeamId); writeCanonBool(w, 102, m.Enabled)
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		case *coretypes.MsgClaimCreatorRewards:
			ctx, err = d.standardPoW(ctx, govAuthority, m.Authority, m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopePow, params, msgCounts[string(m.EnvelopePubkey)], "MsgClaimCreatorRewards", buildCanonV139("MsgClaimCreatorRewards", m.EnvelopePubkey, m.EnvelopeBlockHash, m.EnvelopeDifficulty, m.EnvelopeTimestamp, m.EnvelopeNonce, func(w *canonWriter) {
				for _, id := range m.EpochIds { w.writeUvarint(100, uint64(id)) }
			}), verifyPoW)
			if err != nil {
				return ctx, err
			}
		default:
			return ctx, fmt.Errorf("PowDecorator: unsupported relay message %T", msg)
		}
	}

	return next(ctx, tx, simulate)
}

// requireEnvelopePubkey rejects non-compressed secp256k1 pubkeys before any
// free-tier normalization or PoW routing (review L-5).
func requireEnvelopePubkey(pubkey []byte) error {
	if len(pubkey) != 33 {
		return fmt.Errorf("invalid envelope_pubkey length: got %d, want 33", len(pubkey))
	}
	return nil
}

// envelopeAuthorityOf returns the Authority field for relay-routed messages.
func envelopeAuthorityOf(msg sdk.Msg) (string, bool) {
	if !isRelayMessage(msg) {
		return "", false
	}
	if m, ok := msg.(interface{ GetAuthority() string }); ok {
		return m.GetAuthority(), true
	}
	return "", false
}

// envelopePubkeyOf returns the envelope pubkey for relay-routed messages.
func envelopePubkeyOf(msg sdk.Msg) ([]byte, bool) {
	if !isRelayMessage(msg) {
		return nil, false
	}
	if m, ok := msg.(interface{ GetEnvelopePubkey() []byte }); ok {
		return m.GetEnvelopePubkey(), true
	}
	return nil, false
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
	cw.writeString(101, m.Community)
	cw.writeString(102, m.Title)
	cw.writeString(103, m.Content)
	cw.writeString(104, m.Tag)
	for _, media := range m.Media {
		cw.writeString(105, media)
	}
	cw.writeUvarint(106, uint64(m.ProtocolVersion))
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
	cw.writeString(101, m.Community)
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
	cw.writeUvarint(102, uint64(m.PeriodCount))
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

	// Exact rational arithmetic: factor = round(Base * (1+powFactor)^steps).
	// big.Rat.SetFloat64 is exact for the IEEE754 bit pattern stored in
	// params (protobuf fixed64), so all nodes share the same rational base.
	// Avoids math.Pow float64 / FMA non-determinism across architectures.
	base := new(big.Rat).SetFloat64(powFactor)
	if base == nil {
		return 0, fmt.Errorf("invalid pow_factor: %v", powFactor)
	}
	base.Add(base, big.NewRat(1, 1)) // 1 + powFactor

	maxFactorRat := new(big.Rat).SetUint64(corekeeper.MaxSafeDifficultyFactor)
	baseFactorRat := new(big.Rat).SetUint64(corekeeper.BaseDifficultyFactor)
	// Cap when Base*(1+p)^n would exceed MaxSafe ⇒ (1+p)^n > MaxSafe/Base
	capPow := new(big.Rat).Quo(new(big.Rat).Set(maxFactorRat), baseFactorRat)

	powered := ratPowCapped(base, difficultySteps, capPow)
	if powered == nil {
		return corekeeper.MaxSafeDifficultyFactor, nil
	}

	factorRat := new(big.Rat).Mul(powered, baseFactorRat)
	if factorRat.Cmp(maxFactorRat) > 0 {
		return corekeeper.MaxSafeDifficultyFactor, nil
	}

	factor := roundRatToUint64(factorRat)
	if factor < corekeeper.BaseDifficultyFactor {
		return corekeeper.BaseDifficultyFactor, nil
	}
	if factor > corekeeper.MaxSafeDifficultyFactor {
		return corekeeper.MaxSafeDifficultyFactor, nil
	}
	return factor, nil
}

// ratPowCapped computes base^exp as a rational. Returns nil if the result
// exceeds cap (caller treats that as MaxSafeDifficultyFactor).
func ratPowCapped(base *big.Rat, exp uint64, cap *big.Rat) *big.Rat {
	result := big.NewRat(1, 1)
	b := new(big.Rat).Set(base)
	overCap := new(big.Rat).Add(cap, big.NewRat(1, 1))
	for exp > 0 {
		if exp&1 == 1 {
			result.Mul(result, b)
			if result.Cmp(cap) > 0 {
				return nil
			}
		}
		exp >>= 1
		if exp > 0 {
			b.Mul(b, b)
			if b.Cmp(cap) > 0 {
				b.Set(overCap)
			}
		}
	}
	return result
}

// roundRatToUint64 rounds a non-negative rational half-away-from-zero
// (same as math.Round for positive values).
func roundRatToUint64(r *big.Rat) uint64 {
	if r.Sign() <= 0 {
		return 0
	}
	num := new(big.Int).Set(r.Num())
	den := r.Denom()
	q, rem := new(big.Int).DivMod(num, den, new(big.Int))
	twoRem := new(big.Int).Lsh(rem, 1)
	if twoRem.Cmp(den) >= 0 {
		q.Add(q, big.NewInt(1))
	}
	if !q.IsUint64() {
		return corekeeper.MaxSafeDifficultyFactor
	}
	return q.Uint64()
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
//  1. Equality with the current LastBlockId (most common path), OR
//  2. Membership in the on-chain recent-block-hashes window via lookupHash.
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
	// M-1: reject stale/fabricated last_block_hash BEFORE Argon2id. The check is
	// a string compare against a window the caller already read, so it costs
	// nothing next to the work product; paying 1.76ms+4MB first was pure DoS
	// amplification.
	if !skipHashCheck {
		lb := strings.ToLower(hex.EncodeToString(lastBlockHash))
		// currentLastID is empty under ABCI 2.0, so an empty envelope hash would
		// otherwise match it and skip the window entirely.
		if lb == "" {
			return fmt.Errorf("invalid last_block_hash: empty")
		}
		if lb != strings.ToLower(currentLastID) {
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
		}
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
	return nil
}


func buildCanonV139(name string, pubkey, blockHash []byte, difficulty, ts, nonce uint64, fill func(*canonWriter)) []byte {
	cw := newCanonWriter(name)
	cw.writeBytes(2, pubkey)
	cw.writeBytes(3, blockHash)
	cw.writeUvarint(4, difficulty)
	cw.writeUvarint(6, ts)
	cw.writeUvarint(7, nonce)
	fill(cw)
	return cw.buf
}
