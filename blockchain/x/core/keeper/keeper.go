package keeper

import (
	"context"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"

	"mirage/consensusfatal"
	"mirage/x/core/types"

	corestore "cosmossdk.io/core/store"
	sdkmath "cosmossdk.io/math"
	"github.com/cosmos/cosmos-sdk/codec"
	storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	sdkerrors "github.com/cosmos/cosmos-sdk/types/errors"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	bankkeeper "github.com/cosmos/cosmos-sdk/x/bank/keeper"
	distrkeeper "github.com/cosmos/cosmos-sdk/x/distribution/keeper"
	slashingkeeper "github.com/cosmos/cosmos-sdk/x/slashing/keeper"
	stakingkeeper "github.com/cosmos/cosmos-sdk/x/staking/keeper"
	stakingtypes "github.com/cosmos/cosmos-sdk/x/staking/types"
)

type Keeper struct {
	storeService corestore.KVStoreService
	cdc          codec.Codec
	bank         bankkeeper.Keeper
	staking      *stakingkeeper.Keeper
	distribution *distrkeeper.Keeper
	slashing     slashingkeeper.Keeper
}

func NewKeeper(storeService corestore.KVStoreService, cdc codec.Codec, bank bankkeeper.Keeper, staking *stakingkeeper.Keeper, distribution *distrkeeper.Keeper, slashing slashingkeeper.Keeper) Keeper {
	return Keeper{
		storeService: failFastKVStoreService{delegate: storeService},
		cdc:          cdc,
		bank:         bank,
		staking:      staking,
		distribution: distribution,
		slashing:     slashing,
	}
}

// StoreService exposes the KV store service for use in upgrade handlers.
func (k Keeper) StoreService() corestore.KVStoreService {
	return k.storeService
}

func (k Keeper) profileKey(addr string) []byte   { return []byte(types.ProfilesPrefix + addr) }
func (k Keeper) usernameKey(lower string) []byte { return []byte(types.UsernamesPrefix + lower) }
func (k Keeper) relayCreditKey(valoper string) []byte {
	return []byte(types.RelayCreditsPrefix + valoper)
}

// Profile list key functions
func (k Keeper) profileEnabledAgentsKey(addr string) []byte {
	return []byte(types.ProfileEnabledAgentsPrefix + addr)
}
func (k Keeper) profileFollowedUsersKey(addr string) []byte {
	return []byte(types.ProfileFollowedUsersPrefix + addr)
}
func (k Keeper) profileFollowedTopicsKey(addr string) []byte {
	return []byte(types.ProfileFollowedTopicsPrefix + addr)
}
func (k Keeper) profileBlockedUsersKey(addr string) []byte {
	return []byte(types.ProfileBlockedUsersPrefix + addr)
}
func (k Keeper) profileBlockedPostsKey(addr string) []byte {
	return []byte(types.ProfileBlockedPostsPrefix + addr)
}
func (k Keeper) profileBlockedTopicsKey(addr string) []byte {
	return []byte(types.ProfileBlockedTopicsPrefix + addr)
}

// SetProfileCore stores only the core profile data (scalars, no lists)
func (k Keeper) SetProfileCore(ctx sdk.Context, addr string, bz []byte) error {
	store := k.storeService.OpenKVStore(ctx)
	return store.Set(k.profileKey(addr), bz)
}

// GetProfileCore returns the core profile data (scalars only, no lists)
func (k Keeper) GetProfileCore(ctx sdk.Context, addr string) ([]byte, bool, error) {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.profileKey(addr))
	if err != nil {
		return nil, false, err
	}
	if len(bz) == 0 {
		return nil, false, nil
	}
	return bz, true, nil
}

// SetProfile is an alias for SetProfileCore for backward compatibility
func (k Keeper) SetProfile(ctx sdk.Context, addr string, bz []byte) error {
	return k.SetProfileCore(ctx, addr, bz)
}

// GetProfile is an alias for GetProfileCore for backward compatibility
func (k Keeper) GetProfile(ctx sdk.Context, addr string) ([]byte, bool, error) {
	return k.GetProfileCore(ctx, addr)
}

// Profile list getters/setters

func (k Keeper) SetProfileEnabledAgents(ctx sdk.Context, addr string, agents []string) error {
	store := k.storeService.OpenKVStore(ctx)
	if len(agents) == 0 {
		return store.Delete(k.profileEnabledAgentsKey(addr))
	}
	bz, err := json.Marshal(agents)
	if err != nil {
		return err
	}
	return store.Set(k.profileEnabledAgentsKey(addr), bz)
}

func (k Keeper) GetProfileEnabledAgents(ctx sdk.Context, addr string) ([]string, error) {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.profileEnabledAgentsKey(addr))
	if err != nil {
		return nil, err
	}
	if len(bz) == 0 {
		return []string{}, nil
	}
	var agents []string
	if err := json.Unmarshal(bz, &agents); err != nil {
		return nil, err
	}
	return agents, nil
}

func (k Keeper) SetProfileFollowedUsers(ctx sdk.Context, addr string, users []string) error {
	store := k.storeService.OpenKVStore(ctx)
	if len(users) == 0 {
		return store.Delete(k.profileFollowedUsersKey(addr))
	}
	bz, err := json.Marshal(users)
	if err != nil {
		return err
	}
	return store.Set(k.profileFollowedUsersKey(addr), bz)
}

func (k Keeper) GetProfileFollowedUsers(ctx sdk.Context, addr string) ([]string, error) {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.profileFollowedUsersKey(addr))
	if err != nil {
		return nil, err
	}
	if len(bz) == 0 {
		return []string{}, nil
	}
	var users []string
	if err := json.Unmarshal(bz, &users); err != nil {
		return nil, err
	}
	return users, nil
}

func (k Keeper) SetProfileFollowedTopics(ctx sdk.Context, addr string, topics []string) error {
	store := k.storeService.OpenKVStore(ctx)
	if len(topics) == 0 {
		return store.Delete(k.profileFollowedTopicsKey(addr))
	}
	bz, err := json.Marshal(topics)
	if err != nil {
		return err
	}
	return store.Set(k.profileFollowedTopicsKey(addr), bz)
}

func (k Keeper) GetProfileFollowedTopics(ctx sdk.Context, addr string) ([]string, error) {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.profileFollowedTopicsKey(addr))
	if err != nil {
		return nil, err
	}
	if len(bz) == 0 {
		return []string{}, nil
	}
	var topics []string
	if err := json.Unmarshal(bz, &topics); err != nil {
		return nil, err
	}
	return topics, nil
}

func (k Keeper) SetProfileBlockedUsers(ctx sdk.Context, addr string, users []string) error {
	store := k.storeService.OpenKVStore(ctx)
	if len(users) == 0 {
		return store.Delete(k.profileBlockedUsersKey(addr))
	}
	bz, err := json.Marshal(users)
	if err != nil {
		return err
	}
	return store.Set(k.profileBlockedUsersKey(addr), bz)
}

func (k Keeper) GetProfileBlockedUsers(ctx sdk.Context, addr string) ([]string, error) {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.profileBlockedUsersKey(addr))
	if err != nil {
		return nil, err
	}
	if len(bz) == 0 {
		return []string{}, nil
	}
	var users []string
	if err := json.Unmarshal(bz, &users); err != nil {
		return nil, err
	}
	return users, nil
}

func (k Keeper) SetProfileBlockedPosts(ctx sdk.Context, addr string, posts []string) error {
	store := k.storeService.OpenKVStore(ctx)
	if len(posts) == 0 {
		return store.Delete(k.profileBlockedPostsKey(addr))
	}
	bz, err := json.Marshal(posts)
	if err != nil {
		return err
	}
	return store.Set(k.profileBlockedPostsKey(addr), bz)
}

func (k Keeper) GetProfileBlockedPosts(ctx sdk.Context, addr string) ([]string, error) {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.profileBlockedPostsKey(addr))
	if err != nil {
		return nil, err
	}
	if len(bz) == 0 {
		return []string{}, nil
	}
	var posts []string
	if err := json.Unmarshal(bz, &posts); err != nil {
		return nil, err
	}
	return posts, nil
}

func (k Keeper) SetProfileBlockedTopics(ctx sdk.Context, addr string, topics []string) error {
	store := k.storeService.OpenKVStore(ctx)
	if len(topics) == 0 {
		return store.Delete(k.profileBlockedTopicsKey(addr))
	}
	bz, err := json.Marshal(topics)
	if err != nil {
		return err
	}
	return store.Set(k.profileBlockedTopicsKey(addr), bz)
}

func (k Keeper) GetProfileBlockedTopics(ctx sdk.Context, addr string) ([]string, error) {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.profileBlockedTopicsKey(addr))
	if err != nil {
		return nil, err
	}
	if len(bz) == 0 {
		return []string{}, nil
	}
	var topics []string
	if err := json.Unmarshal(bz, &topics); err != nil {
		return nil, err
	}
	return topics, nil
}

// ═══════════════════════════════════════════════════════════════════════
// Per-entry KV helpers — O(1) add/remove/has, O(n) list
// ═══════════════════════════════════════════════════════════════════════
//
// Three flavors share the same key layout:
//
//   Entry key:  {prefix}{owner}/{entry}  → value (sentinel, position, or sequence)
//   Count key:  {prefix}{owner}\x00c     → uint32 big-endian
//   Seq key:    {prefix}{owner}\x00s     → uint64 big-endian  (ordered/deque only)
//
// See types/keys.go for prefix definitions.

func entryKey(prefix, owner, entry string) []byte {
	return []byte(prefix + owner + "/" + entry)
}

func countKey(prefix, owner string) []byte {
	return []byte(prefix + owner + types.SetCountSuffix)
}

func seqKey(prefix, owner string) []byte {
	return []byte(prefix + owner + types.DequeSeqSuffix)
}

// entryPrefix returns the prefix for iterating all entries of a given owner,
// i.e. {prefix}{owner}/ — note the trailing slash which separates owner from entry.
func entryPrefix(prefix, owner string) []byte {
	return []byte(prefix + owner + "/")
}

var sentinelValue = []byte{1}

func putUint32(v uint32) []byte { b := make([]byte, 4); binary.BigEndian.PutUint32(b, v); return b }
func getUint32(b []byte) (uint32, error) {
	if len(b) == 0 {
		return 0, nil
	}
	if len(b) != 4 {
		return 0, fmt.Errorf("expected 4-byte big-endian uint32, got %d bytes", len(b))
	}
	return binary.BigEndian.Uint32(b), nil
}
func putUint64(v uint64) []byte { b := make([]byte, 8); binary.BigEndian.PutUint64(b, v); return b }
func getUint64(b []byte) (uint64, error) {
	if len(b) == 0 {
		return 0, nil
	}
	if len(b) != 8 {
		return 0, fmt.Errorf("expected 8-byte big-endian uint64, got %d bytes", len(b))
	}
	return binary.BigEndian.Uint64(b), nil
}

// prefixEndBytes returns the end key for a prefix range scan (increment last byte).
func prefixEndBytes(prefix []byte) []byte {
	if len(prefix) == 0 {
		return nil
	}
	end := make([]byte, len(prefix))
	copy(end, prefix)
	for i := len(end) - 1; i >= 0; i-- {
		end[i]++
		if end[i] != 0 {
			return end
		}
	}
	return nil // overflow — prefix was all 0xFF
}

// ── Unordered set helpers (followed_users, followed_topics) ────────────

// addSetEntry adds an entry to an unordered set. Returns false if already present.
// Writes are atomic through the transaction cache; any later error rolls the
// entry write back with the count write.
func (k Keeper) addSetEntry(ctx sdk.Context, prefix, owner, entry string) (bool, error) {
	store := k.storeService.OpenKVStore(ctx)
	ek := entryKey(prefix, owner, entry)
	existing, err := store.Get(ek)
	if err != nil {
		return false, err
	}
	if len(existing) > 0 {
		return false, nil // already present
	}
	if err := store.Set(ek, sentinelValue); err != nil {
		return false, err
	}
	// Increment count. A failed read must not be decoded as zero: that would
	// rewrite a real counter from scratch and admit entries past the tier cap
	// on this node only (review M-2).
	ck := countKey(prefix, owner)
	cb, err := store.Get(ck)
	if err != nil {
		return false, fmt.Errorf("count read failed for %s/%s: %w", prefix, owner, err)
	}
	cnt, err := getUint32(cb)
	if err != nil {
		return false, fmt.Errorf("count decode failed for %s/%s: %w", prefix, owner, err)
	}
	if cnt == math.MaxUint32 {
		return false, fmt.Errorf("count overflow for %s/%s", prefix, owner)
	}
	cnt++
	return true, store.Set(ck, putUint32(cnt))
}

// removeSetEntry removes an entry from an unordered set. Idempotent — no error if absent.
func (k Keeper) removeSetEntry(ctx sdk.Context, prefix, owner, entry string) error {
	store := k.storeService.OpenKVStore(ctx)
	ek := entryKey(prefix, owner, entry)
	existing, err := store.Get(ek)
	if err != nil {
		return err
	}
	if len(existing) == 0 {
		return nil // not present
	}
	if err := store.Delete(ek); err != nil {
		return err
	}
	ck := countKey(prefix, owner)
	cb, err := store.Get(ck)
	if err != nil {
		return fmt.Errorf("count read failed for %s/%s: %w", prefix, owner, err)
	}
	cnt, err := getUint32(cb)
	if err != nil {
		return fmt.Errorf("count decode failed for %s/%s: %w", prefix, owner, err)
	}
	if cnt > 0 {
		cnt--
	}
	if cnt == 0 {
		return store.Delete(ck)
	}
	return store.Set(ck, putUint32(cnt))
}

func (k Keeper) hasSetEntry(ctx sdk.Context, prefix, owner, entry string) (bool, error) {
	store := k.storeService.OpenKVStore(ctx)
	b, err := store.Get(entryKey(prefix, owner, entry))
	if err != nil {
		return false, err
	}
	return len(b) > 0, nil
}

