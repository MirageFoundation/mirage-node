package main

import (
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/cockroachdb/pebble"
	dbm "github.com/cosmos/cosmos-db"
)

const batchSize = 1000

// NOTE: Deprecated after v1.17.0 once all nodes are on PebbleDB.
// Remove if no rollback to GoLevelDB is required.

func main() {
	if len(os.Args) < 3 {
		fmt.Fprintf(os.Stderr, "Usage: %s [--reverse] <data-dir> <db-name> [db-name ...]\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  Default:   GoLevelDB → PebbleDB\n")
		fmt.Fprintf(os.Stderr, "  --reverse: PebbleDB → GoLevelDB\n")
		fmt.Fprintf(os.Stderr, "  Example: %s /root/.mirage/node/data application blockstore state\n", os.Args[0])
		os.Exit(1)
	}

	args := os.Args[1:]
	reverse := false
	if args[0] == "--reverse" {
		reverse = true
		args = args[1:]
	}

	if len(args) < 2 {
		fmt.Fprintf(os.Stderr, "ERROR: need <data-dir> and at least one <db-name>\n")
		os.Exit(1)
	}

	dataDir := args[0]
	dbNames := args[1:]

	var failed []string
	for _, name := range dbNames {
		var err error
		if reverse {
			err = convertPebbleToLevelDB(dataDir, name)
		} else {
			err = convertLevelDBToPebble(dataDir, name)
		}
		if err != nil {
			fmt.Fprintf(os.Stderr, "ERROR converting %s: %v\n", name, err)
			failed = append(failed, name)
		}
	}

	if len(failed) > 0 {
		fmt.Fprintf(os.Stderr, "\nFailed databases: %v\n", failed)
		os.Exit(1)
	}
	fmt.Printf("\nAll %d databases converted successfully.\n", len(dbNames))
}

func convertLevelDBToPebble(dataDir, name string) error {
	srcPath := filepath.Join(dataDir, name+".db")
	if _, err := os.Stat(srcPath); os.IsNotExist(err) {
		fmt.Printf("[%s] skipping — %s does not exist\n", name, srcPath)
		return nil
	}

	tmpDir := filepath.Join(dataDir, "_pebble_convert_tmp_"+name)
	if err := os.MkdirAll(tmpDir, 0o755); err != nil {
		return fmt.Errorf("create temp dir: %w", err)
	}
	cleanup := func() { os.RemoveAll(tmpDir) }

	dstPath := filepath.Join(tmpDir, name+".db")

	fmt.Printf("\n[%s] Opening GoLevelDB: %s\n", name, srcPath)
	srcDB, err := dbm.NewGoLevelDB(name, dataDir, nil)
	if err != nil {
		cleanup()
		return fmt.Errorf("open source: %w", err)
	}

	fmt.Printf("[%s] Creating PebbleDB: %s\n", name, dstPath)
	dstDB, err := pebble.Open(dstPath, &pebble.Options{
		MaxConcurrentCompactions: func() int { return 1 },
	})
	if err != nil {
		srcDB.Close()
		cleanup()
		return fmt.Errorf("create destination: %w", err)
	}

	fmt.Printf("[%s] Copying keys (GoLevelDB → PebbleDB)...\n", name)
	start := time.Now()
	copied, err := copyLevelDBToPebble(name, srcDB, dstDB)
	elapsed := time.Since(start)

	srcDB.Close()

	if err != nil {
		dstDB.Close()
		cleanup()
		return fmt.Errorf("copy failed after %d keys: %w", copied, err)
	}

	fmt.Printf("[%s] Copied %d keys in %s\n", name, copied, elapsed.Round(time.Millisecond))

	fmt.Printf("[%s] Flushing...\n", name)
	if err := dstDB.Flush(); err != nil {
		dstDB.Close()
		cleanup()
		return fmt.Errorf("flush: %w", err)
	}
	if err := dstDB.Close(); err != nil {
		cleanup()
		return fmt.Errorf("close: %w", err)
	}

	return swapDirs(dataDir, name, srcPath, tmpDir, dstPath, cleanup)
}

