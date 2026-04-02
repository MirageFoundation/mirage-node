package main

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/cockroachdb/pebble"
)

type bucketInfo struct {
	name       string
	keyBytes   int64
	valBytes   int64
	count      int64
	minVersion uint32
	maxVersion uint32
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintf(os.Stderr, "Usage: %s <db-path>\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  Analyzes PebbleDB key distribution (read-only, safe while node is running).\n")
		fmt.Fprintf(os.Stderr, "  Example: %s /root/.mirage/node/data/application.db\n", os.Args[0])
		os.Exit(1)
	}

	dbPath := os.Args[1]

	// Symlink all files except LOCK into a temp dir so we can open read-only
	// without conflicting with the running node's exclusive lock.
	tmpDir, err := os.MkdirTemp("", "analyze-db-*")
	if err != nil {
		fmt.Fprintf(os.Stderr, "ERROR creating temp dir: %v\n", err)
		os.Exit(1)
	}
	defer os.RemoveAll(tmpDir)

	entries, err := os.ReadDir(dbPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ERROR reading db dir: %v\n", err)
		os.Exit(1)
	}
	for _, entry := range entries {
		if entry.Name() == "LOCK" {
			continue
		}
		src := filepath.Join(dbPath, entry.Name())
		dst := filepath.Join(tmpDir, entry.Name())
		if err := os.Symlink(src, dst); err != nil {
			fmt.Fprintf(os.Stderr, "ERROR symlinking %s: %v\n", entry.Name(), err)
			os.Exit(1)
		}
	}

	db, err := pebble.Open(tmpDir, &pebble.Options{ReadOnly: true})
	if err != nil {
		fmt.Fprintf(os.Stderr, "ERROR opening DB: %v\n", err)
		os.Exit(1)
	}
	defer db.Close()

	fmt.Println("=== PebbleDB Metrics ===")
	fmt.Println(db.Metrics().String())

	fmt.Println("=== Scanning all keys ===")

	buckets := make(map[string]*bucketInfo)
	addToBucket := func(name string, keyLen, valLen int, version uint32) {
		b, ok := buckets[name]
		if !ok {
			b = &bucketInfo{name: name, minVersion: ^uint32(0)}
			buckets[name] = b
		}
		b.keyBytes += int64(keyLen)
		b.valBytes += int64(valLen)
		b.count++
		if version > 0 {
			if version < b.minVersion {
				b.minVersion = version
			}
			if version > b.maxVersion {
				b.maxVersion = version
			}
		}
	}

	// Also count commit-info versions separately
	var commitInfoMin, commitInfoMax uint32
	commitInfoMin = ^uint32(0)
	var commitInfoCount int64

	iter, err := db.NewIter(nil)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ERROR creating iterator: %v\n", err)
		os.Exit(1)
	}
	defer iter.Close()

	var totalKeys, totalKeyBytes, totalValBytes int64

	for iter.First(); iter.Valid(); iter.Next() {
		key := iter.Key()
		val, err := iter.ValueAndErr()
		if err != nil {
			continue
		}

		totalKeys++
		totalKeyBytes += int64(len(key))
		totalValBytes += int64(len(val))

		bucket, version := classifyKey(key)
		addToBucket(bucket, len(key), len(val), version)

		// Track commit-info version range (s/<digit>... keys)
		if len(key) >= 3 && key[0] == 's' && key[1] == '/' && key[2] >= '0' && key[2] <= '9' {
			commitInfoCount++
			// Parse version number from s/<number> format
			vStr := string(key[2:])
			var v uint64
			fmt.Sscanf(vStr, "%d", &v)
			v32 := uint32(v)
			if v32 < commitInfoMin {
				commitInfoMin = v32
			}
			if v32 > commitInfoMax {
				commitInfoMax = v32
			}
		}
	}

	sorted := make([]*bucketInfo, 0, len(buckets))
	for _, b := range buckets {
		sorted = append(sorted, b)
	}
	sort.Slice(sorted, func(i, j int) bool {
		return (sorted[i].keyBytes + sorted[i].valBytes) > (sorted[j].keyBytes + sorted[j].valBytes)
	})

	fmt.Printf("\n%-45s %10s %10s %10s %10s %15s\n", "BUCKET", "KEY B", "VAL B", "TOTAL", "KEYS", "VERSION RANGE")
	fmt.Println(strings.Repeat("-", 105))
	for _, b := range sorted {
		total := b.keyBytes + b.valBytes
		vRange := ""
		if b.minVersion > 0 && b.minVersion != ^uint32(0) {
			vRange = fmt.Sprintf("v%d..v%d", b.minVersion, b.maxVersion)
		}
		fmt.Printf("%-45s %10s %10s %10s %10d %15s\n",
			b.name, fmtBytes(b.keyBytes), fmtBytes(b.valBytes), fmtBytes(total), b.count, vRange)
	}
	fmt.Println(strings.Repeat("-", 105))
	fmt.Printf("%-45s %10s %10s %10s %10d\n",
		"TOTAL", fmtBytes(totalKeyBytes), fmtBytes(totalValBytes),
		fmtBytes(totalKeyBytes+totalValBytes), totalKeys)

	if commitInfoCount > 0 {
		fmt.Printf("\n=== Commit Info (s/<version>) ===\n")
		fmt.Printf("Count: %d entries\n", commitInfoCount)
		fmt.Printf("Version range: %d .. %d (span: %d)\n", commitInfoMin, commitInfoMax, commitInfoMax-commitInfoMin+1)
		fmt.Printf("Expected with pruning-keep-recent=1000: ~1000 entries\n")
		if commitInfoCount > 1100 {
			fmt.Printf(">>> PRUNING APPEARS BROKEN: %d commit records vs expected ~1000 <<<\n", commitInfoCount)
		}
	}

	// Check the pruneSnapshotHeights key - the root cause
	pruneKey := []byte("s/prunesnapshotheights")
	prunIter, _ := db.NewIter(nil)
	defer func() { _ = prunIter.Close() }()
	fmt.Printf("\n=== Pruning Snapshot Heights (s/prunesnapshotheights) ===\n")
	if prunIter.SeekGE(pruneKey) && bytes.Equal(prunIter.Key(), pruneKey) {
		val, _ := prunIter.ValueAndErr()
		if len(val) == 0 {
			fmt.Println("Key exists but value is empty")
		} else {
			fmt.Printf("Raw bytes (%d): %x\n", len(val), val)
			fmt.Printf("Heights (%d entries): ", len(val)/8)
			for i := 0; i+8 <= len(val); i += 8 {
				h := binary.BigEndian.Uint64(val[i : i+8])
				if i > 0 {
					fmt.Print(", ")
				}
				fmt.Printf("%d", h)
			}
			fmt.Println()
			if len(val) >= 8 {
				first := binary.BigEndian.Uint64(val[0:8])
				fmt.Printf("\nFirst height: %d\n", first)
				fmt.Printf("If snapshot-interval=14400, pruning is capped at: %d\n", first+14400-1)
				fmt.Printf("Current height: ~%d\n", commitInfoMax)
				if first+14400 < uint64(commitInfoMax) {
					fmt.Println(">>> BUG CONFIRMED: pruneSnapshotHeights[0] is stale, blocking all pruning <<<")
				}
			}
		}
	} else {
		fmt.Println("Key NOT FOUND (never set)")
	}
}