// countSetEntries returns the stored entry count. An absent key is zero; a
// failed read is an error, never zero, because these counts gate hard tier
// caps (review M-2).
func (k Keeper) countSetEntries(ctx sdk.Context, prefix, owner string) (uint32, error) {
	store := k.storeService.OpenKVStore(ctx)
	b, err := store.Get(countKey(prefix, owner))
	if err != nil {
		return 0, fmt.Errorf("count read failed for %s/%s: %w", prefix, owner, err)
	}
	count, err := getUint32(b)
	if err != nil {
		return 0, fmt.Errorf("count decode failed for %s/%s: %w", prefix, owner, err)
	}
	return count, nil
}

// listSetEntries returns all entries for an owner (unordered).
func (k Keeper) listSetEntries(ctx sdk.Context, prefix, owner string) ([]string, error) {
	store := k.storeService.OpenKVStore(ctx)
	pfx := entryPrefix(prefix, owner)
	it, err := store.Iterator(pfx, prefixEndBytes(pfx))
	if err != nil {
		return nil, err
	}

	pfxLen := len(pfx)
	var out []string
	for ; it.Valid(); it.Next() {
		key := it.Key()
		if len(key) > pfxLen {
			out = append(out, string(key[pfxLen:]))
		}
	}
	if err := it.Error(); err != nil {
		_ = it.Close()
		return nil, err
	}
	if err := it.Close(); err != nil {
		return nil, err
	}
	if out == nil {
		out = []string{}
	}
	return out, nil
}

// deleteAllSetEntries removes all entries, the count key, and the seq key for an owner.
func (k Keeper) deleteAllSetEntries(ctx sdk.Context, prefix, owner string) error {
	store := k.storeService.OpenKVStore(ctx)
	pfx := entryPrefix(prefix, owner)
	it, err := store.Iterator(pfx, prefixEndBytes(pfx))
	if err != nil {
		return err
	}
	var keys [][]byte
	for ; it.Valid(); it.Next() {
		keys = append(keys, append([]byte(nil), it.Key()...))
	}
	if err := it.Error(); err != nil {
		_ = it.Close()
		return err
	}
	if err := it.Close(); err != nil {
		return err
	}
	for _, key := range keys {
		if err := store.Delete(key); err != nil {
			return err
		}
	}
	if err := store.Delete(countKey(prefix, owner)); err != nil {
		return err
	}
	if err := store.Delete(seqKey(prefix, owner)); err != nil {
		return err
	}
	return nil
}

// ── Ordered set helpers (enabled_agents) ───────────────────────────────

// addOrderedEntry adds an entry with a monotonically increasing position.
// Returns false if already present.
func (k Keeper) addOrderedEntry(ctx sdk.Context, prefix, owner, entry string) (bool, error) {
	store := k.storeService.OpenKVStore(ctx)
	ek := entryKey(prefix, owner, entry)
	existing, err := store.Get(ek)
	if err != nil {
		return false, err
	}
	if len(existing) > 0 {
		return false, nil // already present
	}
	// Get next sequence (position). A failed sequence read would restart
	// positions at zero on this node and reorder the list against peers.
	sk := seqKey(prefix, owner)
	sb, err := store.Get(sk)
	if err != nil {
		return false, fmt.Errorf("sequence read failed for %s/%s: %w", prefix, owner, err)
	}
	seq, err := getUint64(sb)
	if err != nil {
		return false, fmt.Errorf("sequence decode failed for %s/%s: %w", prefix, owner, err)
	}
	nextSeq, err := types.CheckedAddUint64(seq, 1)
	if err != nil {
		return false, fmt.Errorf("sequence overflow for %s/%s: %w", prefix, owner, err)
	}
	if err := store.Set(ek, putUint64(seq)); err != nil {
		return false, err
	}
	if err := store.Set(sk, putUint64(nextSeq)); err != nil {
		return false, err
	}
	ck := countKey(prefix, owner)
	cb, err := store.Get(ck)
	if err != nil {
		return false, fmt.Errorf("count read failed for %s/%s: %w", prefix, owner, err)
	}
	cnt, err := getUint32(cb)
	if err != nil {
		return false, fmt.Errorf("count decode failed for %s/%s: %w", prefix, owner, err)
	}
	if cnt == math.MaxUint32 {
		return false, fmt.Errorf("count overflow for %s/%s", prefix, owner)
	}
	cnt++
	return true, store.Set(ck, putUint32(cnt))
}

// removeOrderedEntry removes an entry. Gaps in position values are harmless.
func (k Keeper) removeOrderedEntry(ctx sdk.Context, prefix, owner, entry string) error {
	return k.removeSetEntry(ctx, prefix, owner, entry)
}

// listOrderedEntries returns entries sorted by their position value (ascending).
func (k Keeper) listOrderedEntries(ctx sdk.Context, prefix, owner string) ([]string, error) {
	store := k.storeService.OpenKVStore(ctx)
	pfx := entryPrefix(prefix, owner)
	it, err := store.Iterator(pfx, prefixEndBytes(pfx))
	if err != nil {
		return nil, err
	}

	pfxLen := len(pfx)
	type kv struct {
		entry string
		pos   uint64
	}
	var items []kv
	for ; it.Valid(); it.Next() {
		key := it.Key()
		if len(key) > pfxLen {
			pos, err := getUint64(it.Value())
			if err != nil {
				_ = it.Close()
				return nil, fmt.Errorf("position decode failed for %s/%s entry=%q: %w",
					prefix, owner, string(key[pfxLen:]), err)
			}
			items = append(items, kv{entry: string(key[pfxLen:]), pos: pos})
		}
	}
	if err := it.Error(); err != nil {
		_ = it.Close()
		return nil, err
	}
	if err := it.Close(); err != nil {
		return nil, err
	}
	sort.Slice(items, func(i, j int) bool { return items[i].pos < items[j].pos })
	out := make([]string, len(items))
	for i, kv := range items {
		out[i] = kv.entry
	}
	return out, nil
}

// replaceAllOrderedEntries deletes all existing entries and writes new ones
// with positions 0, 1, 2, ... Resets seq = len(entries).
func (k Keeper) replaceAllOrderedEntries(ctx sdk.Context, prefix, owner string, entries []string) error {
	if err := k.deleteAllSetEntries(ctx, prefix, owner); err != nil {
		return err
	}
	if len(entries) == 0 {
		return nil
	}
	store := k.storeService.OpenKVStore(ctx)
	for i, e := range entries {
		if err := store.Set(entryKey(prefix, owner, e), putUint64(uint64(i))); err != nil {
			return err
		}
	}
	if err := store.Set(countKey(prefix, owner), putUint32(uint32(len(entries)))); err != nil {
		return err
	}
	return store.Set(seqKey(prefix, owner), putUint64(uint64(len(entries))))
}

// ── Deque helpers (blocked_users, blocked_posts, blocked_topics) ───────

// addDequeEntry adds an entry with a monotonically increasing sequence.
// If the entry already exists, it is a no-op (returns false).
// If count >= maxCap after adding, the entry with the lowest sequence is evicted.
func (k Keeper) addDequeEntry(ctx sdk.Context, prefix, owner, entry string, maxCap uint32) (bool, error) {
	store := k.storeService.OpenKVStore(ctx)
	ek := entryKey(prefix, owner, entry)
	existing, err := store.Get(ek)
	if err != nil {
		return false, err
	}
	if len(existing) > 0 {
		return false, nil // already present — idempotent
	}
	// Assign next sequence. A failed read here would reuse sequence numbers
	// and evict a different entry than peers do on the next overflow.
	sk := seqKey(prefix, owner)
	sb, err := store.Get(sk)
	if err != nil {
		return false, fmt.Errorf("sequence read failed for %s/%s: %w", prefix, owner, err)
	}
	seq, err := getUint64(sb)
	if err != nil {
		return false, fmt.Errorf("sequence decode failed for %s/%s: %w", prefix, owner, err)
	}
	nextSeq, err := types.CheckedAddUint64(seq, 1)
	if err != nil {
		return false, fmt.Errorf("sequence overflow for %s/%s: %w", prefix, owner, err)
	}
	if err := store.Set(ek, putUint64(seq)); err != nil {
		return false, err
	}
	if err := store.Set(sk, putUint64(nextSeq)); err != nil {
		return false, err
	}
	// Increment count
	ck := countKey(prefix, owner)
	cb, err := store.Get(ck)
	if err != nil {
		return false, fmt.Errorf("count read failed for %s/%s: %w", prefix, owner, err)
	}
	cnt, err := getUint32(cb)
	if err != nil {
		return false, fmt.Errorf("count decode failed for %s/%s: %w", prefix, owner, err)
	}
	if cnt == math.MaxUint32 {
		return false, fmt.Errorf("count overflow for %s/%s", prefix, owner)
	}
	cnt++
	if err := store.Set(ck, putUint32(cnt)); err != nil {
		return false, err
	}
	// Evict oldest if over cap
	if maxCap > 0 && cnt > maxCap {
		if err := k.evictLowestSeq(ctx, prefix, owner); err != nil {
			return true, err
		}
		// Decrement count after eviction
		cnt--
		if cnt == 0 {
			if err := store.Delete(ck); err != nil {
				return true, err
			}
		} else {
			if err := store.Set(ck, putUint32(cnt)); err != nil {
				return true, err
			}
		}
	}
	return true, nil
}

// evictLowestSeq iterates all entries for an owner and deletes the one
// with the smallest sequence value.
func (k Keeper) evictLowestSeq(ctx sdk.Context, prefix, owner string) error {
	store := k.storeService.OpenKVStore(ctx)
	pfx := entryPrefix(prefix, owner)
	it, err := store.Iterator(pfx, prefixEndBytes(pfx))
	if err != nil {
		return err
	}

	var minKey []byte
	var minSeq uint64
	first := true
	for ; it.Valid(); it.Next() {
		s, err := getUint64(it.Value())
		if err != nil {
			_ = it.Close()
			return fmt.Errorf("sequence decode failed for %s/%s: %w", prefix, owner, err)
		}
		if first || s < minSeq {
			minKey = append([]byte(nil), it.Key()...)
			minSeq = s
			first = false
		}
	}
	if err := it.Error(); err != nil {
		_ = it.Close()
		return err
	}
	if err := it.Close(); err != nil {
		return err
	}
	if minKey != nil {
		return store.Delete(minKey)
	}
	return nil
}

// ═══════════════════════════════════════════════════════════════════════
// Public per-entry methods for each list type
// ═══════════════════════════════════════════════════════════════════════

// ── Followed Users (unordered set, hard cap) ───────────────────────────

func (k Keeper) AddFollowedUser(ctx sdk.Context, owner, user string) (bool, error) {
	return k.addSetEntry(ctx, types.FollowedUsersPrefix, owner, user)
}

func (k Keeper) RemoveFollowedUser(ctx sdk.Context, owner, user string) error {
	return k.removeSetEntry(ctx, types.FollowedUsersPrefix, owner, user)
}

func (k Keeper) HasFollowedUser(ctx sdk.Context, owner, user string) (bool, error) {
	return k.hasSetEntry(ctx, types.FollowedUsersPrefix, owner, user)
}

func (k Keeper) CountFollowedUsers(ctx sdk.Context, owner string) (uint32, error) {
	return k.countSetEntries(ctx, types.FollowedUsersPrefix, owner)
}

func (k Keeper) ListFollowedUsers(ctx sdk.Context, owner string) ([]string, error) {
	return k.listSetEntries(ctx, types.FollowedUsersPrefix, owner)
}

func (k Keeper) DeleteAllFollowedUsers(ctx sdk.Context, owner string) error {
	return k.deleteAllSetEntries(ctx, types.FollowedUsersPrefix, owner)
}

// ── Followed Topics (unordered set, hard cap) ──────────────────────────

func (k Keeper) AddFollowedTopic(ctx sdk.Context, owner, topic string) (bool, error) {
	return k.addSetEntry(ctx, types.FollowedTopicsPrefix, owner, topic)
}

func (k Keeper) RemoveFollowedTopic(ctx sdk.Context, owner, topic string) error {
	return k.removeSetEntry(ctx, types.FollowedTopicsPrefix, owner, topic)
}

func (k Keeper) HasFollowedTopic(ctx sdk.Context, owner, topic string) (bool, error) {
	return k.hasSetEntry(ctx, types.FollowedTopicsPrefix, owner, topic)
}

func (k Keeper) CountFollowedTopics(ctx sdk.Context, owner string) (uint32, error) {
	return k.countSetEntries(ctx, types.FollowedTopicsPrefix, owner)
}

func (k Keeper) ListFollowedTopics(ctx sdk.Context, owner string) ([]string, error) {
	return k.listSetEntries(ctx, types.FollowedTopicsPrefix, owner)
}

func (k Keeper) DeleteAllFollowedTopics(ctx sdk.Context, owner string) error {
	return k.deleteAllSetEntries(ctx, types.FollowedTopicsPrefix, owner)
}

// ── Enabled Agents (ordered set, hard cap) ─────────────────────────────

func (k Keeper) AddEnabledAgent(ctx sdk.Context, owner, agent string) (bool, error) {
	return k.addOrderedEntry(ctx, types.EnabledAgentsPrefix, owner, agent)
}

func (k Keeper) RemoveEnabledAgent(ctx sdk.Context, owner, agent string) error {
	return k.removeOrderedEntry(ctx, types.EnabledAgentsPrefix, owner, agent)
}

func (k Keeper) HasEnabledAgent(ctx sdk.Context, owner, agent string) (bool, error) {
	return k.hasSetEntry(ctx, types.EnabledAgentsPrefix, owner, agent)
}

func (k Keeper) CountEnabledAgents(ctx sdk.Context, owner string) (uint32, error) {
	return k.countSetEntries(ctx, types.EnabledAgentsPrefix, owner)
}

// ListEnabledAgentsOrdered returns agents sorted by the order they were enabled.
func (k Keeper) ListEnabledAgentsOrdered(ctx sdk.Context, owner string) ([]string, error) {
	return k.listOrderedEntries(ctx, types.EnabledAgentsPrefix, owner)
}