func convertPebbleToLevelDB(dataDir, name string) error {
	srcPath := filepath.Join(dataDir, name+".db")
	if _, err := os.Stat(srcPath); os.IsNotExist(err) {
		fmt.Printf("[%s] skipping — %s does not exist\n", name, srcPath)
		return nil
	}

	tmpDir := filepath.Join(dataDir, "_leveldb_convert_tmp_"+name)
	if err := os.MkdirAll(tmpDir, 0o755); err != nil {
		return fmt.Errorf("create temp dir: %w", err)
	}
	cleanup := func() { os.RemoveAll(tmpDir) }

	fmt.Printf("\n[%s] Opening PebbleDB: %s\n", name, srcPath)
	srcDB, err := pebble.Open(srcPath, &pebble.Options{
		ReadOnly: true,
	})
	if err != nil {
		cleanup()
		return fmt.Errorf("open pebble source: %w", err)
	}

	dstPath := filepath.Join(tmpDir, name+".db")
	fmt.Printf("[%s] Creating GoLevelDB: %s\n", name, dstPath)
	dstDB, err := dbm.NewGoLevelDB(name, tmpDir, nil)
	if err != nil {
		srcDB.Close()
		cleanup()
		return fmt.Errorf("create leveldb destination: %w", err)
	}

	fmt.Printf("[%s] Copying keys (PebbleDB → GoLevelDB)...\n", name)
	start := time.Now()
	copied, err := copyPebbleToLevelDB(name, srcDB, dstDB)
	elapsed := time.Since(start)

	srcDB.Close()

	if err != nil {
		dstDB.Close()
		cleanup()
		return fmt.Errorf("copy failed after %d keys: %w", copied, err)
	}

	fmt.Printf("[%s] Copied %d keys in %s\n", name, copied, elapsed.Round(time.Millisecond))
	dstDB.Close()

	return swapDirs(dataDir, name, srcPath, tmpDir, dstPath, cleanup)
}

func swapDirs(dataDir, name, srcPath, tmpDir, dstPath string, cleanup func()) error {
	bakPath := srcPath + ".bak"
	fmt.Printf("[%s] %s → %s\n", name, srcPath, bakPath)
	if err := os.Rename(srcPath, bakPath); err != nil {
		return fmt.Errorf("backup rename: %w", err)
	}

	fmt.Printf("[%s] %s → %s\n", name, dstPath, srcPath)
	if err := os.Rename(dstPath, srcPath); err != nil {
		os.Rename(bakPath, srcPath)
		return fmt.Errorf("move new DB: %w", err)
	}

	cleanup()
	fmt.Printf("[%s] Done. Backup at %s\n", name, bakPath)
	return nil
}

func copyLevelDBToPebble(label string, src dbm.DB, dst *pebble.DB) (int64, error) {
	itr, err := src.Iterator(nil, nil)
	if err != nil {
		return 0, fmt.Errorf("creating iterator: %w", err)
	}
	defer itr.Close()

	var (
		total      int64
		batchCount int
		batch      = dst.NewBatch()
		lastReport = time.Now()
	)

	for ; itr.Valid(); itr.Next() {
		if err := batch.Set(itr.Key(), itr.Value(), nil); err != nil {
			batch.Close()
			return total, fmt.Errorf("batch set: %w", err)
		}

		batchCount++
		total++

		if batchCount >= batchSize {
			if err := batch.Commit(pebble.NoSync); err != nil {
				return total, fmt.Errorf("batch commit: %w", err)
			}
			batch = dst.NewBatch()
			batchCount = 0
		}

		if time.Since(lastReport) >= 5*time.Second {
			fmt.Printf("  [%s] %d keys copied...\n", label, total)
			lastReport = time.Now()
		}
	}

	if err := itr.Error(); err != nil {
		batch.Close()
		return total, fmt.Errorf("iterator error: %w", err)
	}

	if batchCount > 0 {
		if err := batch.Commit(pebble.NoSync); err != nil {
			return total, fmt.Errorf("final batch commit: %w", err)
		}
	} else {
		batch.Close()
	}

	return total, nil
}

func copyPebbleToLevelDB(label string, src *pebble.DB, dst dbm.DB) (int64, error) {
	iter, err := src.NewIter(nil)
	if err != nil {
		return 0, fmt.Errorf("creating pebble iterator: %w", err)
	}
	defer iter.Close()

	var (
		total      int64
		batchCount int
		batch      = dst.NewBatch()
		lastReport = time.Now()
	)

	for iter.First(); iter.Valid(); iter.Next() {
		key := make([]byte, len(iter.Key()))
		copy(key, iter.Key())
		val, err := iter.ValueAndErr()
		if err != nil {
			batch.Close()
			return total, fmt.Errorf("reading value: %w", err)
		}
		valCopy := make([]byte, len(val))
		copy(valCopy, val)

		if err := batch.Set(key, valCopy); err != nil {
			batch.Close()
			return total, fmt.Errorf("batch set: %w", err)
		}

		batchCount++
		total++

		if batchCount >= batchSize {
			if err := batch.Write(); err != nil {
				return total, fmt.Errorf("batch write: %w", err)
			}
			batch = dst.NewBatch()
			batchCount = 0
		}

		if time.Since(lastReport) >= 5*time.Second {
			fmt.Printf("  [%s] %d keys copied...\n", label, total)
			lastReport = time.Now()
		}
	}

	if err := iter.Error(); err != nil {
		batch.Close()
		return total, fmt.Errorf("iterator error: %w", err)
	}

	if batchCount > 0 {
		if err := batch.Write(); err != nil {
			return total, fmt.Errorf("final batch write: %w", err)
		}
	} else {
		batch.Close()
	}

	return total, nil
}
