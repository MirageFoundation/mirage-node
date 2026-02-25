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

func main() {
	if len(os.Args) < 3 {
		fmt.Fprintf(os.Stderr, "Usage: %s <data-dir> <db-name> [db-name ...]\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  Converts GoLevelDB databases to PebbleDB\n")
		fmt.Fprintf(os.Stderr, "  Example: %s /root/.mirage/node/data application blockstore state tx_index evidence\n", os.Args[0])
		os.Exit(1)
	}

	dataDir := os.Args[1]
	dbNames := os.Args[2:]

	var failed []string
	for _, name := range dbNames {
		if err := convertDB(dataDir, name); err != nil {
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

func convertDB(dataDir, name string) error {
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

	fmt.Printf("[%s] Copying keys...\n", name)
	start := time.Now()
	copied, err := copyAll(name, srcDB, dstDB)
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

	bakPath := srcPath + ".bak"
	fmt.Printf("[%s] %s → %s\n", name, srcPath, bakPath)
	if err := os.Rename(srcPath, bakPath); err != nil {
		return fmt.Errorf("backup rename: %w", err)
	}

	fmt.Printf("[%s] %s → %s\n", name, dstPath, srcPath)
	if err := os.Rename(dstPath, srcPath); err != nil {
		os.Rename(bakPath, srcPath) // restore
		return fmt.Errorf("move new DB: %w", err)
	}

	cleanup()
	fmt.Printf("[%s] Done (%d keys). Backup at %s\n", name, copied, bakPath)
	return nil
}

func copyAll(label string, src dbm.DB, dst *pebble.DB) (int64, error) {
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