// ReplaceAllEnabledAgents atomically replaces the entire agents list,
// preserving the order of the provided slice.
func (k Keeper) ReplaceAllEnabledAgents(ctx sdk.Context, owner string, agents []string) error {
	return k.replaceAllOrderedEntries(ctx, types.EnabledAgentsPrefix, owner, agents)
}

func (k Keeper) DeleteAllEnabledAgents(ctx sdk.Context, owner string) error {
	return k.deleteAllSetEntries(ctx, types.EnabledAgentsPrefix, owner)
}

// ── Blocked Users (deque) ──────────────────────────────────────────────

func (k Keeper) AddBlockedUserDeque(ctx sdk.Context, owner, user string, maxCap uint32) (bool, error) {
	return k.addDequeEntry(ctx, types.BlockedUsersPrefix, owner, user, maxCap)
}

func (k Keeper) RemoveBlockedUser(ctx sdk.Context, owner, user string) error {
	return k.removeSetEntry(ctx, types.BlockedUsersPrefix, owner, user)
}

func (k Keeper) HasBlockedUser(ctx sdk.Context, owner, user string) (bool, error) {
	return k.hasSetEntry(ctx, types.BlockedUsersPrefix, owner, user)
}

func (k Keeper) CountBlockedUsers(ctx sdk.Context, owner string) (uint32, error) {
	return k.countSetEntries(ctx, types.BlockedUsersPrefix, owner)
}

func (k Keeper) ListBlockedUsers(ctx sdk.Context, owner string) ([]string, error) {
	return k.listOrderedEntries(ctx, types.BlockedUsersPrefix, owner)
}

func (k Keeper) DeleteAllBlockedUsers(ctx sdk.Context, owner string) error {
	return k.deleteAllSetEntries(ctx, types.BlockedUsersPrefix, owner)
}

// ── Blocked Posts (deque) ──────────────────────────────────────────────

func (k Keeper) AddBlockedPostDeque(ctx sdk.Context, owner, txhash string, maxCap uint32) (bool, error) {
	return k.addDequeEntry(ctx, types.BlockedPostsPrefix, owner, txhash, maxCap)
}

func (k Keeper) RemoveBlockedPost(ctx sdk.Context, owner, txhash string) error {
	return k.removeSetEntry(ctx, types.BlockedPostsPrefix, owner, txhash)
}

func (k Keeper) HasBlockedPost(ctx sdk.Context, owner, txhash string) (bool, error) {
	return k.hasSetEntry(ctx, types.BlockedPostsPrefix, owner, txhash)
}

func (k Keeper) CountBlockedPosts(ctx sdk.Context, owner string) (uint32, error) {
	return k.countSetEntries(ctx, types.BlockedPostsPrefix, owner)
}

func (k Keeper) ListBlockedPosts(ctx sdk.Context, owner string) ([]string, error) {
	return k.listOrderedEntries(ctx, types.BlockedPostsPrefix, owner)
}

func (k Keeper) DeleteAllBlockedPosts(ctx sdk.Context, owner string) error {
	return k.deleteAllSetEntries(ctx, types.BlockedPostsPrefix, owner)
}

// ── Blocked Topics (deque) ─────────────────────────────────────────────

func (k Keeper) AddBlockedTopicDeque(ctx sdk.Context, owner, topic string, maxCap uint32) (bool, error) {
	return k.addDequeEntry(ctx, types.BlockedTopicsPrefix, owner, topic, maxCap)
}

func (k Keeper) RemoveBlockedTopic(ctx sdk.Context, owner, topic string) error {
	return k.removeSetEntry(ctx, types.BlockedTopicsPrefix, owner, topic)
}

func (k Keeper) HasBlockedTopic(ctx sdk.Context, owner, topic string) (bool, error) {
	return k.hasSetEntry(ctx, types.BlockedTopicsPrefix, owner, topic)
}

func (k Keeper) CountBlockedTopics(ctx sdk.Context, owner string) (uint32, error) {
	return k.countSetEntries(ctx, types.BlockedTopicsPrefix, owner)
}

func (k Keeper) ListBlockedTopics(ctx sdk.Context, owner string) ([]string, error) {
	return k.listOrderedEntries(ctx, types.BlockedTopicsPrefix, owner)
}

func (k Keeper) DeleteAllBlockedTopics(ctx sdk.Context, owner string) error {
	return k.deleteAllSetEntries(ctx, types.BlockedTopicsPrefix, owner)
}

// GetAllProfiles returns all profiles from the store
// WARNING: This loads all profiles into memory - use GetProfilesPaginated for query endpoints
func (k Keeper) GetAllProfiles(ctx sdk.Context) ([][]byte, error) {
	store := k.storeService.OpenKVStore(ctx)
	profilesPrefix := []byte(types.ProfilesPrefix)
	var profiles [][]byte

	// Iterate through all profiles
	iterator, err := store.Iterator(profilesPrefix, storetypes.PrefixEndBytes(profilesPrefix))
	if err != nil {
		return nil, err
	}

	for ; iterator.Valid(); iterator.Next() {
		profiles = append(profiles, append([]byte(nil), iterator.Value()...))
	}
	if err := iterator.Error(); err != nil {
		_ = iterator.Close()
		return nil, err
	}
	if err := iterator.Close(); err != nil {
		return nil, err
	}

	return profiles, nil
}

// GetProfilesPaginated returns profiles with pagination support
// limit is capped at MaxProfilesQueryLimit (100) to prevent memory exhaustion
const MaxProfilesQueryLimit = 100

func (k Keeper) GetProfilesPaginated(ctx sdk.Context, key []byte, limit uint64) (profiles [][]byte, nextKey []byte, err error) {
	store := k.storeService.OpenKVStore(ctx)
	profilesPrefix := []byte(types.ProfilesPrefix)

	// Cap limit to prevent abuse
	if limit == 0 || limit > MaxProfilesQueryLimit {
		limit = MaxProfilesQueryLimit
	}

	// Determine start key
	var startKey []byte
	if len(key) > 0 {
		startKey = append(profilesPrefix, key...)
	} else {
		startKey = profilesPrefix
	}

	iterator, err := store.Iterator(startKey, storetypes.PrefixEndBytes(profilesPrefix))
	if err != nil {
		return nil, nil, err
	}

	count := uint64(0)
	for ; iterator.Valid() && count < limit; iterator.Next() {
		profiles = append(profiles, append([]byte(nil), iterator.Value()...))
		count++
	}

	// If there are more results, return the next key (without prefix)
	if iterator.Valid() {
		fullKey := iterator.Key()
		if len(fullKey) > len(profilesPrefix) {
			nextKey = fullKey[len(profilesPrefix):]
		}
	}
	if err := iterator.Error(); err != nil {
		_ = iterator.Close()
		return nil, nil, err
	}
	if err := iterator.Close(); err != nil {
		return nil, nil, err
	}

	return profiles, nextKey, nil
}

// GetAllKVPairs returns ALL key-value pairs from the module's KV store.
// This is used for complete genesis export without needing to know about specific prefixes.
func (k Keeper) GetAllKVPairs(ctx sdk.Context) ([]*types.RawKVPair, error) {
	store := k.storeService.OpenKVStore(ctx)
	var pairs []*types.RawKVPair

	// Iterate through ALL keys (nil, nil means full range)
	iterator, err := store.Iterator(nil, nil)
	if err != nil {
		return nil, err
	}

	for ; iterator.Valid(); iterator.Next() {
		pairs = append(pairs, &types.RawKVPair{
			Key:   base64.StdEncoding.EncodeToString(iterator.Key()),
			Value: base64.StdEncoding.EncodeToString(iterator.Value()),
		})
	}
	if err := iterator.Error(); err != nil {
		_ = iterator.Close()
		return nil, err
	}
	if err := iterator.Close(); err != nil {
		return nil, err
	}

	return pairs, nil
}

// SetRawKVPair sets a single key-value pair in the store (for genesis import).
func (k Keeper) SetRawKVPair(ctx sdk.Context, key, value []byte) error {
	store := k.storeService.OpenKVStore(ctx)
	return store.Set(key, value)
}

// ClaimUsername stores a mapping username(lowercased) -> owner address if free or same owner
func (k Keeper) ClaimUsername(ctx sdk.Context, username string, owner string) error {
	store := k.storeService.OpenKVStore(ctx)
	key := k.usernameKey(strings.ToLower(username))
	existing, err := store.Get(key)
	if err != nil {
		return err
	}
	if len(existing) > 0 && string(existing) != owner {
		return fmt.Errorf("username already taken")
	}
	return store.Set(key, []byte(owner))
}

// ReleaseUsername removes the mapping if currently owned by the given owner
func (k Keeper) ReleaseUsername(ctx sdk.Context, username string, owner string) error {
	store := k.storeService.OpenKVStore(ctx)
	key := k.usernameKey(strings.ToLower(username))
	existing, err := store.Get(key)
	if err != nil {
		return err
	}
	if len(existing) > 0 && string(existing) == owner {
		return store.Delete(key)
	}
	return nil
}

// DeductFeeFromOwner sends the given amount (umirage) from the owner account to the core module account.
func (k Keeper) DeductFeeFromOwner(ctx sdk.Context, owner string, amount uint64) error {
	if amount == 0 {
		return nil
	}
	addr, err := sdk.AccAddressFromBech32(owner)
	if err != nil {
		return err
	}
	coin := sdk.NewCoin("umirage", sdkmath.NewIntFromUint64(amount))
	coins := sdk.NewCoins(coin)
	if !k.bankSpendableCoins(ctx, addr).IsAllGTE(coins) {
		return sdkerrors.ErrInsufficientFunds.Wrapf("spendable balance is smaller than %s", coins)
	}
	return haltFinalizeUnexpectedBankError(ctx, "deduct_fee_from_owner",
		k.bank.SendCoinsFromAccountToModule(ctx, addr, types.ModuleName, coins))
}

// GetBalance returns the spendable balance for denom on an address.
func (k Keeper) GetBalance(ctx sdk.Context, owner string, denom string) sdkmath.Int {
	addr, err := sdk.AccAddressFromBech32(owner)
	if err != nil {
		return sdkmath.NewInt(0)
	}
	return k.bankBalance(ctx, addr, denom).Amount
}

// SendCoins transfers coins from one account to another using the bank keeper.
func (k Keeper) SendCoins(ctx sdk.Context, fromAddr sdk.AccAddress, toAddr sdk.AccAddress, amt sdk.Coins) error {
	if !k.bankSpendableCoins(ctx, fromAddr).IsAllGTE(amt) {
		return sdkerrors.ErrInsufficientFunds.Wrapf("spendable balance is smaller than %s", amt)
	}
	return haltFinalizeUnexpectedBankError(ctx, "send_coins", k.bank.SendCoins(ctx, fromAddr, toAddr, amt))
}

// AccToValoper converts a bech32 account address (acc) to a validator operator address (valoper)
func (k Keeper) AccToValoper(acc string) (string, error) {
	addr, err := sdk.AccAddressFromBech32(acc)
	if err != nil {
		return "", err
	}
	val := sdk.ValAddress(addr)
	return val.String(), nil
}

// PunishValidator performs a governance-authorized punishment against a validator.
// It can slash by a specified fraction [0,1], jail, and/or tombstone.
func (k Keeper) PunishValidator(ctx sdk.Context, valoper string, fraction sdkmath.LegacyDec, jail bool, tombstone bool, reason string) error {
	// Lookup validator by operator address
	valAddr, err := sdk.ValAddressFromBech32(strings.TrimSpace(valoper))
	if err != nil {
		return fmt.Errorf("invalid valoper: %w", err)
	}
	validator, err := k.staking.GetValidator(ctx, valAddr)
	if err != nil {
		if errors.Is(err, stakingtypes.ErrNoValidatorFound) {
			return fmt.Errorf("validator not found: %w", err)
		}
		return haltFinalizeStoreError(ctx, "staking_get_validator", err)
	}

	// Compute consensus address and power
	consAddrBytes, err := validator.GetConsAddr()
	if err != nil {
		return fmt.Errorf("failed to get consensus address: %w", err)
	}
	consAddr := sdk.ConsAddress(consAddrBytes)
	power := validator.GetConsensusPower(k.staking.PowerReduction(ctx))

	// Slash first (if fraction > 0)
	if fraction.IsPositive() {
		if fraction.GT(sdkmath.LegacyNewDec(1)) {
			fraction = sdkmath.LegacyNewDec(1)
		}
		if err := k.slashing.Slash(sdk.WrapSDKContext(ctx), consAddr, fraction, power, ctx.BlockHeight()); err != nil {
			return fmt.Errorf("slash failed: %w", haltFinalizeSlashingError(ctx, "slashing_slash", err))
		}
	}

	// Jail if requested
	if jail {
		if err := k.slashing.Jail(sdk.WrapSDKContext(ctx), consAddr); err != nil {
			return fmt.Errorf("jail failed: %w", haltFinalizeSlashingError(ctx, "slashing_jail", err))
		}
	}

	// Tombstone if requested
	if tombstone {
		if err := k.slashing.Tombstone(sdk.WrapSDKContext(ctx), consAddr); err != nil {
			return fmt.Errorf("tombstone failed: %w", haltFinalizeSlashingError(ctx, "slashing_tombstone", err))
		}
	}

	// Emit an event for auditing
	ctx.EventManager().EmitEvent(
		sdk.NewEvent(
			"core_punish_validator",
			sdk.NewAttribute("valoper", valoper),
			sdk.NewAttribute("fraction", fraction.String()),
			sdk.NewAttribute("jail", fmt.Sprintf("%t", jail)),
			sdk.NewAttribute("tombstone", fmt.Sprintf("%t", tombstone)),
			sdk.NewAttribute("reason", reason),
		),
	)

	return nil
}

