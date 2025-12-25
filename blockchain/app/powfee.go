package app

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strings"

	sdk "github.com/cosmos/cosmos-sdk/types"
)

// powPayload mirrors the memo JSON we attach for PoW posts.
type powPayload struct {
	Pow string `json:"pow"`
}

// verifyPoW checks that sha256("challenge:proof") has the required leading zero bits.
func verifyPoW(challenge string, proofStr string, requiredBits uint8) bool {
	guess := challenge + ":" + proofStr
	sum := sha256.Sum256([]byte(guess))
	// Count leading zero bits
	bitsToCheck := requiredBits
	for i := 0; i < len(sum) && bitsToCheck > 0; i++ {
		b := sum[i]
		// count leading zeros in byte
		for bit := uint8(0); bit < 8 && bitsToCheck > 0; bit++ {
			if (b & (0x80 >> bit)) != 0 {
				return false
			}
			bitsToCheck--
		}
	}
	return bitsToCheck == 0
}

// extractPoW attempts to parse a PoW payload from the memo string.
// It supports either a raw JSON memo or a memo prefixed with "POST:" followed by JSON.
func extractPoW(memo string) (pow string, ok bool) {
	trimmed := strings.TrimSpace(memo)
	if trimmed == "" {
		return "", false
	}
	if strings.HasPrefix(trimmed, "POST:") {
		trimmed = strings.TrimSpace(strings.TrimPrefix(trimmed, "POST:"))
	}
	var p powPayload
	if err := json.Unmarshal([]byte(trimmed), &p); err != nil {
		return "", false
	}
	if p.Pow == "" {
		return "", false
	}
	// quick sanity: challenge should be 64 hex chars
	parts := strings.SplitN(p.Pow, ":", 2)
	if len(parts) != 2 {
		return "", false
	}
	if len(parts[0]) != 64 {
		return "", false
	}
	_, err := hex.DecodeString(parts[0])
	if err != nil {
		return "", false
	}
	return p.Pow, true
}

// txPaysAnyFee returns true if fee coins contain any non-zero amount.
func txPaysAnyFee(tx sdk.FeeTx) bool {
	fee := tx.GetFee()
	if fee == nil || fee.IsZero() {
		return false
	}
	for _, c := range fee {
		if !c.Amount.IsZero() {
			return true
		}
	}
	return false
}
