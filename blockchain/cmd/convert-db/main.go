package main

import (
	"fmt"
	"os"
	"path/filepath"
	"time"

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
	defer os.RemoveAll(tmpDir)

	fmt.Printf("Opening GoLevelDB source: %s\n", srcPath)
	srcDB, err := dbm.NewGoLevelDB(dbName, dataDir, nil)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: failed to open source GoLevelDB: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Creating PebbleDB destination in: %s\n", tmpDir)
	dstDB, err := dbm.NewPebbleDB(dbName, tmpDir, nil)
	if err != nil {
		srcDB.Close()
		fmt.Fprintf(os.Stderr, "ERROR: failed to create destination PebbleDB: %v\n", err)
		os.Exit(1)
	}

	fmt.Println("Starting key-value copy...")
	start := time.Now()
	copied, err := copyAll(srcDB, dstDB)
	elapsed := time.Since(start)

	if err != nil {
		srcDB.Close()
		dstDB.Close()
		fmt.Fprintf(os.Stderr, "ERROR: copy failed after %d keys: %v\n", copied, err)
		os.Exit(1)
	}

	fmt.Printf("Copied %d keys in %s\n", copied, elapsed.Round(time.Millisecond))

	fmt.Println("Verifying destination key count...")
	dstCount, err := countKeys(dstDB)
	if err != nil {
		srcDB.Close()
		dstDB.Close()
		fmt.Fprintf(os.Stderr, "ERROR: failed to count destination keys: %v\n", err)
		os.Exit(1)
	}

	if dstCount != copied {
		srcDB.Close()
		dstDB.Close()
		fmt.Fprintf(os.Stderr, "ERROR: count mismatch — copied %d but destination has %d\n", copied, dstCount)
		os.Exit(1)
	}

	fmt.Printf("Verified: %d keys in destination\n", dstCount)

	srcDB.Close()
	dstDB.Close()

	bakPath := srcPath + ".bak"
	dstPath := filepath.Join(tmpDir, dbName+".db")

	fmt.Printf("Renaming %s → %s\n", srcPath, bakPath)
	if err := os.Rename(srcPath, bakPath); err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: failed to rename source to backup: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Renaming %s → %s\n", dstPath, srcPath)
	if err := os.Rename(dstPath, srcPath); err != nil {
		// Try to restore the original
		os.Rename(bakPath, srcPath)
		fmt.Fprintf(os.Stderr, "ERROR: failed to move new DB into place: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Done. Backup at %s\n", bakPath)
}

func copyAll(src, dst dbm.DB) (int64, error) {
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
		if err := batch.Set(itr.Key(), itr.Value()); err != nil {
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
			fmt.Printf("  progress: %d keys copied...\n", total)
			lastReport = time.Now()
		}
	}

	if err := itr.Error(); err != nil {
		batch.Close()
		return total, fmt.Errorf("iterator error: %w", err)
	}

	if batchCount > 0 {
		if err := batch.Write(); err != nil {
			return total, fmt.Errorf("final batch write: %w", err)
		}
	}

	return total, nil
}

func countKeys(db dbm.DB) (int64, error) {
	itr, err := db.Iterator(nil, nil)
	if err != nil {
		return 0, err
	}
	defer itr.Close()

	var count int64
	for ; itr.Valid(); itr.Next() {
		count++
	}
	if err := itr.Error(); err != nil {
		return 0, err
	}
	return count, nil
}