// Relay credits accounting
func (k Keeper) GetRelayCredit(ctx sdk.Context, valoper string) sdkmath.Int {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.relayCreditKey(valoper))
	if err != nil {
		// CONSENSUS_FATAL class: node-local — silent zero previously forked
		// mint distribution (M-3). Absent key still means zero credit.
		ctx.Logger().Error("CONSENSUS_FATAL:RELAY_CREDIT_STORE_GET",
			"height", ctx.BlockHeight(), "module", "core", "valoper", valoper, "err", err)
		consensusfatal.HaltErr(fmt.Errorf("CONSENSUS_FATAL:RELAY_CREDIT_STORE_GET height=%d valoper=%s: %w", ctx.BlockHeight(), valoper, err))
	}
	if len(bz) == 0 {
		return sdkmath.ZeroInt()
	}
	// value is big-endian uint64 for simplicity
	if len(bz) != 8 {
		// CONSENSUS_FATAL class: deterministic
		ctx.Logger().Error("CONSENSUS_FATAL:RELAY_CREDIT_DECODE",
			"height", ctx.BlockHeight(), "module", "core", "valoper", valoper, "bytes_len", len(bz))
		consensusfatal.HaltErr(fmt.Errorf("CONSENSUS_FATAL:RELAY_CREDIT_DECODE height=%d valoper=%s bytes=%d: expected 8-byte big-endian uint64", ctx.BlockHeight(), valoper, len(bz)))
	}
	return sdkmath.NewIntFromUint64(binary.BigEndian.Uint64(bz))
}

func (k Keeper) AddRelayCredit(ctx sdk.Context, valoper string, delta sdkmath.Int) error {
	if !delta.IsPositive() {
		return nil
	}
	store := k.storeService.OpenKVStore(ctx)
	cur := k.GetRelayCredit(ctx, valoper)
	next := cur.Add(delta)
	// store as big-endian uint64 up to 2^64-1 (saturate on overflow)
	var v uint64
	if next.IsUint64() {
		v = next.Uint64()
	} else {
		v = ^uint64(0)
	}
	bz := make([]byte, 8)
	binary.BigEndian.PutUint64(bz, v)
	return store.Set(k.relayCreditKey(valoper), bz)
}

func (k Keeper) IterateRelayCredits(ctx sdk.Context, fn func(valoper string, amt sdkmath.Int) bool) error {
	store := k.storeService.OpenKVStore(ctx)
	prefix := []byte(types.RelayCreditsPrefix)
	it, err := store.Iterator(prefix, storetypes.PrefixEndBytes(prefix))
	if err != nil {
		return err
	}
	for ; it.Valid(); it.Next() {
		key := string(it.Key())
		valoper := strings.TrimPrefix(key, types.RelayCreditsPrefix)
		amt := sdkmath.ZeroInt()
		if v := it.Value(); len(v) > 0 {
			if len(v) == 8 {
				amt = sdkmath.NewIntFromUint64(binary.BigEndian.Uint64(v))
			}
		}
		if stop := fn(valoper, amt); stop {
			break
		}
	}
	if err := it.Error(); err != nil {
		_ = it.Close()
		return err
	}
	return it.Close()
}

func (k Keeper) ResetAllRelayCredits(ctx sdk.Context) error {
	store := k.storeService.OpenKVStore(ctx)
	prefix := []byte(types.RelayCreditsPrefix)
	it, err := store.Iterator(prefix, storetypes.PrefixEndBytes(prefix))
	if err != nil {
		return err
	}
	// Collect keys first, then close the iterator, then delete. Mutating the
	// store during iteration is undefined across store backends (including
	// the vendored store/v2 fork); collect-then-delete matches the
	// pruneCommitInfo pattern used elsewhere for the same reason.
	var keys [][]byte
	for ; it.Valid(); it.Next() {
		keys = append(keys, append([]byte(nil), it.Key()...))
	}
	if err := it.Error(); err != nil {
		_ = it.Close()
		return err
	}
	if err := it.Close(); err != nil {
		return err
	}
	for _, key := range keys {
		if err := store.Delete(key); err != nil {
			return fmt.Errorf("ResetAllRelayCredits: delete %x: %w", key, err)
		}
	}
	return nil
}

// HasReservedProfilesBootstrapped reports whether the one-shot reserved
// module-account profile bootstrap has completed.
func (k Keeper) HasReservedProfilesBootstrapped(ctx sdk.Context) (bool, error) {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get([]byte(types.ReservedProfilesBootstrappedKey))
	if err != nil {
		return false, err
	}
	return len(bz) > 0, nil
}

// SetReservedProfilesBootstrapped writes the one-shot BeginBlock sentinel so
// the reserved-profile bootstrap loop does not run again.
func (k Keeper) SetReservedProfilesBootstrapped(ctx sdk.Context) error {
	store := k.storeService.OpenKVStore(ctx)
	return store.Set([]byte(types.ReservedProfilesBootstrappedKey), []byte{1})
}

// GetParams returns the current chain parameters.
//
// FAIL-FAST CONTRACT: any read/decode/validate failure terminates via
// consensusfatal.HaltErr with a tagged CONSENSUS_FATAL message. Silently
// substituting DefaultParams() on one node while peers use the stored params
// produces a single-node app-hash divergence that is invisible until the next
// consensus round. Process exit (not panic) ensures CometBFT's recover cannot
// leave a consensus zombie; the supervisor/watchdog see an unambiguous dead
// process. In DeliverTx the same halt surfaces loudly for operators.
//
// InitGenesis writes SetParams before any block handler runs, so an empty
// store post-genesis is also a bug we want to surface, not paper over.
func (k Keeper) GetParams(ctx sdk.Context) (p types.Params) {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get([]byte("params"))
	if err != nil {
		// CONSENSUS_FATAL class: node-local
		ctx.Logger().Error("CONSENSUS_FATAL:PARAMS_STORE_GET",
			"height", ctx.BlockHeight(), "module", "core", "err", err)
		consensusfatal.HaltErr(fmt.Errorf("CONSENSUS_FATAL:PARAMS_STORE_GET height=%d: %w", ctx.BlockHeight(), err))
	}
	if len(bz) == 0 {
		// CONSENSUS_FATAL class: deterministic
		ctx.Logger().Error("CONSENSUS_FATAL:PARAMS_EMPTY",
			"height", ctx.BlockHeight(), "module", "core")
		consensusfatal.HaltErr(fmt.Errorf("CONSENSUS_FATAL:PARAMS_EMPTY height=%d: params not initialized (InitGenesis must SetParams)", ctx.BlockHeight()))
	}
	if err := k.cdc.Unmarshal(bz, &p); err != nil {
		// CONSENSUS_FATAL class: deterministic
		ctx.Logger().Error("CONSENSUS_FATAL:PARAMS_UNMARSHAL",
			"height", ctx.BlockHeight(), "module", "core", "err", err, "bytes_len", len(bz))
		consensusfatal.HaltErr(fmt.Errorf("CONSENSUS_FATAL:PARAMS_UNMARSHAL height=%d bytes=%d: %w", ctx.BlockHeight(), len(bz), err))
	}
	if err := p.Validate(); err != nil {
		// CONSENSUS_FATAL class: deterministic
		ctx.Logger().Error("CONSENSUS_FATAL:PARAMS_VALIDATE",
			"height", ctx.BlockHeight(), "module", "core", "err", err)
		consensusfatal.HaltErr(fmt.Errorf("CONSENSUS_FATAL:PARAMS_VALIDATE height=%d: %w", ctx.BlockHeight(), err))
	}
	return p
}

func (k Keeper) SetParams(ctx sdk.Context, p types.Params) error {
	if err := p.Validate(); err != nil {
		return fmt.Errorf("SetParams: invalid params: %w", err)
	}
	store := k.storeService.OpenKVStore(ctx)
	bz, err := k.cdc.Marshal(&p)
	if err != nil {
		return err
	}
	return store.Set([]byte("params"), bz)
}

// GetRecentBlockHashes returns the on-chain rolling window of recently
// committed block hashes (lowercase hex). Most-recent-first. Empty if the
// chain has not yet recorded any (immediately after genesis or upgrade).
//
// FAIL-FAST: store-read or decode failures are returned to the caller and
// must propagate as tx-rejection errors. Silently returning an empty list
// would route the tx through a different acceptance branch on this node
// than on peers, producing the same divergence vector that the on-chain
// window was introduced to eliminate.
func (k Keeper) GetRecentBlockHashes(ctx sdk.Context) ([]string, error) {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get([]byte(types.RecentBlockHashesKey))
	if err != nil {
		return nil, fmt.Errorf("CONSENSUS_FATAL:RECENT_HASHES_GET height=%d: %w", ctx.BlockHeight(), err)
	}
	if len(bz) == 0 {
		return nil, nil
	}
	var hashes []string
	if err := json.Unmarshal(bz, &hashes); err != nil {
		return nil, fmt.Errorf("CONSENSUS_FATAL:RECENT_HASHES_DECODE height=%d bytes=%d: %w", ctx.BlockHeight(), len(bz), err)
	}
	return hashes, nil
}

// SetRecentBlockHashes overwrites the on-chain rolling window. Marshal
// failures bubble up; the caller (BeginBlock) will halt the chain rather
// than diverge silently.
func (k Keeper) SetRecentBlockHashes(ctx sdk.Context, hashes []string) error {
	bz, err := json.Marshal(hashes)
	if err != nil {
		return fmt.Errorf("SetRecentBlockHashes: marshal failed: %w", err)
	}
	store := k.storeService.OpenKVStore(ctx)
	return store.Set([]byte(types.RecentBlockHashesKey), bz)
}

// RecordRecentBlockHash prepends a new block-hash to the rolling window and
// trims to `window` entries. Called from BeginBlock with the previous block's
// hash (ctx.BlockHeader().LastBlockId.Hash). The empty hash is ignored — at
// genesis there is no previous block. Duplicate-of-newest is also ignored to
// keep the window monotonic.
func (k Keeper) RecordRecentBlockHash(ctx sdk.Context, hashLower string, window uint32) error {
	if hashLower == "" {
		return nil
	}
	current, err := k.GetRecentBlockHashes(ctx)
	if err != nil {
		return err
	}
	if len(current) > 0 && current[0] == hashLower {
		return nil
	}
	next := make([]string, 0, len(current)+1)
	next = append(next, hashLower)
	limit := int(window)
	if limit <= 0 {
		limit = 60
	}
	for i := 0; i < len(current) && len(next) < limit; i++ {
		if current[i] == hashLower {
			continue
		}
		next = append(next, current[i])
	}
	return k.SetRecentBlockHashes(ctx, next)
}

// moduleAddress returns the module account address for core
func (k Keeper) moduleAddress() sdk.AccAddress {
	return authtypes.NewModuleAddress(types.ModuleName)
}

func (k Keeper) mintDenom() string { return types.MintDenom }

// AssertSupplyInvariant verifies the bank module's fundamental accounting
// identity for the mint denom: recorded supply MUST equal the sum of every
// account balance. This is impossible to violate under correct serial
// execution — every coin minted or burned updates supply and a balance in the
// same call — so any mismatch means this node read stale state mid-block. That
// is exactly the IAVL fast-node stale-read that double-burned a prior block's
// fees and caused the 2026-06-12 app-hash divergence at height 5280036
// (supply was low by 164,124,000 while balances were unchanged).
//
// During Finalize, a mismatch terminates only the corrupted node with the
// precise discrepancy logged, instead of silently committing a divergent app
// hash that surfaces later as a cryptic consensus failure. The auto-recovery
// watchdog then state-syncs the node from healthy peers.
//
// See docs/troubleshooting/divergence-recovery.md.
//
// Cost note (M-2): this is O(accounts) through the canonical-only IAVL path.
// The O(1) delta check cannot detect a supply write paired with a missing
// balance write, so EndBlock retains this scan every block and logs its
// duration every 1000 blocks.
func (k Keeper) AssertSupplyInvariant(ctx sdk.Context) error {
	denom := k.mintDenom()
	sum := sdkmath.ZeroInt()
	k.iterateAllBankBalances(ctx, func(_ sdk.AccAddress, coin sdk.Coin) bool {
		if coin.Denom == denom {
			sum = sum.Add(coin.Amount)
		}
		return false
	})
	supply := k.bankSupply(ctx, denom).Amount
	if !supply.Equal(sum) {
		err := fmt.Errorf(
			"supply invariant violated for %s: recorded supply %s != sum of balances %s (diff %s)",
			denom, supply.String(), sum.String(), supply.Sub(sum).String(),
		)
		return haltFinalizeInvariantError(ctx, "supply_equals_balances", err)
	}
	return nil
}

func (k Keeper) blockSupplyStartKey() []byte { return []byte(types.BlockSupplyStartKey) }
func (k Keeper) blockSupplyDeltaKey() []byte { return []byte(types.BlockSupplyDeltaKey) }

func encodeSupplyInt(v sdkmath.Int) []byte {
	return []byte(v.String())
}

func decodeSupplyInt(bz []byte) (sdkmath.Int, error) {
	if len(bz) == 0 {
		return sdkmath.ZeroInt(), fmt.Errorf("empty supply int bytes")
	}
	v, ok := sdkmath.NewIntFromString(string(bz))
	if !ok {
		return sdkmath.ZeroInt(), fmt.Errorf("invalid supply int %q", string(bz))
	}
	return v, nil
}

// CaptureBlockSupplyStart records the mint-denom supply at BeginBlock and
// resets the per-block supply delta to zero. Must run before any mint/burn
// in the block so EndBlock's AssertSupplyDeltaInvariant is meaningful.
func (k Keeper) CaptureBlockSupplyStart(ctx sdk.Context) error {
	store := k.storeService.OpenKVStore(ctx)
	supply := k.bankSupply(ctx, k.mintDenom()).Amount
	if err := store.Set(k.blockSupplyStartKey(), encodeSupplyInt(supply)); err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:SUPPLY_START_SET: %w", err)
	}
	if err := store.Set(k.blockSupplyDeltaKey(), encodeSupplyInt(sdkmath.ZeroInt())); err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:SUPPLY_DELTA_SET: %w", err)
	}
	ctx.Logger().Debug("supply delta: captured start-of-block supply",
		"height", ctx.BlockHeight(), "supply_start", supply.String())
	return nil
}

