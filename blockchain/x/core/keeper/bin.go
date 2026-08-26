package keeper

import (
	"encoding/binary"
	"encoding/json"
	"fmt"

	sdkmath "cosmossdk.io/math"
	"github.com/cosmos/cosmos-sdk/codec"
	sdk "github.com/cosmos/cosmos-sdk/types"
	proto "github.com/cosmos/gogoproto/proto"

	"mirage/x/core/types"
)

func putU32(v uint32) []byte {
	b := make([]byte, 4)
	binary.BigEndian.PutUint32(b, v)
	return b
}

func getU32(b []byte) (uint32, error) {
	if len(b) != 4 {
		return 0, fmt.Errorf("expected 4-byte uint32, got %d", len(b))
	}
	return binary.BigEndian.Uint32(b), nil
}

func putU64(v uint64) []byte {
	b := make([]byte, 8)
	binary.BigEndian.PutUint64(b, v)
	return b
}

func getU64(b []byte) (uint64, error) {
	if len(b) != 8 {
		return 0, fmt.Errorf("expected 8-byte uint64, got %d", len(b))
	}
	return binary.BigEndian.Uint64(b), nil
}

func (k Keeper) IterPrefix(ctx sdk.Context, prefix []byte, limit int, fn func(key, value []byte) error) error {
	return k.iterPrefixKeys(ctx, prefix, limit, fn)
}

func (k Keeper) CDC() codec.Codec { return k.cdc }

func (k Keeper) GetRaw(ctx sdk.Context, key []byte) ([]byte, error) {
	return k.storeGet(ctx, key)
}

func (k Keeper) GetProto(ctx sdk.Context, key []byte, msg proto.Message) (bool, error) {
	return k.getProto(ctx, key, msg)
}

func (k Keeper) GetU32(ctx sdk.Context, key []byte) (uint32, bool, error) {
	return k.getU32Key(ctx, key)
}

func (k Keeper) storeSet(ctx sdk.Context, key, val []byte) error {
	return k.storeService.OpenKVStore(ctx).Set(key, val)
}

func (k Keeper) storeGet(ctx sdk.Context, key []byte) ([]byte, error) {
	return k.storeService.OpenKVStore(ctx).Get(key)
}

func (k Keeper) storeHas(ctx sdk.Context, key []byte) (bool, error) {
	return k.storeService.OpenKVStore(ctx).Has(key)
}

func (k Keeper) storeDelete(ctx sdk.Context, key []byte) error {
	return k.storeService.OpenKVStore(ctx).Delete(key)
}

func (k Keeper) setProto(ctx sdk.Context, key []byte, msg proto.Message) error {
	bz, err := k.cdc.Marshal(msg)
	if err != nil {
		return err
	}
	return k.storeSet(ctx, key, bz)
}

func (k Keeper) getProto(ctx sdk.Context, key []byte, msg proto.Message) (bool, error) {
	bz, err := k.storeGet(ctx, key)
	if err != nil {
		return false, err
	}
	if len(bz) == 0 {
		return false, nil
	}
	if err := k.cdc.Unmarshal(bz, msg); err != nil {
		return false, err
	}
	return true, nil
}

func (k Keeper) LoadProfile(ctx sdk.Context, owner string) (types.ProfileCore, bool, error) {
	return k.loadProfile(ctx, owner)
}

func (k Keeper) SaveProfile(ctx sdk.Context, core types.ProfileCore) error {
	return k.saveProfile(ctx, core)
}

func (k Keeper) loadProfile(ctx sdk.Context, owner string) (types.ProfileCore, bool, error) {
	bz, found, err := k.GetProfileCore(ctx, owner)
	if err != nil {
		return types.ProfileCore{}, false, err
	}
	if !found {
		return types.ProfileCore{}, false, nil
	}
	var core types.ProfileCore
	if err := json.Unmarshal(bz, &core); err != nil {
		return types.ProfileCore{}, false, fmt.Errorf("corrupt profile JSON for %s: %w", owner, err)
	}
	return core, true, nil
}

func (k Keeper) saveProfile(ctx sdk.Context, core types.ProfileCore) error {
	bz, err := json.Marshal(core)
	if err != nil {
		return err
	}
	return k.SetProfileCore(ctx, core.Owner, bz)
}

