package iavl

import (
	"errors"
	"testing"

	dbm "github.com/cosmos/iavl/db"
)

var errFlushFailed = errors.New("write /data/application.db: no space left on device")

// flushFailDB hands out batches whose Write always fails, standing in for a full
// or read-only volume during commit.
type flushFailDB struct {
	dbm.DB
}

func (d flushFailDB) NewBatch() dbm.Batch { return &flushFailBatch{} }

func (d flushFailDB) NewBatchWithSize(int) dbm.Batch { return &flushFailBatch{} }

type flushFailBatch struct {
	size int
}

func (b *flushFailBatch) Set(key, value []byte) error {
	b.size += len(key) + len(value)
	return nil
}
func (b *flushFailBatch) Delete(key []byte) error   { b.size += len(key); return nil }
func (b *flushFailBatch) Write() error              { return errFlushFailed }
func (b *flushFailBatch) WriteSync() error          { return errFlushFailed }
func (b *flushFailBatch) Close() error              { return nil }
func (b *flushFailBatch) GetByteSize() (int, error) { return b.size, nil }

// TestSetSurfacesFlushErrorInsteadOfMutexPanic pins the fix for the
// already-unlocked-mutex bug on the flush-error path.
//
// Set and Delete drop the lock around the threshold flush and re-take it, but
// upstream's error path returned while still unlocked, so the deferred Unlock
// panicked with "sync: unlock of unlocked mutex". The operator then saw a
// runtime mutex error instead of the disk-full error that actually happened, on
// the one path where the real cause matters most.
func TestSetSurfacesFlushErrorInsteadOfMutexPanic(t *testing.T) {
	// flushThreshold of 1 makes the very first Set cross it.
	b := NewBatchWithFlusher(flushFailDB{}, 1)

	defer func() {
		if r := recover(); r != nil {
			t.Fatalf("Set panicked instead of returning the flush error: %v", r)
		}
	}()

	err := b.Set([]byte("key"), []byte("value"))
	if !errors.Is(err, errFlushFailed) {
		t.Fatalf("Set returned %v, want the underlying flush error", err)
	}

	// The mutex must be usable afterwards. Before the fix the deferred Unlock had
	// already panicked, so this could never be reached.
	if err := b.Close(); err != nil {
		t.Fatalf("Close after a failed flush: %v", err)
	}
}

func TestDeleteSurfacesFlushErrorInsteadOfMutexPanic(t *testing.T) {
	b := NewBatchWithFlusher(flushFailDB{}, 1)

	defer func() {
		if r := recover(); r != nil {
			t.Fatalf("Delete panicked instead of returning the flush error: %v", r)
		}
	}()

	err := b.Delete([]byte("key"))
	if !errors.Is(err, errFlushFailed) {
		t.Fatalf("Delete returned %v, want the underlying flush error", err)
	}
	if err := b.Close(); err != nil {
		t.Fatalf("Close after a failed flush: %v", err)
	}
}