// addSupplyDelta accumulates a signed mint-denom supply change for this block.
// Positive for mints, negative for burns. Called from keeper mint/burn wrappers.
func (k Keeper) addSupplyDelta(ctx sdk.Context, delta sdkmath.Int) error {
	if delta.IsZero() {
		return nil
	}
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.blockSupplyDeltaKey())
	if err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:SUPPLY_DELTA_GET: %w", err)
	}
	cur := sdkmath.ZeroInt()
	if len(bz) > 0 {
		cur, err = decodeSupplyInt(bz)
		if err != nil {
			return fmt.Errorf("CONSENSUS_FATAL:SUPPLY_DELTA_DECODE: %w", err)
		}
	}
	next := cur.Add(delta)
	if err := store.Set(k.blockSupplyDeltaKey(), encodeSupplyInt(next)); err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:SUPPLY_DELTA_SET: %w", err)
	}
	ctx.Logger().Debug("supply delta: updated",
		"height", ctx.BlockHeight(), "delta", delta.String(), "running", next.String())
	return nil
}

// AssertSupplyDeltaInvariant is an O(1) per-block supply guard:
// recorded bank supply must equal BeginBlock start + accumulated mint/burn
// delta. It complements, but does not replace, the full supply-vs-balances
// invariant because it cannot observe a missing account-balance write.
func (k Keeper) AssertSupplyDeltaInvariant(ctx sdk.Context) error {
	store := k.storeService.OpenKVStore(ctx)
	startBz, err := store.Get(k.blockSupplyStartKey())
	if err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:SUPPLY_START_GET: %w", err)
	}
	if len(startBz) == 0 {
		// BeginBlock did not capture (e.g. unit tests that only call EndBlock).
		// Fall back to the full scan so the guard still runs.
		ctx.Logger().Debug("supply delta: start key absent, falling back to full AssertSupplyInvariant",
			"height", ctx.BlockHeight())
		return k.AssertSupplyInvariant(ctx)
	}
	start, err := decodeSupplyInt(startBz)
	if err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:SUPPLY_START_DECODE: %w", err)
	}
	deltaBz, err := store.Get(k.blockSupplyDeltaKey())
	if err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:SUPPLY_DELTA_GET: %w", err)
	}
	delta := sdkmath.ZeroInt()
	if len(deltaBz) > 0 {
		delta, err = decodeSupplyInt(deltaBz)
		if err != nil {
			return fmt.Errorf("CONSENSUS_FATAL:SUPPLY_DELTA_DECODE: %w", err)
		}
	}
	expected := start.Add(delta)
	supply := k.bankSupply(ctx, k.mintDenom()).Amount
	if !supply.Equal(expected) {
		err := fmt.Errorf(
			"supply delta invariant violated for %s: supply %s != start %s + delta %s (expected %s, diff %s)",
			k.mintDenom(), supply.String(), start.String(), delta.String(), expected.String(), supply.Sub(expected).String(),
		)
		return haltFinalizeInvariantError(ctx, "supply_delta", err)
	}
	return nil
}

// burnCoinsTracked burns amt of the mint denom from the core module and
// records the supply delta for the O(1) EndBlock invariant.
func (k Keeper) burnCoinsTracked(ctx sdk.Context, amt sdkmath.Int) error {
	if !amt.IsPositive() {
		return nil
	}
	coin := sdk.NewCoin(k.mintDenom(), amt)
	if err := k.bank.BurnCoins(ctx, types.ModuleName, sdk.NewCoins(coin)); err != nil {
		return haltFinalizeUnexpectedBankError(ctx, "burn_core_coins", err)
	}
	return k.addSupplyDelta(ctx, amt.Neg())
}

// mintCoinsTracked mints amt of the mint denom into the core module and
// records the supply delta for the O(1) EndBlock invariant.
func (k Keeper) mintCoinsTracked(ctx sdk.Context, amt sdkmath.Int) error {
	if !amt.IsPositive() {
		return nil
	}
	coin := sdk.NewCoin(k.mintDenom(), amt)
	if err := k.bank.MintCoins(ctx, types.ModuleName, sdk.NewCoins(coin)); err != nil {
		return haltFinalizeBankError(ctx, "mint_core_coins", err)
	}
	return k.addSupplyDelta(ctx, amt)
}

// BurnAllFromModule burns all balance of the core module account for the mint denom
func (k Keeper) BurnAllFromModule(ctx sdk.Context) error {
	addr := k.moduleAddress()
	bal := k.bankBalance(ctx, addr, k.mintDenom()).Amount
	if !bal.IsPositive() {
		return nil
	}
	return k.burnCoinsTracked(ctx, bal)
}

// BurnAllFromModuleName transfers the entire balance of the given module account
// for the chain mint denom into the core module account and burns it.
func (k Keeper) BurnAllFromModuleName(ctx sdk.Context, moduleName string) error {
	if strings.TrimSpace(moduleName) == "" {
		return nil
	}
	srcAddr := authtypes.NewModuleAddress(moduleName)
	bal := k.bankBalance(ctx, srcAddr, k.mintDenom()).Amount
	if !bal.IsPositive() {
		return nil
	}
	coin := sdk.NewCoin(k.mintDenom(), bal)
	if err := k.bank.SendCoinsFromModuleToModule(ctx, moduleName, types.ModuleName, sdk.NewCoins(coin)); err != nil {
		return haltFinalizeUnexpectedBankError(ctx, "move_module_balance_for_burn", err)
	}
	return k.burnCoinsTracked(ctx, bal)
}

// BurnFromModuleAmount burns exactly amount umirage from the core module
// account. A short module balance is an accounting inconsistency and must not
// be hidden with a partial burn.
func (k Keeper) BurnFromModuleAmount(ctx sdk.Context, amount uint64) error {
	if amount == 0 {
		return nil
	}
	addr := k.moduleAddress()
	bal := k.bankBalance(ctx, addr, k.mintDenom()).Amount
	amt := sdkmath.NewIntFromUint64(amount)
	if bal.LT(amt) {
		// CONSENSUS_FATAL class: deterministic — recorded reserve liabilities
		// exceed their backing module balance.
		err := fmt.Errorf(
			"CONSENSUS_FATAL:CORE_MODULE_SHORT_BURN height=%d balance=%s required=%s denom=%s",
			ctx.BlockHeight(), bal.String(), amt.String(), k.mintDenom(),
		)
		ctx.Logger().Error("CONSENSUS_FATAL:CORE_MODULE_SHORT_BURN",
			"height", ctx.BlockHeight(), "balance", bal.String(),
			"required", amt.String(), "denom", k.mintDenom())
		consensusfatal.HaltErr(err)
		return err
	}
	return k.burnCoinsTracked(ctx, amt)
}

// MintToAccount mints amount (umirage) into the core module account and sends to recipient
func (k Keeper) MintToAccount(ctx sdk.Context, recipient string, amount uint64) error {
	if amount == 0 {
		return fmt.Errorf("amount must be > 0")
	}
	to, err := sdk.AccAddressFromBech32(strings.TrimSpace(recipient))
	if err != nil {
		return fmt.Errorf("invalid recipient: %w", err)
	}
	amt := sdkmath.NewIntFromUint64(amount)
	coin := sdk.NewCoin(k.mintDenom(), amt)
	if err := k.mintCoinsTracked(ctx, amt); err != nil {
		return err
	}
	return haltFinalizeUnexpectedBankError(ctx, "send_minted_coins",
		k.bank.SendCoinsFromModuleToAccount(ctx, types.ModuleName, to, sdk.NewCoins(coin)))
}

type mintRecipient struct {
	operatorAddress string
	accountAddress  sdk.AccAddress
	amount          sdkmath.Int
}

// buildMintRecipients validates reward recipients before MintCoins runs. It
// reports invalid validator addresses and mismatched slices to MintIfNeeded,
// which rejects the block before minting.
func buildMintRecipients(operatorAddrs []string, amounts []sdkmath.Int) (recipients []mintRecipient, skippedInvalid []string, totalMint sdkmath.Int, mismatch bool) {
	if len(operatorAddrs) != len(amounts) {
		return nil, nil, sdkmath.ZeroInt(), true
	}
	recipients = make([]mintRecipient, 0, len(operatorAddrs))
	skippedInvalid = make([]string, 0)
	totalMint = sdkmath.ZeroInt()
	for i, amount := range amounts {
		if !amount.IsPositive() {
			continue
		}
		valAddr, err := sdk.ValAddressFromBech32(operatorAddrs[i])
		if err != nil {
			skippedInvalid = append(skippedInvalid, operatorAddrs[i])
			continue
		}
		recipients = append(recipients, mintRecipient{
			operatorAddress: operatorAddrs[i],
			accountAddress:  sdk.AccAddress(valAddr),
			amount:          amount,
		})
		totalMint = totalMint.Add(amount)
	}
	return recipients, skippedInvalid, totalMint, false
}

// mintBankIface is the narrow subset of bankkeeper.Keeper that the mint
// distribution path consumes. It exists so mintAndDistribute can be unit-
// tested with injected bank-failure behavior without standing up the full
// SDK bank keeper. bankkeeper.Keeper satisfies this interface at compile
// time (verified implicitly at the MintIfNeeded call site).
type mintBankIface interface {
	MintCoins(ctx context.Context, moduleName string, amt sdk.Coins) error
	SendCoinsFromModuleToAccount(ctx context.Context, senderModule string, recipientAddr sdk.AccAddress, amt sdk.Coins) error
}

// mintResult captures the accounting outcome of a successful mint interval.
// A distribution error returns the partial result only for diagnostics; the
// caller rejects the block and the SDK rolls every operation back.
type mintResult struct {
	minted sdkmath.Int
	sent   sdkmath.Int
}

// mintAndDistribute mints totalMint into moduleName and distributes it across
// recipients. Any bank error propagates so BeginBlock's cache rolls back the
// mint and every earlier send as one state transition.
func mintAndDistribute(
	ctx sdk.Context,
	bank mintBankIface,
	moduleName, denom string,
	recipients []mintRecipient,
	totalMint sdkmath.Int,
) (mintResult, error) {
	result := mintResult{
		minted: sdkmath.ZeroInt(),
		sent:   sdkmath.ZeroInt(),
	}
	if !totalMint.IsPositive() || len(recipients) == 0 {
		return result, nil
	}
	mintCoins := sdk.NewCoins(sdk.NewCoin(denom, totalMint))
	if err := bank.MintCoins(ctx, moduleName, mintCoins); err != nil {
		return result, fmt.Errorf("mint distribution: mint %s: %w", totalMint.String(),
			haltFinalizeUnexpectedBankError(ctx, "mint_distribution", err))
	}
	result.minted = totalMint
	for _, r := range recipients {
		rewardCoins := sdk.NewCoins(sdk.NewCoin(denom, r.amount))
		if err := bank.SendCoinsFromModuleToAccount(ctx, moduleName, r.accountAddress, rewardCoins); err != nil {
			return result, fmt.Errorf("mint distribution: send to %s amount %s: %w",
				r.operatorAddress, r.amount.String(),
				haltFinalizeUnexpectedBankError(ctx, "mint_distribution_send", err))
		}
		result.sent = result.sent.Add(r.amount)
		ctx.Logger().Info("mint distribution",
			"valoper", r.operatorAddress,
			"total", r.amount.String(),
		)
	}
	return result, nil
}

