package main

import (
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/cockroachdb/pebble"
)

// maxCompactKey is a key guaranteed to be >= any real key in the database.
var maxCompactKey = bytes16FF()

func bytes16FF() []byte {
	b := make([]byte, 16)
	for i := range b {
		b[i] = 0xff
	}
	return b
}

func main() {
	if len(os.Args) < 3 {
		fmt.Fprintf(os.Stderr, "Usage: %s <data-dir> <db-name> [db-name ...]\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  Forces full PebbleDB compaction to reclaim disk space from tombstones.\n")
		fmt.Fprintf(os.Stderr, "  Example: %s /root/.mirage/node/data application blockstore state tx_index evidence\n", os.Args[0])
		os.Exit(1)
	}

	dataDir := os.Args[1]
	dbNames := os.Args[2:]

	var failed []string
	for _, name := range dbNames {
		if err := compactDB(dataDir, name); err != nil {
			fmt.Fprintf(os.Stderr, "ERROR compacting %s: %v\n", name, err)
			failed = append(failed, name)
		}
	}

	if len(failed) > 0 {
		fmt.Fprintf(os.Stderr, "\nFailed databases: %v\n", failed)
		os.Exit(1)
	}
	fmt.Printf("\nAll %d databases compacted successfully.\n", len(dbNames))
}

func dirSize(path string) (int64, error) {
	var total int64
	err := filepath.Walk(path, func(_ string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() {
			total += info.Size()
		}
		return nil
	})
	return total, err
}

func fmtBytes(b int64) string {
	switch {
	case b >= 1<<30:
		return fmt.Sprintf("%.2f GB", float64(b)/float64(1<<30))
	case b >= 1<<20:
		return fmt.Sprintf("%.1f MB", float64(b)/float64(1<<20))
	case b >= 1<<10:
		return fmt.Sprintf("%.0f KB", float64(b)/float64(1<<10))
	default:
		return fmt.Sprintf("%d B", b)
	}
}

func compactDB(dataDir, name string) error {
	dbPath := filepath.Join(dataDir, name+".db")
	if _, err := os.Stat(dbPath); os.IsNotExist(err) {
		fmt.Printf("[%s] skipping — %s does not exist\n", name, dbPath)
		return nil
	}

	beforeSize, _ := dirSize(dbPath)
	fmt.Printf("\n[%s] Opening PebbleDB: %s (%s)\n", name, dbPath, fmtBytes(beforeSize))

	db, err := pebble.Open(dbPath, &pebble.Options{})
	if err != nil {
		return fmt.Errorf("open: %w", err)
	}

	fmt.Printf("[%s] Running full compaction...\n", name)
	start := time.Now()

	if err := db.Compact(nil, maxCompactKey, true); err != nil {
		db.Close()
		return fmt.Errorf("compact: %w", err)
	}

	elapsed := time.Since(start)
	fmt.Printf("[%s] Compaction completed in %s\n", name, elapsed.Round(time.Millisecond))

	if err := db.Close(); err != nil {
		return fmt.Errorf("close: %w", err)
	}

	afterSize, _ := dirSize(dbPath)
	saved := beforeSize - afterSize
	pct := float64(0)
	if beforeSize > 0 {
		pct = float64(saved) / float64(beforeSize) * 100
	}
	fmt.Printf("[%s] %s → %s (freed %s, %.0f%%)\n", name, fmtBytes(beforeSize), fmtBytes(afterSize), fmtBytes(saved), pct)
	return nil
}