func classifyKey(key []byte) (string, uint32) {
	// Cosmos SDK multistore format: s/k:<store_name>/<iavl_key>
	if len(key) >= 4 && bytes.HasPrefix(key, []byte("s/k:")) {
		rest := key[4:]
		slashIdx := bytes.IndexByte(rest, '/')
		if slashIdx < 0 {
			return "s/k:<malformed>", 0
		}
		storeName := string(rest[:slashIdx])
		iavlKey := rest[slashIdx+1:]

		if len(iavlKey) == 0 {
			return fmt.Sprintf("s/k:%s/<empty>", storeName), 0
		}

		// IAVL node keys: first byte is the type, then version(4 bytes) + nonce(4 bytes)
		firstByte := iavlKey[0]
		if firstByte == 'f' {
			return fmt.Sprintf("s/k:%s/fast-nodes", storeName), 0
		}
		if firstByte == 'r' {
			var ver uint32
			if len(iavlKey) >= 5 {
				ver = binary.BigEndian.Uint32(iavlKey[1:5])
			}
			return fmt.Sprintf("s/k:%s/roots", storeName), ver
		}
		if firstByte == 'o' {
			return fmt.Sprintf("s/k:%s/orphans", storeName), 0
		}

		// For node keys (any other prefix byte, typically 'n' or 's'), extract version
		var ver uint32
		if len(iavlKey) >= 5 {
			ver = binary.BigEndian.Uint32(iavlKey[1:5])
		}
		return fmt.Sprintf("s/k:%s/nodes", storeName), ver
	}

	// Multistore metadata: s/_:<store_name>
	if len(key) >= 4 && bytes.HasPrefix(key, []byte("s/")) {
		return fmt.Sprintf("s/%c:... (metadata)", key[2]), 0
	}

	if len(key) > 10 {
		return fmt.Sprintf("0x%x... (unknown)", key[:10]), 0
	}
	return fmt.Sprintf("0x%x (unknown)", key), 0
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