// MintIfNeeded mints params.MintQuantity umirage every params.MintInterval
// blocks and distributes proportionally to validator accounts.
//
// Every state-dependent failure propagates. A node that skips minting while
// peers succeed commits a different supply and app hash even when its own local
// supply invariant remains internally consistent.
func (k Keeper) MintIfNeeded(ctx sdk.Context) error {
	current := ctx.BlockHeight()
	params := k.GetParams(ctx)

	interval, err := types.CheckedUint64ToInt64(params.MintInterval)
	if err != nil {
		return fmt.Errorf("MintIfNeeded: unusable mint_interval %d: %w", params.MintInterval, err)
	}
	if interval <= 0 {
		return fmt.Errorf("MintIfNeeded: mint_interval must be positive: %d", params.MintInterval)
	}

	// Start minting from block MintInterval, then every MintInterval thereafter
	if current < interval {
		return nil
	}

	// Mint if current block is a multiple of MintInterval
	if current%interval != 0 {
		return nil
	}

	amt := sdkmath.NewIntFromUint64(params.MintQuantity)
	if !amt.IsPositive() {
		return nil
	}

	// Get total stake and validators, excluding jailed and non-bonded
	total_stake := sdkmath.ZeroInt()
	var vals []stakingtypes.Validator
	if err := k.staking.IterateValidators(ctx, func(_ int64, valI stakingtypes.ValidatorI) (stop bool) {
		val := valI.(stakingtypes.Validator)
		if val.Jailed {
			return false
		}
		if !val.IsBonded() {
			return false
		}
		vals = append(vals, val)
		total_stake = total_stake.Add(val.Tokens)
		return false
	}); err != nil {
		return fmt.Errorf("mint distribution: iterate validators: %w",
			haltFinalizeStoreError(ctx, "staking_iterate_validators", err))
	}
	if total_stake.IsZero() {
		return nil
	}

	ctx.Logger().Info("mint interval triggered",
		"height", current,
		"mint_quantity", params.MintQuantity,
		"validators_found", len(vals),
		"total_stake", total_stake.String(),
	)

	// CRITICAL: Sort validators by operator address for deterministic processing
	// Without this, the remainder distribution is non-deterministic and causes OE aborts
	sort.Slice(vals, func(i, j int) bool {
		return vals[i].OperatorAddress < vals[j].OperatorAddress
	})

	// Split pools based on param MintDynamicSplit [0,1]
	split := params.MintDynamicSplit
	dynDec, errDec := sdkmath.LegacyNewDecFromStr(fmt.Sprintf("%.18f", split))
	if errDec != nil {
		return fmt.Errorf("mint distribution: invalid MintDynamicSplit %s: %w",
			fmt.Sprintf("%.18f", split), errDec)
	}
	dynamicPool := dynDec.MulInt(amt).TruncateInt()
	if dynamicPool.IsNegative() || dynamicPool.GT(amt) {
		return fmt.Errorf("mint distribution: dynamic pool %s outside [0,%s]",
			dynamicPool.String(), amt.String())
	}
	baselinePool := amt.Sub(dynamicPool)

	// Baseline stake-weighted distribution
	type validatorReward struct {
		validator stakingtypes.Validator
		baseline  sdkmath.Int
		dynamic   sdkmath.Int
	}
	var rewards []validatorReward

	baselineDistributed := sdkmath.ZeroInt()
	for _, val := range vals {
		share := sdkmath.LegacyNewDecFromInt(val.Tokens).Quo(sdkmath.LegacyNewDecFromInt(total_stake))
		valAmt := share.MulInt(baselinePool).TruncateInt()
		if valAmt.IsPositive() {
			baselineDistributed = baselineDistributed.Add(valAmt)
			rewards = append(rewards, validatorReward{validator: val, baseline: valAmt, dynamic: sdkmath.ZeroInt()})
		} else {
			rewards = append(rewards, validatorReward{validator: val, baseline: sdkmath.ZeroInt(), dynamic: sdkmath.ZeroInt()})
		}
		ctx.Logger().Info("baseline alloc",
			"valoper", val.OperatorAddress,
			"tokens", val.Tokens.String(),
			"share", share.String(),
			"baseline_pool", baselinePool.String(),
			"baseline_alloc", valAmt.String(),
		)
	}
	// fix baseline remainder deterministically to last
	baseRemainder := baselinePool.Sub(baselineDistributed)
	if baseRemainder.IsPositive() && len(rewards) > 0 {
		rewards[len(rewards)-1].baseline = rewards[len(rewards)-1].baseline.Add(baseRemainder)
		ctx.Logger().Info("baseline remainder assigned",
			"valoper", rewards[len(rewards)-1].validator.OperatorAddress,
			"remainder", baseRemainder.String(),
		)
	}

	// Dynamic pool: weight by (credits_i * voting_power_i)
	// Gather credits for current validators
	type dynWeight struct {
		idx    int
		weight sdkmath.LegacyDec
	}
	var weights []dynWeight
	sumWeights := sdkmath.LegacyNewDec(0)
	for i, vr := range rewards {
		credits := k.GetRelayCredit(ctx, vr.validator.OperatorAddress)
		// Cap credits by MintDynamicCreditCap per interval
		limit := sdkmath.NewIntFromUint64(params.MintDynamicCreditCap)
		creditsCapped := credits
		if credits.GT(limit) {
			creditsCapped = limit
		}
		if !creditsCapped.IsPositive() || !vr.validator.Tokens.IsPositive() {
			weights = append(weights, dynWeight{idx: i, weight: sdkmath.LegacyNewDec(0)})
			ctx.Logger().Info("dynamic weight",
				"valoper", vr.validator.OperatorAddress,
				"credits", credits.String(),
				"credits_after_cap", creditsCapped.String(),
				"limit", limit.String(),
				"tokens", vr.validator.Tokens.String(),
				"weight", "0",
			)
			continue
		}
		w := sdkmath.LegacyNewDecFromInt(creditsCapped).Mul(sdkmath.LegacyNewDecFromInt(vr.validator.Tokens))
		weights = append(weights, dynWeight{idx: i, weight: w})
		sumWeights = sumWeights.Add(w)
		ctx.Logger().Info("dynamic weight",
			"valoper", vr.validator.OperatorAddress,
			"credits", credits.String(),
			"credits_after_cap", creditsCapped.String(),
			"limit", limit.String(),
			"tokens", vr.validator.Tokens.String(),
			"weight", w.String(),
		)
	}

	dynamicAssigned := sdkmath.ZeroInt()
	if dynamicPool.IsPositive() {
		if !sumWeights.IsPositive() {
			// Fallback: no credits → stake-weighted distribution like baseline
			dynDistributed := sdkmath.ZeroInt()
			for i, vr := range rewards {
				share := sdkmath.LegacyNewDecFromInt(vr.validator.Tokens).Quo(sdkmath.LegacyNewDecFromInt(total_stake))
				valAmt := share.MulInt(dynamicPool).TruncateInt()
				rewards[i].dynamic = valAmt
				dynDistributed = dynDistributed.Add(valAmt)
				ctx.Logger().Info("dynamic fallback alloc",
					"valoper", vr.validator.OperatorAddress,
					"tokens", vr.validator.Tokens.String(),
					"share", share.String(),
					"dynamic_pool", dynamicPool.String(),
					"dynamic_alloc", valAmt.String(),
				)
			}
			rem := dynamicPool.Sub(dynDistributed)
			if rem.IsPositive() && len(rewards) > 0 {
				rewards[len(rewards)-1].dynamic = rewards[len(rewards)-1].dynamic.Add(rem)
				ctx.Logger().Info("dynamic fallback remainder assigned",
					"valoper", rewards[len(rewards)-1].validator.OperatorAddress,
					"remainder", rem.String(),
				)
			}
			dynamicAssigned = dynDistributed.Add(rem)
		} else if sumWeights.IsPositive() {
			// initial allocation proportional to weights
			lastIdxWithWeight := -1
			for _, w := range weights {
				if !w.weight.IsPositive() {
					continue
				}
				lastIdxWithWeight = w.idx
				alloc := w.weight.MulInt(dynamicPool).QuoTruncate(sumWeights).TruncateInt()
				if alloc.IsPositive() {
					rewards[w.idx].dynamic = alloc
					dynamicAssigned = dynamicAssigned.Add(alloc)
					ctx.Logger().Info("dynamic alloc initial",
						"valoper", rewards[w.idx].validator.OperatorAddress,
						"alloc", alloc.String(),
					)
				}
			}
			// final remainder, if any, add to the last with positive weight (deterministic)
			finalR := dynamicPool.Sub(dynamicAssigned)
			if finalR.IsPositive() && lastIdxWithWeight >= 0 {
				rewards[lastIdxWithWeight].dynamic = rewards[lastIdxWithWeight].dynamic.Add(finalR)
				dynamicAssigned = dynamicAssigned.Add(finalR)
				ctx.Logger().Info("dynamic alloc remainder",
					"valoper", rewards[lastIdxWithWeight].validator.OperatorAddress,
					"extra", finalR.String(),
				)
			}
		}
	}

	// Build and validate every recipient before minting.
	operatorAddrs := make([]string, len(rewards))
	amounts := make([]sdkmath.Int, len(rewards))
	for i, r := range rewards {
		operatorAddrs[i] = r.validator.OperatorAddress
		amounts[i] = r.baseline.Add(r.dynamic)
	}
	recipients, skippedInvalid, totalMint, mismatch := buildMintRecipients(operatorAddrs, amounts)
	if mismatch {
		return fmt.Errorf("mint distribution: recipient slice length mismatch: operator_addrs=%d amounts=%d",
			len(operatorAddrs), len(amounts))
	}
	if len(skippedInvalid) > 0 {
		return fmt.Errorf("mint distribution: invalid validator addresses: %s",
			strings.Join(skippedInvalid, ","))
	}

	result, err := mintAndDistribute(ctx, k.bank, types.ModuleName, k.mintDenom(), recipients, totalMint)
	if err != nil {
		return err
	}

	// Track net supply change for the O(1) EndBlock delta invariant (M-2).
	if net := result.minted; !net.IsZero() {
		if err := k.addSupplyDelta(ctx, net); err != nil {
			return fmt.Errorf("mint distribution: track supply delta %s: %w", net.String(), err)
		}
	}

	// Reset relay credits at end of interval so the next interval starts fresh.
	// A failure rolls the block back with the mint and sends.
	if err := k.ResetAllRelayCredits(ctx); err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:RELAY_CREDITS_RESET height=%d: %w",
			ctx.BlockHeight(), err)
	}

	ctx.Logger().Info("mint interval complete",
		"height", current,
		"attempted_mint", totalMint.String(),
		"minted", result.minted.String(),
		"sent", result.sent.String(),
		"validators", len(recipients),
		"skipped_invalid_validators", len(skippedInvalid),
		"total_stake", total_stake.String(),
		"baseline_pool", baselinePool.String(),
		"dynamic_pool", dynamicPool.String(),
		"dynamic_assigned", dynamicAssigned.String(),
	)
	return nil
}

// UTCJulianDayFromUnix returns the number of whole UTC days since Unix epoch.
// Day 0: 1970-01-01, Day 1: 1970-01-02, etc.
func UTCJulianDayFromUnix(unixSeconds int64) int {
	if unixSeconds <= 0 {
		return 0
	}
	return int(unixSeconds / 86400)
}

// PoW message counter keys
func (k Keeper) powMessageCountKey(height int64) []byte {
	return []byte(fmt.Sprintf("pow_msg_count:%d", height))
}

func (k Keeper) currentDifficultyKey() []byte {
	return []byte("current_difficulty")
}

func (k Keeper) consecutiveLowUsageKey() []byte {
	return []byte("consecutive_low_usage")
}

// RecordPoWMessage increments the PoW message counter for the current block
func (k Keeper) RecordPoWMessage(ctx sdk.Context) error {
	store := k.storeService.OpenKVStore(ctx)
	key := k.powMessageCountKey(ctx.BlockHeight())

	count := uint64(0)
	existing, err := store.Get(key)
	if err != nil {
		// CONSENSUS_FATAL class: node-local
		ctx.Logger().Error("CONSENSUS_FATAL:POW_COUNT_STORE_GET",
			"height", ctx.BlockHeight(), "module", "core", "op", "record", "err", err)
		consensusfatal.HaltErr(fmt.Errorf("CONSENSUS_FATAL:POW_COUNT_STORE_GET height=%d op=record: %w", ctx.BlockHeight(), err))
	}
	if len(existing) > 0 {
		if len(existing) != 8 {
			// CONSENSUS_FATAL class: deterministic
			consensusfatal.HaltErr(fmt.Errorf(
				"CONSENSUS_FATAL:POW_COUNT_DECODE height=%d op=record bytes=%d: expected 8-byte big-endian uint64",
				ctx.BlockHeight(), len(existing),
			))
		}
		count = binary.BigEndian.Uint64(existing)
	}
	count, err = types.CheckedAddUint64(count, 1)
	if err != nil {
		consensusfatal.HaltErr(fmt.Errorf(
			"CONSENSUS_FATAL:POW_COUNT_OVERFLOW height=%d op=record: %w",
			ctx.BlockHeight(), err,
		))
	}

	bz := make([]byte, 8)
	binary.BigEndian.PutUint64(bz, count)
	if err := store.Set(key, bz); err != nil {
		return err
	}
	ctx.Logger().Info("PoW message recorded", "height", ctx.BlockHeight(), "count", count)
	return nil
}

// GetPoWMessageCount returns the number of PoW messages in the current window
func (k Keeper) GetPoWMessageCount(ctx sdk.Context, params types.Params) uint64 {
	store := k.storeService.OpenKVStore(ctx)
	currentHeight := ctx.BlockHeight()
	// A window outside the governance-safe bound cannot be summed: clamping it
	// would sum a different range than peers, and iterating it would be an
	// unbounded sweep (review M-7). Params.Validate rejects such values, so
	// reaching here means raw-imported or upgrade-written state.
	periodStart, err := types.CheckedWindowStart(currentHeight, params.PowMessageWindow)
	if err != nil {
		ctx.Logger().Error("CONSENSUS_FATAL:POW_WINDOW_PARAM",
			"height", currentHeight, "window", params.PowMessageWindow, "op", "window_sum", "err", err)
		consensusfatal.HaltErr(fmt.Errorf("CONSENSUS_FATAL:POW_WINDOW_PARAM height=%d window=%d op=window_sum: %w",
			currentHeight, params.PowMessageWindow, err))
	}

	total := uint64(0)
	for height := periodStart; height <= currentHeight; height++ {
		key := k.powMessageCountKey(height)
		bz, err := store.Get(key)
		if err != nil {
			// CONSENSUS_FATAL class: node-local
			ctx.Logger().Error("CONSENSUS_FATAL:POW_COUNT_STORE_GET",
				"height", ctx.BlockHeight(), "read_height", height, "module", "core", "op", "window_sum", "err", err)
			consensusfatal.HaltErr(fmt.Errorf("CONSENSUS_FATAL:POW_COUNT_STORE_GET height=%d read_height=%d op=window_sum: %w", ctx.BlockHeight(), height, err))
		}
		if len(bz) > 0 {
			if len(bz) != 8 {
				// CONSENSUS_FATAL class: deterministic
				consensusfatal.HaltErr(fmt.Errorf(
					"CONSENSUS_FATAL:POW_COUNT_DECODE height=%d read_height=%d op=window_sum bytes=%d: expected 8-byte big-endian uint64",
					ctx.BlockHeight(), height, len(bz),
				))
			}
			total, err = types.CheckedAddUint64(total, binary.BigEndian.Uint64(bz))
			if err != nil {
				consensusfatal.HaltErr(fmt.Errorf(
					"CONSENSUS_FATAL:POW_COUNT_OVERFLOW height=%d read_height=%d op=window_sum: %w",
					ctx.BlockHeight(), height, err,
				))
			}
		}
	}
	return total
}

