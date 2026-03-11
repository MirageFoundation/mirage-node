package keeper

import (
	"bytes"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"mirage/x/core/types"

	corestore "cosmossdk.io/core/store"
	sdkmath "cosmossdk.io/math"
	storetypes "cosmossdk.io/store/types"
	"github.com/cosmos/cosmos-sdk/codec"
	sdk "github.com/cosmos/cosmos-sdk/types"
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
	return Keeper{storeService: storeService, cdc: cdc, bank: bank, staking: staking, distribution: distribution, slashing: slashing}
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
func getUint32(b []byte) uint32 {
	if len(b) < 4 {
		return 0
	}
	return binary.BigEndian.Uint32(b)
}
func putUint64(v uint64) []byte { b := make([]byte, 8); binary.BigEndian.PutUint64(b, v); return b }
func getUint64(b []byte) uint64 {
	if len(b) < 8 {
		return 0
	}
	return binary.BigEndian.Uint64(b)
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
// Writes the entry first, then increments the count (crash-safety: orphan entry
// is harmless and will be counted on next List call).
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
	// Increment count
	ck := countKey(prefix, owner)
	cb, _ := store.Get(ck)
	cnt := getUint32(cb) + 1
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
	cb, _ := store.Get(ck)
	cnt := getUint32(cb)
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

func (k Keeper) countSetEntries(ctx sdk.Context, prefix, owner string) uint32 {
	store := k.storeService.OpenKVStore(ctx)
	b, _ := store.Get(countKey(prefix, owner))
	return getUint32(b)
}

// listSetEntries returns all entries for an owner (unordered).
func (k Keeper) listSetEntries(ctx sdk.Context, prefix, owner string) ([]string, error) {
	store := k.storeService.OpenKVStore(ctx)
	pfx := entryPrefix(prefix, owner)
	it, err := store.Iterator(pfx, prefixEndBytes(pfx))
	if err != nil {
		return nil, err
	}
	defer it.Close()

	pfxLen := len(pfx)
	var out []string
	for ; it.Valid(); it.Next() {
		key := it.Key()
		if len(key) > pfxLen {
			out = append(out, string(key[pfxLen:]))
		}
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
	it.Close()
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
	// Get next sequence (position)
	sk := seqKey(prefix, owner)
	sb, _ := store.Get(sk)
	seq := getUint64(sb)
	if err := store.Set(ek, putUint64(seq)); err != nil {
		return false, err
	}
	if err := store.Set(sk, putUint64(seq+1)); err != nil {
		return false, err
	}
	ck := countKey(prefix, owner)
	cb, _ := store.Get(ck)
	cnt := getUint32(cb) + 1
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
	defer it.Close()

	pfxLen := len(pfx)
	type kv struct {
		entry string
		pos   uint64
	}
	var items []kv
	for ; it.Valid(); it.Next() {
		key := it.Key()
		if len(key) > pfxLen {
			items = append(items, kv{entry: string(key[pfxLen:]), pos: getUint64(it.Value())})
		}
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
	// Assign next sequence
	sk := seqKey(prefix, owner)
	sb, _ := store.Get(sk)
	seq := getUint64(sb)
	if err := store.Set(ek, putUint64(seq)); err != nil {
		return false, err
	}
	if err := store.Set(sk, putUint64(seq+1)); err != nil {
		return false, err
	}
	// Increment count
	ck := countKey(prefix, owner)
	cb, _ := store.Get(ck)
	cnt := getUint32(cb) + 1
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
	defer it.Close()

	var minKey []byte
	var minSeq uint64
	first := true
	for ; it.Valid(); it.Next() {
		s := getUint64(it.Value())
		if first || s < minSeq {
			minKey = append([]byte(nil), it.Key()...)
			minSeq = s
			first = false
		}
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

func (k Keeper) CountFollowedUsers(ctx sdk.Context, owner string) uint32 {
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

func (k Keeper) CountFollowedTopics(ctx sdk.Context, owner string) uint32 {
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

func (k Keeper) CountEnabledAgents(ctx sdk.Context, owner string) uint32 {
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

func (k Keeper) CountBlockedUsers(ctx sdk.Context, owner string) uint32 {
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

func (k Keeper) CountBlockedPosts(ctx sdk.Context, owner string) uint32 {
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

func (k Keeper) CountBlockedTopics(ctx sdk.Context, owner string) uint32 {
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
	defer iterator.Close()

	for ; iterator.Valid(); iterator.Next() {
		profiles = append(profiles, iterator.Value())
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
	defer iterator.Close()

	count := uint64(0)
	for ; iterator.Valid() && count < limit; iterator.Next() {
		profiles = append(profiles, iterator.Value())
		count++
	}

	// If there are more results, return the next key (without prefix)
	if iterator.Valid() {
		fullKey := iterator.Key()
		if len(fullKey) > len(profilesPrefix) {
			nextKey = fullKey[len(profilesPrefix):]
		}
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
	defer iterator.Close()

	for ; iterator.Valid(); iterator.Next() {
		pairs = append(pairs, &types.RawKVPair{
			Key:   base64.StdEncoding.EncodeToString(iterator.Key()),
			Value: base64.StdEncoding.EncodeToString(iterator.Value()),
		})
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
	return k.bank.SendCoinsFromAccountToModule(ctx, addr, types.ModuleName, sdk.NewCoins(coin))
}

// GetBalance returns the spendable balance for denom on an address.
func (k Keeper) GetBalance(ctx sdk.Context, owner string, denom string) sdkmath.Int {
	addr, err := sdk.AccAddressFromBech32(owner)
	if err != nil {
		return sdkmath.NewInt(0)
	}
	return k.bank.GetBalance(ctx, addr, denom).Amount
}

// SendCoins transfers coins from one account to another using the bank keeper.
func (k Keeper) SendCoins(ctx sdk.Context, fromAddr sdk.AccAddress, toAddr sdk.AccAddress, amt sdk.Coins) error {
	return k.bank.SendCoins(ctx, fromAddr, toAddr, amt)
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
		return fmt.Errorf("validator not found: %w", err)
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
			return fmt.Errorf("slash failed: %w", err)
		}
	}

	// Jail if requested
	if jail {
		if err := k.slashing.Jail(sdk.WrapSDKContext(ctx), consAddr); err != nil {
			return fmt.Errorf("jail failed: %w", err)
		}
	}

	// Tombstone if requested
	if tombstone {
		if err := k.slashing.Tombstone(sdk.WrapSDKContext(ctx), consAddr); err != nil {
			return fmt.Errorf("tombstone failed: %w", err)
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
	if err != nil || len(bz) == 0 {
		return sdkmath.ZeroInt()
	}
	// value is big-endian uint64 for simplicity
	if len(bz) == 8 {
		return sdkmath.NewIntFromUint64(binary.BigEndian.Uint64(bz))
	}
	return sdkmath.ZeroInt()
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
	defer it.Close()
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
	return nil
}

func (k Keeper) ResetAllRelayCredits(ctx sdk.Context) error {
	store := k.storeService.OpenKVStore(ctx)
	prefix := []byte(types.RelayCreditsPrefix)
	it, err := store.Iterator(prefix, storetypes.PrefixEndBytes(prefix))
	if err != nil {
		return err
	}
	defer it.Close()
	for ; it.Valid(); it.Next() {
		_ = store.Delete(it.Key())
	}
	return nil
}

// Params helpers
func (k Keeper) GetParams(ctx sdk.Context) (p types.Params) {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get([]byte("params"))
	if err == nil && len(bz) > 0 {
		_ = k.cdc.Unmarshal(bz, &p)
	}
	if p.MinDifficulty == 0 || p.PowMessageWindow == 0 || p.MintInterval == 0 || p.MintQuantity == 0 || p.BlockHashWindow == 0 ||
		p.MaxUsernameSize == 0 || p.MaxTopicSize == 0 || p.MinUsernameSize == 0 || p.MinTopicSize == 0 || len(p.Tiers) == 0 {
		p = types.DefaultParams()
	}
	return p
}

func (k Keeper) SetParams(ctx sdk.Context, p types.Params) error {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := k.cdc.Marshal(&p)
	if err != nil {
		return err
	}
	return store.Set([]byte("params"), bz)
}

// moduleAddress returns the module account address for core
func (k Keeper) moduleAddress() sdk.AccAddress {
	return authtypes.NewModuleAddress(types.ModuleName)
}

func (k Keeper) mintDenom() string { return types.MintDenom }

// BurnAllFromModule burns all balance of the core module account for the mint denom
func (k Keeper) BurnAllFromModule(ctx sdk.Context) error {
	addr := k.moduleAddress()
	bal := k.bank.GetBalance(ctx, addr, k.mintDenom()).Amount
	if !bal.IsPositive() {
		return nil
	}
	coin := sdk.NewCoin(k.mintDenom(), bal)
	return k.bank.BurnCoins(ctx, types.ModuleName, sdk.NewCoins(coin))
}

// BurnAllFromModuleName transfers the entire balance of the given module account
// for the chain mint denom into the core module account and burns it.
func (k Keeper) BurnAllFromModuleName(ctx sdk.Context, moduleName string) error {
	if strings.TrimSpace(moduleName) == "" {
		return nil
	}
	srcAddr := authtypes.NewModuleAddress(moduleName)
	bal := k.bank.GetBalance(ctx, srcAddr, k.mintDenom()).Amount
	if !bal.IsPositive() {
		return nil
	}
	coin := sdk.NewCoin(k.mintDenom(), bal)
	if err := k.bank.SendCoinsFromModuleToModule(ctx, moduleName, types.ModuleName, sdk.NewCoins(coin)); err != nil {
		return err
	}
	return k.bank.BurnCoins(ctx, types.ModuleName, sdk.NewCoins(coin))
}

// BurnFromModuleAmount burns up to 'amount' umirage from the core module account.
// If the module balance is less than amount, it burns the available balance.
func (k Keeper) BurnFromModuleAmount(ctx sdk.Context, amount uint64) error {
	if amount == 0 {
		return nil
	}
	addr := k.moduleAddress()
	bal := k.bank.GetBalance(ctx, addr, k.mintDenom()).Amount
	amt := sdkmath.NewIntFromUint64(amount)
	if bal.LT(amt) {
		amt = bal
	}
	if !amt.IsPositive() {
		return nil
	}
	coin := sdk.NewCoin(k.mintDenom(), amt)
	return k.bank.BurnCoins(ctx, types.ModuleName, sdk.NewCoins(coin))
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
	coin := sdk.NewCoin(k.mintDenom(), sdkmath.NewIntFromUint64(amount))
	if err := k.bank.MintCoins(ctx, types.ModuleName, sdk.NewCoins(coin)); err != nil {
		return err
	}
	return k.bank.SendCoinsFromModuleToAccount(ctx, types.ModuleName, to, sdk.NewCoins(coin))
}

// MintIfNeeded mints params.MintQuantity umirage every params.MintInterval blocks and distributes proportionally to validator accounts
func (k Keeper) MintIfNeeded(ctx sdk.Context) error {
	current := ctx.BlockHeight()
	params := k.GetParams(ctx)

	// Start minting from block MintInterval, then every MintInterval thereafter
	if current < int64(params.MintInterval) {
		return nil
	}

	// Mint if current block is a multiple of MintInterval
	if current%int64(params.MintInterval) != 0 {
		return nil
	}

	amt := sdkmath.NewIntFromUint64(params.MintQuantity)
	if !amt.IsPositive() {
		return nil
	}

	// Get total stake and validators, excluding jailed and non-bonded
	total_stake := sdkmath.ZeroInt()
	var vals []stakingtypes.Validator
	err := k.staking.IterateValidators(ctx, func(_ int64, valI stakingtypes.ValidatorI) (stop bool) {
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
	})
	if err != nil {
		return err
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
	if split < 0 {
		split = 0
	}
	if split > 1 {
		split = 1
	}
	dynDec, errDec := sdkmath.LegacyNewDecFromStr(fmt.Sprintf("%.18f", split))
	if errDec != nil {
		dynDec = sdkmath.LegacyNewDecWithPrec(5, 1) // 0.5 fallback
	}
	dynamicPool := dynDec.MulInt(amt).TruncateInt()
	if dynamicPool.IsNegative() || dynamicPool.GT(amt) {
		dynamicPool = amt.QuoRaw(2)
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
				alloc := w.weight.MulInt(dynamicPool).QuoTruncate(sumWeights).TruncateInt()
				if alloc.IsPositive() {
					rewards[w.idx].dynamic = alloc
					dynamicAssigned = dynamicAssigned.Add(alloc)
					lastIdxWithWeight = w.idx
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

	// Mint total amount and distribute (baseline + dynamic)
	coins := sdk.NewCoins(sdk.NewCoin(k.mintDenom(), amt))
	if err := k.bank.MintCoins(ctx, types.ModuleName, coins); err != nil {
		return err
	}

	for _, r := range rewards {
		total := r.baseline.Add(r.dynamic)
		if !total.IsPositive() {
			continue
		}
		val_coins := sdk.NewCoins(sdk.NewCoin(k.mintDenom(), total))
		valAddr, err := sdk.ValAddressFromBech32(r.validator.OperatorAddress)
		if err != nil {
			continue
		}
		accAddr := sdk.AccAddress(valAddr)
		if err := k.bank.SendCoinsFromModuleToAccount(ctx, types.ModuleName, accAddr, val_coins); err != nil {
			continue
		}
		ctx.Logger().Info("mint distribution",
			"valoper", r.validator.OperatorAddress,
			"baseline", r.baseline.String(),
			"dynamic", r.dynamic.String(),
			"total", total.String(),
		)
	}

	// Reset relay credits for next interval
	_ = k.ResetAllRelayCredits(ctx)

	ctx.Logger().Info("minted tokens (baseline+dynamic) and distributed to validators",
		"amount", amt.String(),
		"validators", len(rewards),
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
	if bz, err := store.Get(key); err == nil && len(bz) > 0 {
		count = binary.BigEndian.Uint64(bz)
	}
	count++

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
	periodStart := currentHeight - int64(params.PowMessageWindow) + 1
	if periodStart < 1 {
		periodStart = 1
	}

	total := uint64(0)
	for height := periodStart; height <= currentHeight; height++ {
		key := k.powMessageCountKey(height)
		if bz, err := store.Get(key); err == nil && len(bz) > 0 {
			total += binary.BigEndian.Uint64(bz)
		}
	}
	return total
}

// CleanupOldCounters removes counters older than the retention period
func (k Keeper) CleanupOldCounters(ctx sdk.Context, params types.Params) error {
	store := k.storeService.OpenKVStore(ctx)
	currentHeight := ctx.BlockHeight()
	// Keep 2 windows worth of data for safety margin
	cutoffHeight := currentHeight - int64(params.PowMessageWindow)*2

	if cutoffHeight < 1 {
		return nil // Nothing to clean up yet
	}

	// Clean up in batches to avoid expensive operations in a single block
	// Delete up to 100 old counter keys per block
	const maxDeletesPerBlock = 100
	deleted := 0

	// Start from the oldest possible height (genesis = 1) and work up to cutoff
	// We use a stored marker to track cleanup progress across blocks
	markerKey := []byte("pow_cleanup_marker")
	startHeight := int64(1)
	if bz, err := store.Get(markerKey); err == nil && len(bz) == 8 {
		startHeight = int64(binary.BigEndian.Uint64(bz))
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
	start := currentHeight - int64(params.PowMessageWindow) + 1
	if start < 1 {
		start = 1
	}
	for h := start; h <= currentHeight; h++ {
		key := k.powMessageCountKey(h)
		_ = store.Delete(key)
	}
	return nil
}

// BaseDifficultySteps is the default difficulty step (0 = base).
const BaseDifficultySteps uint64 = 0

// BaseDifficultyFactor is the base work factor (1.0x).
const BaseDifficultyFactor uint64 = 1000

// MaxSafeDifficultyFactor caps the factor to 2^53-1 so JSON/JS Number is lossless.
const MaxSafeDifficultyFactor uint64 = (1 << 53) - 1

// MaxSafeDifficultySteps caps the step count to 2^53-1 so JSON/JS Number is lossless.
const MaxSafeDifficultySteps uint64 = (1 << 53) - 1

// GetCurrentDifficulty returns the current dynamic difficulty step.
// 0 = base difficulty. Higher values = harder via (1 + pow_factor)^difficulty.
func (k Keeper) GetCurrentDifficulty(ctx sdk.Context) uint64 {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.currentDifficultyKey())
	if err != nil || len(bz) == 0 {
		return BaseDifficultySteps
	}
	v := binary.BigEndian.Uint64(bz)
	if v > MaxSafeDifficultySteps {
		return MaxSafeDifficultySteps
	}
	return v
}

// HasCurrentDifficulty returns true if the current_difficulty key exists in store
func (k Keeper) HasCurrentDifficulty(ctx sdk.Context) bool {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.currentDifficultyKey())
	return err == nil && len(bz) > 0
}

func (k Keeper) previousDifficultyKey() []byte { return []byte("prev_difficulty") }
func (k Keeper) lastChangeHeightKey() []byte   { return []byte("last_diff_change_height") }

// SetCurrentDifficulty sets the current dynamic difficulty and records previous value and change height
func (k Keeper) SetCurrentDifficulty(ctx sdk.Context, difficulty uint64) error {
	store := k.storeService.OpenKVStore(ctx)
	// read old
	old := k.GetCurrentDifficulty(ctx)
	// write new current
	bz := make([]byte, 8)
	binary.BigEndian.PutUint64(bz, difficulty)
	if err := store.Set(k.currentDifficultyKey(), bz); err != nil {
		return err
	}
	// store previous and height
	pbz := make([]byte, 8)
	binary.BigEndian.PutUint64(pbz, old)
	_ = store.Set(k.previousDifficultyKey(), pbz)
	hbz := make([]byte, 8)
	binary.BigEndian.PutUint64(hbz, uint64(ctx.BlockHeight()))
	_ = store.Set(k.lastChangeHeightKey(), hbz)
	return nil
}

// GetPreviousDifficulty returns previous difficulty or current if unset
func (k Keeper) GetPreviousDifficulty(ctx sdk.Context) uint64 {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.previousDifficultyKey())
	if err != nil || len(bz) == 0 {
		return k.GetCurrentDifficulty(ctx)
	}
	return binary.BigEndian.Uint64(bz)
}

// GetLastDifficultyChangeHeight returns the height of the last difficulty change
func (k Keeper) GetLastDifficultyChangeHeight(ctx sdk.Context) int64 {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.lastChangeHeightKey())
	if err != nil || len(bz) == 0 {
		return 0
	}
	return int64(binary.BigEndian.Uint64(bz))
}

// GetConsecutiveLowUsage returns the number of consecutive blocks with low usage
func (k Keeper) GetConsecutiveLowUsage(ctx sdk.Context) uint64 {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get(k.consecutiveLowUsageKey())
	if err != nil || len(bz) == 0 {
		return 0
	}
	return binary.BigEndian.Uint64(bz)
}

// SetConsecutiveLowUsage sets the number of consecutive blocks with low usage
func (k Keeper) SetConsecutiveLowUsage(ctx sdk.Context, count uint64) error {
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
	store := k.storeService.OpenKVStore(ctx)
	prefix := []byte(types.SubscriptionsPrefix)
	// End key is for all subscriptions with expiry <= timestamp
	endKey := []byte(fmt.Sprintf("%s%016x:", types.SubscriptionsPrefix, timestamp+1))

	var expired []ExpiredSubscription

	iterator, err := store.Iterator(prefix, endKey)
	if err != nil {
		return nil, err
	}
	defer iterator.Close()

	for ; iterator.Valid(); iterator.Next() {
		key := string(iterator.Key())
		// Parse key: subs/{expiry_hex}:{address}
		trimmed := strings.TrimPrefix(key, types.SubscriptionsPrefix)
		parts := strings.SplitN(trimmed, ":", 2)
		if len(parts) != 2 {
			continue
		}
		var expiry int64
		_, err := fmt.Sscanf(parts[0], "%x", &expiry)
		if err != nil {
			continue
		}
		addr := parts[1]
		level := 0
		if v := iterator.Value(); len(v) >= 4 {
			level = int(binary.BigEndian.Uint32(v))
		}
		expired = append(expired, ExpiredSubscription{
			Address: addr,
			Level:   level,
			Expiry:  expiry,
		})
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

	// Send to module account first
	if err := k.bank.SendCoinsFromAccountToModule(ctx, accAddr, types.ModuleName, coins); err != nil {
		return err
	}
	// Then burn from module
	return k.bank.BurnCoins(ctx, types.ModuleName, coins)
}

// DeleteUserState removes all on-chain state for a user:
// profile core, all profile lists, username mapping, subscription index,
// and sweeps spendable balances to the community pool.
// Returns the username that was released (for logging) and the swept amounts.
func (k Keeper) DeleteUserState(ctx sdk.Context, addr string) (usernameReleased string, sweptAmounts sdk.Coins, err error) {
	store := k.storeService.OpenKVStore(ctx)
	accAddr, err := sdk.AccAddressFromBech32(addr)
	if err != nil {
		return "", nil, fmt.Errorf("invalid address: %w", err)
	}

	// Load profile to get username and subscription expiry before deletion
	var username string
	var subscriptionExpiry int64
	if bz, found, _ := k.GetProfileCore(ctx, addr); found {
		var core types.ProfileCore
		if err := json.Unmarshal(bz, &core); err == nil {
			username = core.Username
			subscriptionExpiry = core.SubscriptionExpiry
		}
	}

	// Delete profile core KV
	if err := store.Delete(k.profileKey(addr)); err != nil {
		return "", nil, err
	}

	// Delete all per-entry list keys (prefix-range delete + count + seq for each list)
	if err := k.DeleteAllEnabledAgents(ctx, addr); err != nil {
		return "", nil, err
	}
	if err := k.DeleteAllFollowedUsers(ctx, addr); err != nil {
		return "", nil, err
	}
	if err := k.DeleteAllFollowedTopics(ctx, addr); err != nil {
		return "", nil, err
	}
	if err := k.DeleteAllBlockedUsers(ctx, addr); err != nil {
		return "", nil, err
	}
	if err := k.DeleteAllBlockedPosts(ctx, addr); err != nil {
		return "", nil, err
	}
	if err := k.DeleteAllBlockedTopics(ctx, addr); err != nil {
		return "", nil, err
	}
	// Also delete legacy blob keys in case they exist (pre-migration data)
	if err := store.Delete(k.profileEnabledAgentsKey(addr)); err != nil {
		return "", nil, err
	}
	if err := store.Delete(k.profileFollowedUsersKey(addr)); err != nil {
		return "", nil, err
	}
	if err := store.Delete(k.profileFollowedTopicsKey(addr)); err != nil {
		return "", nil, err
	}
	if err := store.Delete(k.profileBlockedUsersKey(addr)); err != nil {
		return "", nil, err
	}
	if err := store.Delete(k.profileBlockedPostsKey(addr)); err != nil {
		return "", nil, err
	}
	if err := store.Delete(k.profileBlockedTopicsKey(addr)); err != nil {
		return "", nil, err
	}

	// Release username mapping
	if username != "" {
		if err := k.ReleaseUsername(ctx, username, addr); err != nil {
			return "", nil, err
		}
		usernameReleased = username
	}

	// Remove subscription index entry if present
	if subscriptionExpiry > 0 {
		_ = k.RemoveSubscription(ctx, addr, subscriptionExpiry)
	}

	// Sweep all spendable balances to community pool
	spendable := k.bank.SpendableCoins(ctx, accAddr)
	if spendable.IsAllPositive() {
		if err := k.distribution.FundCommunityPool(ctx, spendable, accAddr); err != nil {
			return usernameReleased, nil, fmt.Errorf("failed to sweep funds to community pool: %w", err)
		}
		sweptAmounts = spendable
	}

	return usernameReleased, sweptAmounts, nil
}

// ============================================
// Bridge Attestation State Management
// ============================================

// GetBridgeAttestation retrieves a bridge attestation by source_chain and burn_id.
// Returns an error if multiple attestations exist for the same burn.
func (k Keeper) GetBridgeAttestation(ctx sdk.Context, sourceChain, burnID string) (*types.BridgeAttestation, bool, error) {
	store := k.storeService.OpenKVStore(ctx)
	prefix := []byte(fmt.Sprintf("%s%s/%s/", types.BridgeAttestationsPrefix, sourceChain, burnID))
	it, err := store.Iterator(prefix, storetypes.PrefixEndBytes(prefix))
	if err != nil {
		return nil, false, err
	}
	defer it.Close()

	var attestation *types.BridgeAttestation
	for ; it.Valid(); it.Next() {
		if attestation != nil {
			return nil, false, fmt.Errorf("multiple attestations found for %s/%s", sourceChain, burnID)
		}
		parsed, err := types.UnmarshalBridgeAttestation(it.Value())
		if err != nil {
			return nil, false, err
		}
		attestation = parsed
	}
	if attestation == nil {
		return nil, false, nil
	}
	return attestation, true, nil
}

// GetBridgeAttestationWithParams retrieves a bridge attestation with parameter-scoped key.
func (k Keeper) GetBridgeAttestationWithParams(ctx sdk.Context, sourceChain, burnID, recipient string, amount uint64) (*types.BridgeAttestation, bool, error) {
	if strings.TrimSpace(recipient) == "" {
		return nil, false, fmt.Errorf("recipient cannot be empty")
	}
	store := k.storeService.OpenKVStore(ctx)
	key := types.BridgeAttestationKeyWithParams(sourceChain, burnID, recipient, amount)
	bz, err := store.Get(key)
	if err != nil {
		return nil, false, err
	}
	if len(bz) == 0 {
		return nil, false, nil
	}
	attestation, err := types.UnmarshalBridgeAttestation(bz)
	if err != nil {
		return nil, false, err
	}
	return attestation, true, nil
}

// SetBridgeAttestation stores a bridge attestation in state using parameterized key.
func (k Keeper) SetBridgeAttestation(ctx sdk.Context, attestation *types.BridgeAttestation) error {
	if len(attestation.Attestors) > 0 {
		return fmt.Errorf("bridge attestors must be stored separately")
	}
	store := k.storeService.OpenKVStore(ctx)
	key := types.BridgeAttestationKeyWithParams(attestation.SourceChain, attestation.BurnID, attestation.MirageRecipient, attestation.Amount)
	stored := *attestation
	stored.Attestors = nil
	bz, err := stored.Marshal()
	if err != nil {
		return err
	}
	return store.Set(key, bz)
}

// GetOrCreateBridgeAttestation retrieves or creates a new bridge attestation.
// Uses parameterized keys so each (chain, burnID, recipient, amount) tuple has its own record.
func (k Keeper) GetOrCreateBridgeAttestation(ctx sdk.Context, sourceChain, burnID, mirageRecipient string, amount uint64) (*types.BridgeAttestation, error) {
	attestation, found, err := k.GetBridgeAttestationWithParams(ctx, sourceChain, burnID, mirageRecipient, amount)
	if err != nil {
		return nil, err
	}
	if found {
		return attestation, nil
	}
	// Create new attestation
	attestation = types.NewBridgeAttestation(sourceChain, burnID, mirageRecipient, amount, ctx.BlockHeight())
	if err := k.SetBridgeAttestation(ctx, attestation); err != nil {
		return nil, err
	}
	// Increment pending count
	if err := k.IncrementBridgePendingCount(ctx); err != nil {
		return nil, err
	}
	return attestation, nil
}

// SetBridgeAttestor stores a validator's attestation for an inbound burn.
// Scoped by burn parameters (recipient, amount) to prevent cross-attestation poisoning.
func (k Keeper) SetBridgeAttestor(ctx sdk.Context, sourceChain, burnID, recipient string, amount uint64, valoper string, power int64) error {
	if power <= 0 {
		return fmt.Errorf("attestor power must be positive")
	}
	if strings.TrimSpace(valoper) == "" {
		return fmt.Errorf("attestor valoper cannot be empty")
	}
	store := k.storeService.OpenKVStore(ctx)
	key := types.BridgeAttestorKeyWithParams(sourceChain, burnID, recipient, amount, valoper)
	bz := make([]byte, 8)
	binary.BigEndian.PutUint64(bz, uint64(power))
	return store.Set(key, bz)
}

// HasBridgeAttestor returns true if the validator already attested to the burn with matching params.
func (k Keeper) HasBridgeAttestor(ctx sdk.Context, sourceChain, burnID, recipient string, amount uint64, valoper string) (bool, error) {
	store := k.storeService.OpenKVStore(ctx)
	key := types.BridgeAttestorKeyWithParams(sourceChain, burnID, recipient, amount, valoper)
	bz, err := store.Get(key)
	if err != nil {
		return false, err
	}
	return len(bz) > 0, nil
}

// IterateBridgeAttestors iterates over attestors for a specific burn + params.
func (k Keeper) IterateBridgeAttestors(ctx sdk.Context, sourceChain, burnID, recipient string, amount uint64, fn func(valoper string, power int64) bool) error {
	store := k.storeService.OpenKVStore(ctx)
	if strings.TrimSpace(recipient) == "" {
		return fmt.Errorf("recipient cannot be empty")
	}
	paramsHash := types.BurnParamsHash(recipient, amount)
	prefix := []byte(fmt.Sprintf("%s%s/%s/%s/", types.BridgeAttestorsPrefix, sourceChain, burnID, paramsHash))
	it, err := store.Iterator(prefix, storetypes.PrefixEndBytes(prefix))
	if err != nil {
		return err
	}
	defer it.Close()
	for ; it.Valid(); it.Next() {
		key := string(it.Key())
		valoper := strings.TrimPrefix(key, string(prefix))
		if valoper == "" {
			continue
		}
		value := it.Value()
		if len(value) != 8 {
			return fmt.Errorf("invalid attestor power for %s/%s: length=%d", sourceChain, burnID, len(value))
		}
		power := int64(binary.BigEndian.Uint64(value))
		if stop := fn(valoper, power); stop {
			break
		}
	}
	return nil
}

// GetBridgeAttestorList returns a sorted list of attestors for a burn.
func (k Keeper) GetBridgeAttestorList(ctx sdk.Context, sourceChain, burnID, recipient string, amount uint64) ([]string, error) {
	var attestors []string
	if err := k.IterateBridgeAttestors(ctx, sourceChain, burnID, recipient, amount, func(valoper string, _ int64) bool {
		attestors = append(attestors, valoper)
		return false
	}); err != nil {
		return nil, err
	}
	sort.Strings(attestors)
	return attestors, nil
}

type bridgeAttestationParams struct {
	recipient string
	amount    uint64
}

// MigrateBridgeAttestationParams moves legacy bridge attestation and attestor keys to param-scoped keys.
func (k Keeper) MigrateBridgeAttestationParams(ctx sdk.Context) (int, int, error) {
	store := k.storeService.OpenKVStore(ctx)
	prefix := []byte(types.BridgeAttestationsPrefix)
	it, err := store.Iterator(prefix, storetypes.PrefixEndBytes(prefix))
	if err != nil {
		return 0, 0, err
	}
	defer it.Close()

	attestationParams := make(map[string]bridgeAttestationParams)
	var attestationsToDelete [][]byte
	attestationsMoved := 0

	for ; it.Valid(); it.Next() {
		key := string(it.Key())
		suffix := strings.TrimPrefix(key, types.BridgeAttestationsPrefix)
		parts := strings.Split(suffix, "/")
		if len(parts) != 2 && len(parts) != 3 {
			return 0, 0, fmt.Errorf("invalid bridge attestation key: %s", key)
		}
		attestation, err := types.UnmarshalBridgeAttestation(it.Value())
		if err != nil {
			return 0, 0, err
		}
		if strings.TrimSpace(attestation.MirageRecipient) == "" {
			return 0, 0, fmt.Errorf("attestation missing recipient for %s", key)
		}

		attKey := parts[0] + "/" + parts[1]
		if existing, ok := attestationParams[attKey]; ok {
			if existing.recipient != attestation.MirageRecipient || existing.amount != attestation.Amount {
				return 0, 0, fmt.Errorf("conflicting attestation params for %s", attKey)
			}
		} else {
			attestationParams[attKey] = bridgeAttestationParams{
				recipient: attestation.MirageRecipient,
				amount:    attestation.Amount,
			}
		}

		if len(parts) == 3 {
			expected := types.BurnParamsHash(attestation.MirageRecipient, attestation.Amount)
			if parts[2] != expected {
				return 0, 0, fmt.Errorf("attestation params hash mismatch for %s", attKey)
			}
		}

		if len(parts) == 2 {
			newKey := types.BridgeAttestationKeyWithParams(parts[0], parts[1], attestation.MirageRecipient, attestation.Amount)
			existing, err := store.Get(newKey)
			if err != nil {
				return 0, 0, err
			}
			if len(existing) == 0 {
				if err := store.Set(newKey, it.Value()); err != nil {
					return 0, 0, err
				}
			} else if !bytes.Equal(existing, it.Value()) {
				return 0, 0, fmt.Errorf("conflicting attestation for %s", key)
			}
			attestationsToDelete = append(attestationsToDelete, append([]byte{}, it.Key()...))
			attestationsMoved++
		}
	}

	for _, k := range attestationsToDelete {
		if err := store.Delete(k); err != nil {
			return 0, 0, err
		}
	}

	attPrefix := []byte(types.BridgeAttestorsPrefix)
	attIt, err := store.Iterator(attPrefix, storetypes.PrefixEndBytes(attPrefix))
	if err != nil {
		return 0, 0, err
	}
	defer attIt.Close()

	var attestorsToDelete [][]byte
	attestorsMoved := 0

	for ; attIt.Valid(); attIt.Next() {
		key := string(attIt.Key())
		suffix := strings.TrimPrefix(key, types.BridgeAttestorsPrefix)
		parts := strings.Split(suffix, "/")
		if len(parts) == 4 {
			continue
		}
		if len(parts) != 3 {
			return 0, 0, fmt.Errorf("invalid bridge attestor key: %s", key)
		}

		sourceChain := parts[0]
		burnID := parts[1]
		valoper := parts[2]
		info, ok := attestationParams[sourceChain+"/"+burnID]
		if !ok {
			return 0, 0, fmt.Errorf("missing attestation for %s/%s", sourceChain, burnID)
		}
		newKey := types.BridgeAttestorKeyWithParams(sourceChain, burnID, info.recipient, info.amount, valoper)
		existing, err := store.Get(newKey)
		if err != nil {
			return 0, 0, err
		}
		if len(existing) == 0 {
			if err := store.Set(newKey, attIt.Value()); err != nil {
				return 0, 0, err
			}
		} else if !bytes.Equal(existing, attIt.Value()) {
			return 0, 0, fmt.Errorf("conflicting attestor entry for %s", key)
		}
		attestorsToDelete = append(attestorsToDelete, append([]byte{}, attIt.Key()...))
		attestorsMoved++
	}

	for _, k := range attestorsToDelete {
		if err := store.Delete(k); err != nil {
			return 0, 0, err
		}
	}

	ctx.Logger().Debug("bridge attestation key migration complete",
		"attestations_moved", attestationsMoved,
		"attestors_moved", attestorsMoved)

	return attestationsMoved, attestorsMoved, nil
}

func (k Keeper) iterateBridgeAttestationsLegacy(ctx sdk.Context, fn func(sourceChain, burnID string, attestation *types.BridgeAttestation) bool) error {
	store := k.storeService.OpenKVStore(ctx)
	prefix := []byte(types.BridgeAttestationsPrefix)
	it, err := store.Iterator(prefix, storetypes.PrefixEndBytes(prefix))
	if err != nil {
		return err
	}
	defer it.Close()
	for ; it.Valid(); it.Next() {
		key := string(it.Key())
		suffix := strings.TrimPrefix(key, types.BridgeAttestationsPrefix)
		parts := strings.Split(suffix, "/")
		if len(parts) != 2 {
			continue
		}
		attestation, err := types.UnmarshalBridgeAttestation(it.Value())
		if err != nil {
			return err
		}
		if stop := fn(parts[0], parts[1], attestation); stop {
			break
		}
	}
	return nil
}

// MigrateBridgeAttestors moves stored attestor maps to per-attestor keys.
func (k Keeper) MigrateBridgeAttestors(ctx sdk.Context) error {
	var migrateErr error
	err := k.iterateBridgeAttestationsLegacy(ctx, func(sourceChain, burnID string, attestation *types.BridgeAttestation) bool {
		if len(attestation.Attestors) == 0 {
			return false
		}

		var sumPower int64
		for _, power := range attestation.Attestors {
			if power <= 0 {
				continue
			}
			sumPower += power
		}
		if sumPower != attestation.AttestedPower {
			migrateErr = fmt.Errorf("attested power mismatch for %s/%s: stored=%d sum=%d", sourceChain, burnID, attestation.AttestedPower, sumPower)
			return true
		}

		for valoperAddr, power := range attestation.Attestors {
			if power <= 0 {
				continue
			}
			if err := k.SetBridgeAttestor(ctx, sourceChain, burnID, attestation.MirageRecipient, attestation.Amount, valoperAddr, power); err != nil {
				migrateErr = err
				return true
			}
		}

		attestation.Attestors = nil
		if err := k.SetBridgeAttestation(ctx, attestation); err != nil {
			migrateErr = err
			return true
		}

		return false
	})
	if err != nil {
		return err
	}
	return migrateErr
}

// ============================================
// Bridge Burn State Management
// ============================================

// GetBridgeBurnRecord retrieves a bridge burn record from state
func (k Keeper) GetBridgeBurnRecord(ctx sdk.Context, destChain, burnID string) (*types.BridgeBurnRecord, bool, error) {
	store := k.storeService.OpenKVStore(ctx)
	key := types.BridgeBurnKey(destChain, burnID)
	bz, err := store.Get(key)
	if err != nil {
		return nil, false, err
	}
	if len(bz) == 0 {
		return nil, false, nil
	}
	record, err := types.UnmarshalBridgeBurnRecord(bz)
	if err != nil {
		return nil, false, err
	}
	return record, true, nil
}

// SetBridgeBurnRecord stores a bridge burn record in state
func (k Keeper) SetBridgeBurnRecord(ctx sdk.Context, record *types.BridgeBurnRecord) error {
	store := k.storeService.OpenKVStore(ctx)
	key := types.BridgeBurnKey(record.DestinationChain, record.BurnID)
	bz, err := record.Marshal()
	if err != nil {
		return err
	}
	return store.Set(key, bz)
}

// ============================================
// Bridge Mint Confirmation State Management
// ============================================

// GetBridgeMintedRecord retrieves a bridge mint record from state
func (k Keeper) GetBridgeMintedRecord(ctx sdk.Context, destChain, burnID string) (*types.BridgeMintedRecord, bool, error) {
	store := k.storeService.OpenKVStore(ctx)
	key := types.BridgeMintedKey(destChain, burnID)
	bz, err := store.Get(key)
	if err != nil {
		return nil, false, err
	}
	if len(bz) == 0 {
		return nil, false, nil
	}
	record, err := types.UnmarshalBridgeMintedRecord(bz)
	if err != nil {
		return nil, false, err
	}
	return record, true, nil
}

// SetBridgeMintedRecord stores a bridge mint record in state
func (k Keeper) SetBridgeMintedRecord(ctx sdk.Context, record *types.BridgeMintedRecord) error {
	store := k.storeService.OpenKVStore(ctx)
	key := types.BridgeMintedKey(record.DestinationChain, record.BurnID)
	bz, err := record.Marshal()
	if err != nil {
		return err
	}
	return store.Set(key, bz)
}

// ============================================
// Bridge Mint Attestation State Management (Outbound)
// ============================================

// GetBridgeMintAttestation retrieves a bridge mint attestation from state
func (k Keeper) GetBridgeMintAttestation(ctx sdk.Context, destChain, burnID string) (*types.BridgeMintAttestation, bool, error) {
	store := k.storeService.OpenKVStore(ctx)
	key := types.BridgeMintAttestationKey(destChain, burnID)
	bz, err := store.Get(key)
	if err != nil {
		return nil, false, err
	}
	if len(bz) == 0 {
		return nil, false, nil
	}
	attestation, err := types.UnmarshalBridgeMintAttestation(bz)
	if err != nil {
		return nil, false, err
	}
	return attestation, true, nil
}

// SetBridgeMintAttestation stores a bridge mint attestation in state
func (k Keeper) SetBridgeMintAttestation(ctx sdk.Context, attestation *types.BridgeMintAttestation) error {
	if len(attestation.Attestors) > 0 {
		return fmt.Errorf("bridge mint attestors must be stored separately")
	}
	store := k.storeService.OpenKVStore(ctx)
	key := types.BridgeMintAttestationKey(attestation.DestinationChain, attestation.BurnID)
	stored := *attestation
	stored.Attestors = nil
	bz, err := stored.Marshal()
	if err != nil {
		return err
	}
	return store.Set(key, bz)
}

// SetBridgeMintAttestor stores a validator's attestation for an outbound mint.
func (k Keeper) SetBridgeMintAttestor(ctx sdk.Context, destChain, burnID, valoper string, power int64) error {
	if power <= 0 {
		return fmt.Errorf("attestor power must be positive")
	}
	if strings.TrimSpace(valoper) == "" {
		return fmt.Errorf("attestor valoper cannot be empty")
	}
	store := k.storeService.OpenKVStore(ctx)
	key := types.BridgeMintAttestorKey(destChain, burnID, valoper)
	bz := make([]byte, 8)
	binary.BigEndian.PutUint64(bz, uint64(power))
	return store.Set(key, bz)
}

// HasBridgeMintAttestor returns true if the validator already attested to the mint.
func (k Keeper) HasBridgeMintAttestor(ctx sdk.Context, destChain, burnID, valoper string) (bool, error) {
	store := k.storeService.OpenKVStore(ctx)
	key := types.BridgeMintAttestorKey(destChain, burnID, valoper)
	bz, err := store.Get(key)
	if err != nil {
		return false, err
	}
	return len(bz) > 0, nil
}

// IterateBridgeMintAttestors iterates over attestors for a specific mint.
func (k Keeper) IterateBridgeMintAttestors(ctx sdk.Context, destChain, burnID string, fn func(valoper string, power int64) bool) error {
	store := k.storeService.OpenKVStore(ctx)
	prefix := []byte(fmt.Sprintf("%s%s/%s/", types.BridgeMintAttestorsPrefix, destChain, burnID))
	it, err := store.Iterator(prefix, storetypes.PrefixEndBytes(prefix))
	if err != nil {
		return err
	}
	defer it.Close()
	for ; it.Valid(); it.Next() {
		key := string(it.Key())
		valoper := strings.TrimPrefix(key, string(prefix))
		if valoper == "" {
			continue
		}
		value := it.Value()
		if len(value) != 8 {
			return fmt.Errorf("invalid attestor power for %s/%s: length=%d", destChain, burnID, len(value))
		}
		power := int64(binary.BigEndian.Uint64(value))
		if stop := fn(valoper, power); stop {
			break
		}
	}
	return nil
}

// GetBridgeMintAttestorList returns a sorted list of attestors for a mint.
func (k Keeper) GetBridgeMintAttestorList(ctx sdk.Context, destChain, burnID string) ([]string, error) {
	var attestors []string
	if err := k.IterateBridgeMintAttestors(ctx, destChain, burnID, func(valoper string, _ int64) bool {
		attestors = append(attestors, valoper)
		return false
	}); err != nil {
		return nil, err
	}
	sort.Strings(attestors)
	return attestors, nil
}

// IterateBridgeMintAttestations iterates over all outbound mint attestations.
func (k Keeper) IterateBridgeMintAttestations(ctx sdk.Context, fn func(destChain, burnID string, attestation *types.BridgeMintAttestation) bool) error {
	store := k.storeService.OpenKVStore(ctx)
	prefix := []byte(types.BridgeMintAttestationsPrefix)
	it, err := store.Iterator(prefix, storetypes.PrefixEndBytes(prefix))
	if err != nil {
		return err
	}
	defer it.Close()
	for ; it.Valid(); it.Next() {
		key := string(it.Key())
		suffix := strings.TrimPrefix(key, types.BridgeMintAttestationsPrefix)
		parts := strings.SplitN(suffix, "/", 2)
		if len(parts) != 2 {
			continue
		}
		attestation, err := types.UnmarshalBridgeMintAttestation(it.Value())
		if err != nil {
			return err
		}
		if stop := fn(parts[0], parts[1], attestation); stop {
			break
		}
	}
	return nil
}

// MigrateBridgeMintAttestors moves stored attestor maps to per-attestor keys.
func (k Keeper) MigrateBridgeMintAttestors(ctx sdk.Context) error {
	var migrateErr error
	err := k.IterateBridgeMintAttestations(ctx, func(destChain, burnID string, attestation *types.BridgeMintAttestation) bool {
		if len(attestation.Attestors) == 0 {
			return false
		}

		var (
			bestValoper string
			bestPower   int64
			sumPower    int64
		)
		for valoperAddr, power := range attestation.Attestors {
			if power <= 0 {
				continue
			}
			sumPower += power
			if power > bestPower {
				bestPower = power
				bestValoper = valoperAddr
			}
		}
		if sumPower != attestation.AttestedPower {
			migrateErr = fmt.Errorf("attested power mismatch for %s/%s: stored=%d sum=%d", destChain, burnID, attestation.AttestedPower, sumPower)
			return true
		}

		for valoperAddr, power := range attestation.Attestors {
			if power <= 0 {
				continue
			}
			if err := k.SetBridgeMintAttestor(ctx, destChain, burnID, valoperAddr, power); err != nil {
				migrateErr = err
				return true
			}
		}

		if attestation.Confirmed && strings.TrimSpace(attestation.ConfirmedBy) == "" {
			if bestValoper == "" {
				migrateErr = fmt.Errorf("confirmed mint attestation missing attestors for %s/%s", destChain, burnID)
				return true
			}
			valoper, err := sdk.ValAddressFromBech32(bestValoper)
			if err != nil {
				migrateErr = fmt.Errorf("invalid confirmed_by valoper: %w", err)
				return true
			}
			attestation.ConfirmedBy = sdk.AccAddress(valoper).String()
		} else if strings.TrimSpace(attestation.ConfirmedBy) != "" {
			confirmedFound := false
			for valoperAddr := range attestation.Attestors {
				valoper, err := sdk.ValAddressFromBech32(valoperAddr)
				if err != nil {
					migrateErr = fmt.Errorf("invalid confirmed_by valoper: %w", err)
					return true
				}
				if sdk.AccAddress(valoper).String() == attestation.ConfirmedBy {
					confirmedFound = true
					break
				}
			}
			if !confirmedFound {
				migrateErr = fmt.Errorf("confirmed_by not found in attestors for %s/%s", destChain, burnID)
				return true
			}
		}

		attestation.Attestors = nil
		if err := k.SetBridgeMintAttestation(ctx, attestation); err != nil {
			migrateErr = err
			return true
		}
		return false
	})
	if err != nil {
		return err
	}
	return migrateErr
}

// GetOrCreateBridgeMintAttestation retrieves or creates a new bridge mint attestation
func (k Keeper) GetOrCreateBridgeMintAttestation(ctx sdk.Context, burnID, destChain, destTx string) (*types.BridgeMintAttestation, error) {
	attestation, found, err := k.GetBridgeMintAttestation(ctx, destChain, burnID)
	if err != nil {
		return nil, err
	}
	if found {
		return attestation, nil
	}
	// Create new attestation
	attestation = types.NewBridgeMintAttestation(burnID, destChain, destTx, ctx.BlockHeight())
	if err := k.SetBridgeMintAttestation(ctx, attestation); err != nil {
		return nil, err
	}
	return attestation, nil
}

// GetNextBridgeSequence increments and returns the next sequence number for a destination chain
func (k Keeper) GetNextBridgeSequence(ctx sdk.Context, destChain string) (uint64, error) {
	store := k.storeService.OpenKVStore(ctx)
	key := []byte(types.BridgeSequencePrefix + destChain)

	bz, err := store.Get(key)
	if err != nil {
		return 0, err
	}

	var seq uint64 = 1 // Start at 1
	if len(bz) > 0 {
		seq = binary.BigEndian.Uint64(bz) + 1
	}

	// Store the new sequence
	bzNew := make([]byte, 8)
	binary.BigEndian.PutUint64(bzNew, seq)
	if err := store.Set(key, bzNew); err != nil {
		return 0, err
	}

	return seq, nil
}

// GetCurrentBridgeSequence returns the current sequence number for a destination chain (without incrementing)
func (k Keeper) GetCurrentBridgeSequence(ctx sdk.Context, destChain string) (uint64, error) {
	store := k.storeService.OpenKVStore(ctx)
	key := []byte(types.BridgeSequencePrefix + destChain)

	bz, err := store.Get(key)
	if err != nil {
		return 0, err
	}

	if len(bz) == 0 {
		return 0, nil // No burns yet for this chain
	}

	return binary.BigEndian.Uint64(bz), nil
}

// SetBridgeSequence sets the sequence number for a destination chain.
// Used by upgrade handlers to advance sequence past stale external chain state.
func (k Keeper) SetBridgeSequence(ctx sdk.Context, destChain string, seq uint64) error {
	store := k.storeService.OpenKVStore(ctx)
	key := []byte(types.BridgeSequencePrefix + destChain)
	bz := make([]byte, 8)
	binary.BigEndian.PutUint64(bz, seq)
	return store.Set(key, bz)
}

// GetBridgePendingCount returns the count of pending (unminted) attestations
func (k Keeper) GetBridgePendingCount(ctx sdk.Context) (uint64, error) {
	store := k.storeService.OpenKVStore(ctx)
	bz, err := store.Get([]byte(types.BridgePendingCountKey))
	if err != nil {
		return 0, err
	}
	if len(bz) == 0 {
		return 0, nil
	}
	return binary.BigEndian.Uint64(bz), nil
}

// SetBridgePendingCount sets the pending attestation count
func (k Keeper) SetBridgePendingCount(ctx sdk.Context, count uint64) error {
	store := k.storeService.OpenKVStore(ctx)
	bz := make([]byte, 8)
	binary.BigEndian.PutUint64(bz, count)
	return store.Set([]byte(types.BridgePendingCountKey), bz)
}

// IncrementBridgePendingCount increments the pending attestation count
func (k Keeper) IncrementBridgePendingCount(ctx sdk.Context) error {
	count, err := k.GetBridgePendingCount(ctx)
	if err != nil {
		return err
	}
	return k.SetBridgePendingCount(ctx, count+1)
}

// DecrementBridgePendingCount decrements the pending attestation count
func (k Keeper) DecrementBridgePendingCount(ctx sdk.Context) error {
	count, err := k.GetBridgePendingCount(ctx)
	if err != nil {
		return err
	}
	if count > 0 {
		return k.SetBridgePendingCount(ctx, count-1)
	}
	return nil
}

// GetTotalBondedValidatorPower returns the total voting power of all bonded validators
func (k Keeper) GetTotalBondedValidatorPower(ctx sdk.Context) (int64, error) {
	var totalPower int64
	err := k.staking.IterateBondedValidatorsByPower(ctx, func(_ int64, validator stakingtypes.ValidatorI) bool {
		totalPower += validator.GetConsensusPower(k.staking.PowerReduction(ctx))
		return false
	})
	return totalPower, err
}

// GetValidatorPower returns the voting power of a specific validator
func (k Keeper) GetValidatorPower(ctx sdk.Context, valoper string) (int64, error) {
	valAddr, err := sdk.ValAddressFromBech32(valoper)
	if err != nil {
		return 0, fmt.Errorf("invalid validator address: %w", err)
	}
	validator, err := k.staking.GetValidator(ctx, valAddr)
	if err != nil {
		return 0, fmt.Errorf("validator not found: %w", err)
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
		return false, nil // Not found = not bonded
	}
	return validator.IsBonded(), nil
}

// HasEnvelopeNonce checks if a nonce has been seen for the given pubkey hash.
func (k Keeper) HasEnvelopeNonce(ctx sdk.Context, pubkeyHash []byte, nonce uint64) bool {
	store := k.storeService.OpenKVStore(ctx)
	key := []byte(fmt.Sprintf("%s%x/%d", types.EnvelopeNoncePrefix, pubkeyHash, nonce))
	val, err := store.Get(key)
	if err != nil {
		return false
	}
	return val != nil
}

// SetEnvelopeNonce records a nonce for the given pubkey hash with an expiry time.
func (k Keeper) SetEnvelopeNonce(ctx sdk.Context, pubkeyHash []byte, nonce uint64, expiryUnix int64) error {
	store := k.storeService.OpenKVStore(ctx)
	key := []byte(fmt.Sprintf("%s%x/%d", types.EnvelopeNoncePrefix, pubkeyHash, nonce))
	if err := store.Set(key, []byte{}); err != nil {
		return err
	}
	// Also set expiry index for pruning
	expiryKey := []byte(fmt.Sprintf("%s%020d/%x/%d", types.EnvelopeNonceExpiryPrefix, expiryUnix, pubkeyHash, nonce))
	return store.Set(expiryKey, []byte{})
}

// PruneExpiredNonces removes all nonce entries that have expired.
func (k Keeper) PruneExpiredNonces(ctx sdk.Context, nowUnix int64) (int, error) {
	store := k.storeService.OpenKVStore(ctx)
	prefix := []byte(types.EnvelopeNonceExpiryPrefix)
	// End key is exclusive; use nowUnix+1 so we include entries expiring exactly at nowUnix
	cutoff := []byte(fmt.Sprintf("%s%020d/", types.EnvelopeNonceExpiryPrefix, nowUnix+1))

	iter, err := store.Iterator(prefix, cutoff)
	if err != nil {
		return 0, err
	}
	defer iter.Close()

	var toDelete [][]byte
	for ; iter.Valid(); iter.Next() {
		toDelete = append(toDelete, append([]byte{}, iter.Key()...))
	}

	pruned := 0
	for _, expiryKey := range toDelete {
		// Parse the nonce key from the expiry key
		// Format: envelope_nonce_expiry/{expiry_unix}/{pubkey_hash}/{nonce}
		// We need to reconstruct: envelope_nonce/{pubkey_hash}/{nonce}
		suffix := string(expiryKey[len(types.EnvelopeNonceExpiryPrefix):])
		// Skip past the expiry timestamp (20 digits + "/")
		if len(suffix) > 21 {
			nonceKeySuffix := suffix[21:] // {pubkey_hash}/{nonce}
			nonceKey := []byte(types.EnvelopeNoncePrefix + nonceKeySuffix)
			_ = store.Delete(nonceKey)
		}
		_ = store.Delete(expiryKey)
		pruned++
	}
	return pruned, nil
}

// GetEnabledBridgeChains returns all enabled bridge chains from params
func (k Keeper) GetEnabledBridgeChains(ctx sdk.Context) []*types.BridgeChainConfig {
	params := k.GetParams(ctx)
	var enabled []*types.BridgeChainConfig
	for _, chain := range params.BridgeChains {
		if chain.Enabled {
			enabled = append(enabled, chain)
		}
	}
	return enabled
}