func (k Keeper) getU64Key(ctx sdk.Context, key []byte) (uint64, bool, error) {
	bz, err := k.storeGet(ctx, key)
	if err != nil {
		return 0, false, err
	}
	if len(bz) == 0 {
		return 0, false, nil
	}
	v, err := getU64(bz)
	return v, true, err
}

func (k Keeper) setU64Key(ctx sdk.Context, key []byte, v uint64) error {
	return k.storeSet(ctx, key, putU64(v))
}

func (k Keeper) getU32Key(ctx sdk.Context, key []byte) (uint32, bool, error) {
	bz, err := k.storeGet(ctx, key)
	if err != nil {
		return 0, false, err
	}
	if len(bz) == 0 {
		return 0, false, nil
	}
	v, err := getU32(bz)
	return v, true, err
}

func (k Keeper) setU32Key(ctx sdk.Context, key []byte, v uint32) error {
	return k.storeSet(ctx, key, putU32(v))
}

func (k Keeper) addCheckedU32(ctx sdk.Context, key []byte, delta int64) (uint32, error) {
	cur, _, err := k.getU32Key(ctx, key)
	if err != nil {
		return 0, err
	}
	next := int64(cur) + delta
	if next < 0 || next > int64(^uint32(0)) {
		return 0, fmt.Errorf("uint32 counter overflow/underflow at %q: %d + %d", string(key), cur, delta)
	}
	if next == 0 {
		if err := k.storeDelete(ctx, key); err != nil {
			return 0, err
		}
		return 0, nil
	}
	if err := k.setU32Key(ctx, key, uint32(next)); err != nil {
		return 0, err
	}
	return uint32(next), nil
}

func (k Keeper) addCheckedU64(ctx sdk.Context, key []byte, delta int64) (uint64, error) {
	cur, _, err := k.getU64Key(ctx, key)
	if err != nil {
		return 0, err
	}
	if delta >= 0 {
		sum, err := types.CheckedAddUint64(cur, uint64(delta))
		if err != nil {
			return 0, err
		}
		if err := k.setU64Key(ctx, key, sum); err != nil {
			return 0, err
		}
		return sum, nil
	}
	sub := uint64(-delta)
	if cur < sub {
		return 0, fmt.Errorf("uint64 underflow at %q: %d - %d", string(key), cur, sub)
	}
	next := cur - sub
	if next == 0 {
		if err := k.storeDelete(ctx, key); err != nil {
			return 0, err
		}
		return 0, nil
	}
	if err := k.setU64Key(ctx, key, next); err != nil {
		return 0, err
	}
	return next, nil
}

func (k Keeper) iterPrefixKeys(ctx sdk.Context, prefix []byte, limit int, fn func(key, value []byte) error) error {
	return k.iterPrefixFrom(ctx, prefix, prefix, false, limit, fn)
}

func (k Keeper) iterPrefixFrom(ctx sdk.Context, prefix, start []byte, exclusive bool, limit int, fn func(key, value []byte) error) error {
	store := k.storeService.OpenKVStore(ctx)
	if len(start) == 0 {
		start = prefix
	}
	it, err := store.Iterator(start, prefixEndBytes(prefix))
	if err != nil {
		return err
	}
	n := 0
	skipped := !exclusive
	for ; it.Valid(); it.Next() {
		kcopy := append([]byte(nil), it.Key()...)
		if !skipped {
			skipped = true
			continue
		}
		if limit > 0 && n >= limit {
			break
		}
		vcopy := append([]byte(nil), it.Value()...)
		if err := fn(kcopy, vcopy); err != nil {
			_ = it.Close()
			return err
		}
		n++
	}
	if err := it.Error(); err != nil {
		_ = it.Close()
		return err
	}
	return it.Close()
}

func (k Keeper) intString(v sdkmath.Int) string {
	return v.String()
}

func (k Keeper) parseInt(s string) (sdkmath.Int, error) {
	if s == "" {
		return sdkmath.ZeroInt(), nil
	}
	v, ok := sdkmath.NewIntFromString(s)
	if !ok {
		return sdkmath.Int{}, fmt.Errorf("invalid integer %q", s)
	}
	return v, nil
}