// CleanupOldCounters removes counters older than the retention period
func (k Keeper) CleanupOldCounters(ctx sdk.Context, params types.Params) error {
	store := k.storeService.OpenKVStore(ctx)
	currentHeight := ctx.BlockHeight()
	// Keep 2 windows worth of data for safety margin
	retention, err := types.CheckedMulUint64(params.PowMessageWindow, 2)
	if err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:POW_WINDOW_PARAM height=%d window=%d op=cleanup: %w",
			currentHeight, params.PowMessageWindow, err)
	}
	retentionHeights, err := types.CheckedUint64ToInt64(retention)
	if err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:POW_WINDOW_PARAM height=%d window=%d op=cleanup: %w",
			currentHeight, params.PowMessageWindow, err)
	}
	cutoffHeight := currentHeight - retentionHeights

	if cutoffHeight < 1 {
		return nil // Nothing to clean up yet
	}

	// Clean up in batches to avoid expensive operations in a single block
	// Delete up to 100 old counter keys per block
	const maxDeletesPerBlock = 100
	deleted := 0

	// Start from the oldest possible height (genesis = 1) and work up to cutoff
	// We use a stored marker to track cleanup progress across blocks
	// A node-local Get failure must not be read as "no marker": that would
	// restart this node's sweep at height 1 while peers continue from the
	// stored cursor, committing a different counter keyset and therefore a
	// different app hash (review M-6).
	markerKey := []byte("pow_cleanup_marker")
	startHeight := int64(1)
	markerBz, err := store.Get(markerKey)
	if err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:POW_CLEANUP_MARKER_GET height=%d: %w", currentHeight, err)
	}
	if len(markerBz) > 0 {
		if len(markerBz) != 8 {
			return fmt.Errorf("CONSENSUS_FATAL:POW_CLEANUP_MARKER_LEN height=%d len=%d", currentHeight, len(markerBz))
		}
		marker, err := types.CheckedUint64ToInt64(binary.BigEndian.Uint64(markerBz))
		if err != nil {
			return fmt.Errorf("CONSENSUS_FATAL:POW_CLEANUP_MARKER_RANGE height=%d: %w", currentHeight, err)
		}
		if marker < 1 || marker > currentHeight {
			return fmt.Errorf("CONSENSUS_FATAL:POW_CLEANUP_MARKER_RANGE height=%d marker=%d", currentHeight, marker)
		}
		startHeight = marker
	}

	for height := startHeight; height <= cutoffHeight && deleted < maxDeletesPerBlock; height++ {
		key := k.powMessageCountKey(height)
		// Try to delete - it's fine if the key doesn't exist
		if err := store.Delete(key); err != nil {
			return fmt.Errorf("failed to delete pow counter at height %d: %w", height, err)
		}
		deleted++
		startHeight = height + 1
	}

	// Store progress marker for next block
	if deleted > 0 {
		bz := make([]byte, 8)
		binary.BigEndian.PutUint64(bz, uint64(startHeight))
		if err := store.Set(markerKey, bz); err != nil {
			return fmt.Errorf("failed to update cleanup marker: %w", err)
		}
	}

	if deleted > 0 {
		ctx.Logger().Debug("CleanupOldCounters", "deleted", deleted, "next_start", startHeight)
	}
	return nil
}

// ClearPoWWindow deletes PoW message counters in the current window
func (k Keeper) ClearPoWWindow(ctx sdk.Context, params types.Params) error {
	store := k.storeService.OpenKVStore(ctx)
	currentHeight := ctx.BlockHeight()
	start, err := types.CheckedWindowStart(currentHeight, params.PowMessageWindow)
	if err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:POW_WINDOW_PARAM height=%d window=%d op=window_clear: %w",
			currentHeight, params.PowMessageWindow, err)
	}
	for h := start; h <= currentHeight; h++ {
		key := k.powMessageCountKey(h)
		// A partial clear feeds a different sliding-window count into the
		// next block's difficulty decision than peers see (review L-2).
		if err := store.Delete(key); err != nil {
			return fmt.Errorf("CONSENSUS_FATAL:POW_WINDOW_CLEAR height=%d: %w", h, err)
		}
	}
	return nil
}

// BaseDifficultySteps is the default difficulty step (0 = base).
const BaseDifficultySteps uint64 = 0

// BaseDifficultyFactor is the base work factor (1.0x).
const BaseDifficultyFactor uint64 = 1000

// MaxSafeDifficultyFactor caps the factor to 2^53-1 so JSON/JS Number is lossless.
const MaxSafeDifficultyFactor uint64 = (1 << 53) - 1

// MaxSafeDifficultySteps bounds exact rational exponentiation cost in ante.
const MaxSafeDifficultySteps uint64 = 10_000

// GetCurrentDifficulty returns the current dynamic difficulty step.
// 0 = base difficulty. Higher values = harder via (1 + pow_factor)^difficulty.
func (k Keeper) GetCurrentDifficulty(ctx sdk.Context) uint64 {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.currentDifficultyKey())
	if err != nil {
		// CONSENSUS_FATAL class: node-local
		ctx.Logger().Error("CONSENSUS_FATAL:DIFFICULTY_STORE_GET",
			"height", ctx.BlockHeight(), "module", "core", "err", err)
		consensusfatal.HaltErr(fmt.Errorf("CONSENSUS_FATAL:DIFFICULTY_STORE_GET height=%d: %w", ctx.BlockHeight(), err))
	}
	if len(bz) == 0 {
		return BaseDifficultySteps
	}
	if len(bz) != 8 {
		consensusfatal.HaltErr(fmt.Errorf(
			"CONSENSUS_FATAL:DIFFICULTY_DECODE height=%d bytes=%d: expected 8-byte big-endian uint64",
			ctx.BlockHeight(), len(bz),
		))
	}
	v := binary.BigEndian.Uint64(bz)
	if v > MaxSafeDifficultySteps {
		consensusfatal.HaltErr(fmt.Errorf(
			"CONSENSUS_FATAL:DIFFICULTY_RANGE height=%d difficulty=%d max=%d",
			ctx.BlockHeight(), v, MaxSafeDifficultySteps,
		))
	}
	return v
}

// HasCurrentDifficulty returns true if the current_difficulty key exists in store
func (k Keeper) HasCurrentDifficulty(ctx sdk.Context) bool {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.currentDifficultyKey())
	if err != nil {
		// CONSENSUS_FATAL class: node-local
		ctx.Logger().Error("CONSENSUS_FATAL:DIFFICULTY_STORE_GET",
			"height", ctx.BlockHeight(), "module", "core", "op", "has", "err", err)
		consensusfatal.HaltErr(fmt.Errorf("CONSENSUS_FATAL:DIFFICULTY_STORE_GET height=%d op=has: %w", ctx.BlockHeight(), err))
	}
	return len(bz) > 0
}

func (k Keeper) previousDifficultyKey() []byte { return []byte("prev_difficulty") }
func (k Keeper) lastChangeHeightKey() []byte   { return []byte("last_diff_change_height") }

// SetCurrentDifficulty sets the current dynamic difficulty and records previous value and change height
func (k Keeper) SetCurrentDifficulty(ctx sdk.Context, difficulty uint64) error {
	if difficulty > MaxSafeDifficultySteps {
		return fmt.Errorf("difficulty %d exceeds max %d", difficulty, MaxSafeDifficultySteps)
	}
	store := k.storeService.OpenKVStore(ctx)
	// read old
	old := k.GetCurrentDifficulty(ctx)
	// write new current
	bz := make([]byte, 8)
	binary.BigEndian.PutUint64(bz, difficulty)
	if err := store.Set(k.currentDifficultyKey(), bz); err != nil {
		return err
	}
	// Previous difficulty and change height are read by the ante grace window,
	// so all three writes are one state transition. A failure here returns an
	// error and the caller's cache rollback undoes the current write (L-3).
	pbz := make([]byte, 8)
	binary.BigEndian.PutUint64(pbz, old)
	if err := store.Set(k.previousDifficultyKey(), pbz); err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:PREV_DIFFICULTY_SET height=%d: %w", ctx.BlockHeight(), err)
	}
	hbz := make([]byte, 8)
	binary.BigEndian.PutUint64(hbz, uint64(ctx.BlockHeight()))
	if err := store.Set(k.lastChangeHeightKey(), hbz); err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:DIFFICULTY_CHANGE_HEIGHT_SET height=%d: %w", ctx.BlockHeight(), err)
	}
	return nil
}

// GetPreviousDifficulty returns previous difficulty or current if unset
func (k Keeper) GetPreviousDifficulty(ctx sdk.Context) uint64 {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.previousDifficultyKey())
	if err != nil {
		// CONSENSUS_FATAL class: node-local
		ctx.Logger().Error("CONSENSUS_FATAL:PREV_DIFFICULTY_STORE_GET",
			"height", ctx.BlockHeight(), "module", "core", "err", err)
		consensusfatal.HaltErr(fmt.Errorf("CONSENSUS_FATAL:PREV_DIFFICULTY_STORE_GET height=%d: %w", ctx.BlockHeight(), err))
	}
	if len(bz) == 0 {
		return k.GetCurrentDifficulty(ctx)
	}
	if len(bz) != 8 {
		consensusfatal.HaltErr(fmt.Errorf(
			"CONSENSUS_FATAL:PREV_DIFFICULTY_DECODE height=%d bytes=%d: expected 8-byte big-endian uint64",
			ctx.BlockHeight(), len(bz),
		))
	}
	v := binary.BigEndian.Uint64(bz)
	if v > MaxSafeDifficultySteps {
		consensusfatal.HaltErr(fmt.Errorf(
			"CONSENSUS_FATAL:PREV_DIFFICULTY_RANGE height=%d difficulty=%d max=%d",
			ctx.BlockHeight(), v, MaxSafeDifficultySteps,
		))
	}
	return v
}

// GetLastDifficultyChangeHeight returns the height of the last difficulty change
func (k Keeper) GetLastDifficultyChangeHeight(ctx sdk.Context) int64 {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.lastChangeHeightKey())
	if err != nil {
		// CONSENSUS_FATAL class: node-local
		ctx.Logger().Error("CONSENSUS_FATAL:LAST_DIFF_CHANGE_STORE_GET",
			"height", ctx.BlockHeight(), "module", "core", "err", err)
		consensusfatal.HaltErr(fmt.Errorf("CONSENSUS_FATAL:LAST_DIFF_CHANGE_STORE_GET height=%d: %w", ctx.BlockHeight(), err))
	}
	if len(bz) == 0 {
		return 0
	}
	if len(bz) != 8 {
		consensusfatal.HaltErr(fmt.Errorf(
			"CONSENSUS_FATAL:LAST_DIFF_CHANGE_DECODE height=%d bytes=%d: expected 8-byte big-endian uint64",
			ctx.BlockHeight(), len(bz),
		))
	}
	v := binary.BigEndian.Uint64(bz)
	height, err := types.CheckedUint64ToInt64(v)
	if err != nil {
		consensusfatal.HaltErr(fmt.Errorf(
			"CONSENSUS_FATAL:LAST_DIFF_CHANGE_RANGE height=%d stored=%d: %w",
			ctx.BlockHeight(), v, err,
		))
	}
	return height
}

// GetConsecutiveLowUsage returns the number of consecutive blocks with low usage
func (k Keeper) GetConsecutiveLowUsage(ctx sdk.Context) uint64 {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.consecutiveLowUsageKey())
	if err != nil {
		// CONSENSUS_FATAL class: node-local
		ctx.Logger().Error("CONSENSUS_FATAL:CONSECUTIVE_LOW_USAGE_STORE_GET",
			"height", ctx.BlockHeight(), "module", "core", "err", err)
		consensusfatal.HaltErr(fmt.Errorf("CONSENSUS_FATAL:CONSECUTIVE_LOW_USAGE_STORE_GET height=%d: %w", ctx.BlockHeight(), err))
	}
	if len(bz) == 0 {
		return 0
	}
	if len(bz) != 8 {
		consensusfatal.HaltErr(fmt.Errorf(
			"CONSENSUS_FATAL:CONSECUTIVE_LOW_USAGE_DECODE height=%d bytes=%d: expected 8-byte big-endian uint64",
			ctx.BlockHeight(), len(bz),
		))
	}
	v := binary.BigEndian.Uint64(bz)
	if v > types.MaxPowCalmSequenceThreshold {
		consensusfatal.HaltErr(fmt.Errorf(
			"CONSENSUS_FATAL:CONSECUTIVE_LOW_USAGE_RANGE height=%d count=%d max=%d",
			ctx.BlockHeight(), v, types.MaxPowCalmSequenceThreshold,
		))
	}
	return v
}

// SetConsecutiveLowUsage sets the number of consecutive blocks with low usage
func (k Keeper) SetConsecutiveLowUsage(ctx sdk.Context, count uint64) error {
	if count > types.MaxPowCalmSequenceThreshold {
		return fmt.Errorf("consecutive low usage %d exceeds max %d", count, types.MaxPowCalmSequenceThreshold)
	}
	store := k.storeService.OpenKVStore(ctx)
	bz := make([]byte, 8)
	binary.BigEndian.PutUint64(bz, count)
	return store.Set(k.consecutiveLowUsageKey(), bz)
}

// Subscription tracking methods

// subscriptionKey builds the key for subscription index: subs/{expiry_hex}:{address}
func (k Keeper) subscriptionKey(expiry int64, addr string) []byte {
	// Use hex-encoded expiry for lexicographic ordering
	return []byte(fmt.Sprintf("%s%016x:%s", types.SubscriptionsPrefix, expiry, addr))
}

// SetSubscription indexes a subscription for renewal tracking
func (k Keeper) SetSubscription(ctx sdk.Context, addr string, level int, expiry int64) error {
	if expiry <= 0 {
		return fmt.Errorf("subscription expiry must be positive: %d", expiry)
	}
	if level < 0 || uint64(level) > math.MaxUint32 {
		return fmt.Errorf("subscription level out of uint32 range: %d", level)
	}
	store := k.storeService.OpenKVStore(ctx)
	key := k.subscriptionKey(expiry, addr)
	bz := make([]byte, 4)
	binary.BigEndian.PutUint32(bz, uint32(level))
	return store.Set(key, bz)
}

// RemoveSubscription removes a subscription from the index
func (k Keeper) RemoveSubscription(ctx sdk.Context, addr string, expiry int64) error {
	store := k.storeService.OpenKVStore(ctx)
	key := k.subscriptionKey(expiry, addr)
	return store.Delete(key)
}

// ExpiredSubscription represents a subscription that needs renewal
type ExpiredSubscription struct {
	Address string
	Level   int
	Expiry  int64
}

