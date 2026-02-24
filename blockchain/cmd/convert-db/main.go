package main

import (
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/cockroachdb/pebble"
	dbm "github.com/cosmos/cosmos-db"
)

const (
	dbName    = "application"
	batchSize = 1000
)

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintf(os.Stderr, "Usage: %s <data-dir>\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  Converts %s.db from GoLevelDB to PebbleDB\n", dbName)
		os.Exit(1)
	}

	dataDir := os.Args[1]
	srcPath := filepath.Join(dataDir, dbName+".db")

	if _, err := os.Stat(srcPath); os.IsNotExist(err) {
		fmt.Fprintf(os.Stderr, "ERROR: %s does not exist\n", srcPath)
		os.Exit(1)
	}

	tmpDir := filepath.Join(dataDir, "_pebble_convert_tmp")
	if err := os.MkdirAll(tmpDir, 0o755); err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: failed to create temp dir: %v\n", err)
		os.Exit(1)
	}

	dstPath := filepath.Join(tmpDir, dbName+".db")

	fmt.Printf("Opening GoLevelDB source: %s\n", srcPath)
	srcDB, err := dbm.NewGoLevelDB(dbName, dataDir, nil)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: failed to open source GoLevelDB: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Creating PebbleDB destination: %s\n", dstPath)
	dstDB, err := pebble.Open(dstPath, &pebble.Options{
		MaxConcurrentCompactions: func() int { return 1 },
	})
	if err != nil {
		srcDB.Close()
		fmt.Fprintf(os.Stderr, "ERROR: failed to create destination PebbleDB: %v\n", err)
		os.Exit(1)
	}

	fmt.Println("Starting key-value copy...")
	start := time.Now()
	copied, err := copyAll(srcDB, dstDB)
	elapsed := time.Since(start)

	srcDB.Close()

	if err != nil {
		dstDB.Close()
		os.RemoveAll(tmpDir)
		fmt.Fprintf(os.Stderr, "ERROR: copy failed after %d keys: %v\n", copied, err)
		os.Exit(1)
	}

	fmt.Printf("Copied %d keys in %s\n", copied, elapsed.Round(time.Millisecond))

	fmt.Println("Flushing and closing PebbleDB...")
	if err := dstDB.Flush(); err != nil {
		dstDB.Close()
		os.RemoveAll(tmpDir)
		fmt.Fprintf(os.Stderr, "ERROR: PebbleDB flush failed: %v\n", err)
		os.Exit(1)
	}
	if err := dstDB.Close(); err != nil {
		os.RemoveAll(tmpDir)
		fmt.Fprintf(os.Stderr, "ERROR: PebbleDB close failed: %v\n", err)
		os.Exit(1)
	}
	fmt.Printf("Conversion complete: %d keys\n", copied)

	bakPath := srcPath + ".bak"

	fmt.Printf("Renaming %s → %s\n", srcPath, bakPath)
	if err := os.Rename(srcPath, bakPath); err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: failed to rename source to backup: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Renaming %s → %s\n", dstPath, srcPath)
	if err := os.Rename(dstPath, srcPath); err != nil {
		os.Rename(bakPath, srcPath)
		fmt.Fprintf(os.Stderr, "ERROR: failed to move new DB into place: %v\n", err)
		os.Exit(1)
	}

	os.RemoveAll(tmpDir)
	fmt.Printf("Done. Backup at %s\n", bakPath)
}

func copyAll(src dbm.DB, dst *pebble.DB) (int64, error) {
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
			fmt.Printf("  progress: %d keys copied...\n", total)
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