// GetExpiredSubscriptions returns all subscriptions with expiry <= timestamp
func (k Keeper) GetExpiredSubscriptions(ctx sdk.Context, timestamp int64) ([]ExpiredSubscription, error) {
	if timestamp < 0 {
		return nil, fmt.Errorf("subscription expiry scan timestamp must be non-negative: %d", timestamp)
	}
	exclusiveEnd, err := types.CheckedAddInt64(timestamp, 1)
	if err != nil {
		return nil, fmt.Errorf("subscription expiry scan end: %w", err)
	}
	store := k.storeService.OpenKVStore(ctx)
	prefix := []byte(types.SubscriptionsPrefix)
	// End key is for all subscriptions with expiry <= timestamp
	endKey := []byte(fmt.Sprintf("%s%016x:", types.SubscriptionsPrefix, exclusiveEnd))

	var expired []ExpiredSubscription

	iterator, err := store.Iterator(prefix, endKey)
	if err != nil {
		return nil, err
	}

	for ; iterator.Valid(); iterator.Next() {
		key := string(iterator.Key())
		// Parse key: subs/{expiry_hex}:{address}
		trimmed := strings.TrimPrefix(key, types.SubscriptionsPrefix)
		parts := strings.SplitN(trimmed, ":", 2)
		if len(parts) != 2 {
			_ = iterator.Close()
			return nil, fmt.Errorf("malformed subscription index key %q", key)
		}
		expiryUint, err := strconv.ParseUint(parts[0], 16, 64)
		if err != nil {
			_ = iterator.Close()
			return nil, fmt.Errorf("malformed subscription expiry in key %q: %w", key, err)
		}
		expiry, err := types.CheckedUint64ToInt64(expiryUint)
		if err != nil {
			_ = iterator.Close()
			return nil, fmt.Errorf("subscription expiry out of range in key %q: %w", key, err)
		}
		addr := parts[1]
		if strings.TrimSpace(addr) == "" {
			_ = iterator.Close()
			return nil, fmt.Errorf("subscription index key %q has empty address", key)
		}
		value := iterator.Value()
		if len(value) != 4 {
			_ = iterator.Close()
			return nil, fmt.Errorf("malformed subscription level for %q: expected 4 bytes, got %d",
				key, len(value))
		}
		level := int(binary.BigEndian.Uint32(value))
		expired = append(expired, ExpiredSubscription{
			Address: addr,
			Level:   level,
			Expiry:  expiry,
		})
	}
	if err := iterator.Error(); err != nil {
		_ = iterator.Close()
		return nil, err
	}
	if err := iterator.Close(); err != nil {
		return nil, err
	}

	return expired, nil
}

// BurnFromAccount burns tokens from a user account by sending to module and burning
func (k Keeper) BurnFromAccount(ctx sdk.Context, addr string, amount uint64) error {
	if amount == 0 {
		return nil
	}
	accAddr, err := sdk.AccAddressFromBech32(addr)
	if err != nil {
		return err
	}
	coin := sdk.NewCoin(k.mintDenom(), sdkmath.NewIntFromUint64(amount))
	coins := sdk.NewCoins(coin)
	if !k.bankSpendableCoins(ctx, accAddr).IsAllGTE(coins) {
		return sdkerrors.ErrInsufficientFunds.Wrapf("spendable balance is smaller than %s", coins)
	}

	// Send to module account first
	if err := k.bank.SendCoinsFromAccountToModule(ctx, accAddr, types.ModuleName, coins); err != nil {
		return haltFinalizeUnexpectedBankError(ctx, "move_account_balance_for_burn", err)
	}
	// Then burn from module (tracked for O(1) supply delta invariant)
	return k.burnCoinsTracked(ctx, coin.Amount)
}

// DeleteUserState removes all on-chain state for a user:
// profile core, all profile lists, username mapping, subscription index,
// and sweeps spendable balances to the community pool.
//
// username and subscriptionExpiry come from the caller's already-decoded
// profile. Reloading and re-decoding them here used to discard both the Get
// and the unmarshal error, which could delete the profile while leaving its
// username mapping or subscription index behind — and a surviving index later
// trips CONSENSUS_FATAL:PROFILE_MISSING (review M-3).
//
// Returns the swept amounts. Rollback of earlier deletes on a later failure is
// the caller's transaction cache, not a compensating write here.
func (k Keeper) DeleteUserState(ctx sdk.Context, addr, username string, subscriptionExpiry int64) (sweptAmounts sdk.Coins, err error) {
	store := k.storeService.OpenKVStore(ctx)
	accAddr, err := sdk.AccAddressFromBech32(addr)
	if err != nil {
		return nil, fmt.Errorf("invalid address: %w", err)
	}

	// Delete profile core KV
	if err := store.Delete(k.profileKey(addr)); err != nil {
		return nil, err
	}

	// Delete all per-entry list keys (prefix-range delete + count + seq for each list)
	if err := k.DeleteAllEnabledAgents(ctx, addr); err != nil {
		return nil, err
	}
	if err := k.DeleteAllFollowedUsers(ctx, addr); err != nil {
		return nil, err
	}
	if err := k.DeleteAllFollowedTopics(ctx, addr); err != nil {
		return nil, err
	}
	if err := k.DeleteAllBlockedUsers(ctx, addr); err != nil {
		return nil, err
	}
	if err := k.DeleteAllBlockedPosts(ctx, addr); err != nil {
		return nil, err
	}
	if err := k.DeleteAllBlockedTopics(ctx, addr); err != nil {
		return nil, err
	}
	// Also delete legacy blob keys in case they exist (pre-migration data)
	if err := store.Delete(k.profileEnabledAgentsKey(addr)); err != nil {
		return nil, err
	}
	if err := store.Delete(k.profileFollowedUsersKey(addr)); err != nil {
		return nil, err
	}
	if err := store.Delete(k.profileFollowedTopicsKey(addr)); err != nil {
		return nil, err
	}
	if err := store.Delete(k.profileBlockedUsersKey(addr)); err != nil {
		return nil, err
	}
	if err := store.Delete(k.profileBlockedPostsKey(addr)); err != nil {
		return nil, err
	}
	if err := store.Delete(k.profileBlockedTopicsKey(addr)); err != nil {
		return nil, err
	}

	// Release username mapping
	if username != "" {
		if err := k.ReleaseUsername(ctx, username, addr); err != nil {
			return nil, err
		}
	}

	// Remove subscription index entry if present. Discarding this error left a
	// stale index pointing at a deleted profile.
	if subscriptionExpiry > 0 {
		if err := k.RemoveSubscription(ctx, addr, subscriptionExpiry); err != nil {
			return nil, fmt.Errorf("failed to remove subscription index for %s at expiry %d: %w",
				addr, subscriptionExpiry, err)
		}
	}

	// Sweep all spendable balances to community pool
	spendable := k.bankSpendableCoins(ctx, accAddr)
	if spendable.IsAllPositive() {
		if err := k.distribution.FundCommunityPool(ctx, spendable, accAddr); err != nil {
			return nil, fmt.Errorf("failed to sweep funds to community pool: %w",
				haltFinalizeUnexpectedBankError(ctx, "fund_community_pool", err))
		}
		sweptAmounts = spendable
	}

	return sweptAmounts, nil
}

// GetTotalBondedValidatorPower returns the total voting power of all bonded validators
func (k Keeper) GetTotalBondedValidatorPower(ctx sdk.Context) (int64, error) {
	var totalPower int64
	err := k.staking.IterateBondedValidatorsByPower(ctx, func(_ int64, validator stakingtypes.ValidatorI) bool {
		totalPower += validator.GetConsensusPower(k.staking.PowerReduction(ctx))
		return false
	})
	return totalPower, haltFinalizeStoreError(ctx, "staking_iterate_bonded_validators", err)
}

// GetValidatorPower returns the voting power of a specific validator
func (k Keeper) GetValidatorPower(ctx sdk.Context, valoper string) (int64, error) {
	valAddr, err := sdk.ValAddressFromBech32(valoper)
	if err != nil {
		return 0, fmt.Errorf("invalid validator address: %w", err)
	}
	validator, err := k.staking.GetValidator(ctx, valAddr)
	if err != nil {
		if errors.Is(err, stakingtypes.ErrNoValidatorFound) {
			return 0, fmt.Errorf("validator not found: %w", err)
		}
		return 0, haltFinalizeStoreError(ctx, "staking_get_validator_power", err)
	}
	if !validator.IsBonded() {
		return 0, fmt.Errorf("validator not bonded")
	}
	return validator.GetConsensusPower(k.staking.PowerReduction(ctx)), nil
}

// IsValidatorBonded returns true if the validator is currently bonded
func (k Keeper) IsValidatorBonded(ctx sdk.Context, valoper string) (bool, error) {
	valAddr, err := sdk.ValAddressFromBech32(valoper)
	if err != nil {
		return false, err
	}
	validator, err := k.staking.GetValidator(ctx, valAddr)
	if err != nil {
		if errors.Is(err, stakingtypes.ErrNoValidatorFound) {
			return false, nil
		}
		return false, haltFinalizeStoreError(ctx, "staking_is_validator_bonded", err)
	}
	return validator.IsBonded(), nil
}

// HasEnvelopeNonce checks if a nonce has been seen for the given pubkey hash.
func (k Keeper) HasEnvelopeNonce(ctx sdk.Context, pubkeyHash []byte, nonce uint64) bool {
	store := k.storeService.OpenKVStore(ctx)
	key := []byte(fmt.Sprintf("%s%x/%d", types.EnvelopeNoncePrefix, pubkeyHash, nonce))
	found, err := store.Has(key)
	if err != nil {
		// CONSENSUS_FATAL class: node-local
		ctx.Logger().Error("CONSENSUS_FATAL:ENVELOPE_NONCE_STORE_HAS",
			"height", ctx.BlockHeight(), "module", "core", "err", err)
		consensusfatal.HaltErr(fmt.Errorf("CONSENSUS_FATAL:ENVELOPE_NONCE_STORE_HAS height=%d: %w", ctx.BlockHeight(), err))
	}
	return found
}

// SetEnvelopeNonce records a nonce for the given pubkey hash with an expiry time.
func (k Keeper) SetEnvelopeNonce(ctx sdk.Context, pubkeyHash []byte, nonce uint64, expiryUnix int64) error {
	if expiryUnix <= 0 {
		return fmt.Errorf("envelope nonce expiry must be positive: %d", expiryUnix)
	}
	store := k.storeService.OpenKVStore(ctx)
	key := []byte(fmt.Sprintf("%s%x/%d", types.EnvelopeNoncePrefix, pubkeyHash, nonce))
	if err := store.Set(key, []byte{}); err != nil {
		return err
	}
	// Also set expiry index for pruning
	expiryKey := []byte(fmt.Sprintf("%s%020d/%x/%d", types.EnvelopeNonceExpiryPrefix, expiryUnix, pubkeyHash, nonce))
	if err := store.Set(expiryKey, []byte{}); err != nil {
		return err
	}
	ctx.Logger().Debug("RelaySig: stored envelope nonce", "nonce", nonce, "expiry_unix", expiryUnix)
	return nil
}

// PruneExpiredNonces removes all nonce entries that have expired.
func (k Keeper) PruneExpiredNonces(ctx sdk.Context, nowUnix int64) (int, error) {
	if nowUnix < 0 {
		return 0, fmt.Errorf("envelope nonce prune time must be non-negative: %d", nowUnix)
	}
	exclusiveEnd, err := types.CheckedAddInt64(nowUnix, 1)
	if err != nil {
		return 0, fmt.Errorf("envelope nonce prune cutoff: %w", err)
	}
	store := k.storeService.OpenKVStore(ctx)
	prefix := []byte(types.EnvelopeNonceExpiryPrefix)
	// End key is exclusive; use nowUnix+1 so we include entries expiring exactly at nowUnix
	cutoff := []byte(fmt.Sprintf("%s%020d/", types.EnvelopeNonceExpiryPrefix, exclusiveEnd))

	iter, err := store.Iterator(prefix, cutoff)
	if err != nil {
		return 0, err
	}

	var toDelete [][]byte
	for ; iter.Valid(); iter.Next() {
		toDelete = append(toDelete, append([]byte{}, iter.Key()...))
	}
	if err := iter.Error(); err != nil {
		_ = iter.Close()
		return 0, err
	}
	if err := iter.Close(); err != nil {
		return 0, err
	}

	pruned := 0
	for _, expiryKey := range toDelete {
		// Parse the nonce key from the expiry key
		// Format: envelope_nonce_expiry/{expiry_unix}/{pubkey_hash}/{nonce}
		// We need to reconstruct: envelope_nonce/{pubkey_hash}/{nonce}
		suffix := string(expiryKey[len(types.EnvelopeNonceExpiryPrefix):])
		if len(suffix) <= 21 || suffix[20] != '/' {
			return pruned, fmt.Errorf("invalid envelope nonce expiry key: %q", string(expiryKey))
		}
		expiry, err := strconv.ParseInt(suffix[:20], 10, 64)
		if err != nil || expiry < 0 || expiry > nowUnix {
			return pruned, fmt.Errorf("invalid envelope nonce expiry timestamp in key %q", string(expiryKey))
		}
		nonceParts := strings.Split(suffix[21:], "/")
		if len(nonceParts) != 2 || nonceParts[0] == "" || nonceParts[1] == "" {
			return pruned, fmt.Errorf("invalid envelope nonce expiry key: %q", string(expiryKey))
		}
		pubkeyHash, err := hex.DecodeString(nonceParts[0])
		if err != nil || len(pubkeyHash) == 0 {
			return pruned, fmt.Errorf("invalid envelope nonce pubkey hash in key %q", string(expiryKey))
		}
		nonce, err := strconv.ParseUint(nonceParts[1], 10, 64)
		if err != nil {
			return pruned, fmt.Errorf("invalid envelope nonce in key %q", string(expiryKey))
		}
		canonicalSuffix := fmt.Sprintf("%020d/%x/%d", expiry, pubkeyHash, nonce)
		if suffix != canonicalSuffix {
			return pruned, fmt.Errorf("non-canonical envelope nonce expiry key: %q", string(expiryKey))
		}
		nonceKeySuffix := suffix[21:]
		nonceKey := []byte(types.EnvelopeNoncePrefix + nonceKeySuffix)
		if err := store.Delete(nonceKey); err != nil {
			return pruned, err
		}
		if err := store.Delete(expiryKey); err != nil {
			return pruned, err
		}
		pruned++
	}
	return pruned, nil
}
