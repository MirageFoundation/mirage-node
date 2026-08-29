package app

import (
	"encoding/hex"
	"encoding/json"
	"os"
	"testing"
)

// The relay signature and the PoW preimage are produced independently by the
// chain (Go), the backend/tests (shared/canon.py) and the browser
// (TransactionHandler.js). A single byte of disagreement makes an otherwise
// valid transaction unverifiable, and the failure only shows up for the exact
// field combination that diverged — a false boolean, for instance. These
// vectors are generated from shared/canon.py so the two implementations are
// pinned to each other byte for byte.

type canonVectorFile struct {
	Envelope struct {
		PubkeyHex    string `json:"pubkey_hex"`
		BlockHashHex string `json:"block_hash_hex"`
		Difficulty   uint64 `json:"difficulty"`
		Timestamp    uint64 `json:"timestamp"`
		Nonce        uint64 `json:"nonce"`
	} `json:"envelope"`
	Vectors []struct {
		Msg      string         `json:"msg"`
		Fields   map[string]any `json:"fields"`
		CanonHex string         `json:"canon_hex"`
	} `json:"vectors"`
}

func TestCanonV139MatchesSharedPythonVectors(t *testing.T) {
	raw, err := os.ReadFile("../../shared/testdata/canon_v139_vectors.json")
	if err != nil {
		t.Fatalf("read vectors: %v", err)
	}
	var file canonVectorFile
	if err := json.Unmarshal(raw, &file); err != nil {
		t.Fatalf("parse vectors: %v", err)
	}
	pubkey, err := hex.DecodeString(file.Envelope.PubkeyHex)
	if err != nil {
		t.Fatalf("decode pubkey: %v", err)
	}
	blockHash, err := hex.DecodeString(file.Envelope.BlockHashHex)
	if err != nil {
		t.Fatalf("decode block hash: %v", err)
	}
	if len(file.Vectors) == 0 {
		t.Fatal("vector file is empty")
	}

	str := func(fields map[string]any, key string) string {
		v, ok := fields[key]
		if !ok {
			t.Fatalf("vector missing string field %q", key)
		}
		s, ok := v.(string)
		if !ok {
			t.Fatalf("vector field %q is not a string", key)
		}
		return s
	}
	u64 := func(fields map[string]any, key string) uint64 {
		v, ok := fields[key]
		if !ok {
			t.Fatalf("vector missing numeric field %q", key)
		}
		n, ok := v.(float64)
		if !ok {
			t.Fatalf("vector field %q is not a number", key)
		}
		return uint64(n)
	}
	boolean := func(fields map[string]any, key string) bool {
		v, ok := fields[key]
		if !ok {
			t.Fatalf("vector missing bool field %q", key)
		}
		b, ok := v.(bool)
		if !ok {
			t.Fatalf("vector field %q is not a bool", key)
		}
		return b
	}

	for _, vec := range file.Vectors {
		fields := vec.Fields
		var fill func(w *canonWriter)
		switch vec.Msg {
		case "MsgCreateCurationTeam":
			fill = func(w *canonWriter) {
				w.writeString(100, str(fields, "community"))
				w.writeString(101, str(fields, "name"))
				w.writeString(102, str(fields, "description"))
			}
		case "MsgSetCurationTeamProfile":
			fill = func(w *canonWriter) {
				w.writeString(100, str(fields, "community"))
				w.writeUvarint(101, u64(fields, "team_id"))
				w.writeString(102, str(fields, "name"))
				w.writeString(103, str(fields, "description"))
			}
		case "MsgInviteCurator", "MsgRevokeCuratorInvite", "MsgRemoveCurator":
			fill = func(w *canonWriter) {
				w.writeString(100, str(fields, "community"))
				w.writeUvarint(101, u64(fields, "team_id"))
				w.writeString(102, str(fields, "target"))
			}
		case "MsgAcceptCuratorInvite", "MsgDeclineCuratorInvite", "MsgLeaveCurationTeam", "MsgDeleteCurationTeam":
			fill = func(w *canonWriter) {
				w.writeString(100, str(fields, "community"))
				w.writeUvarint(101, u64(fields, "team_id"))
			}
		case "MsgTransferCurationTeam":
			fill = func(w *canonWriter) {
				w.writeString(100, str(fields, "community"))
				w.writeUvarint(101, u64(fields, "team_id"))
				w.writeString(102, str(fields, "new_owner"))
			}
		case "MsgSetCurationPreference":
			fill = func(w *canonWriter) {
				w.writeString(100, str(fields, "community"))
				w.writeUvarint(101, u64(fields, "mode"))
				w.writeUvarint(102, u64(fields, "pinned_team_id"))
			}
		case "MsgSetCurationPostHidden", "MsgSetCurationUserHidden":
			fill = func(w *canonWriter) {
				w.writeString(100, str(fields, "community"))
				w.writeUvarint(101, u64(fields, "team_id"))
				w.writeString(102, str(fields, "target"))
				writeCanonBool(w, 103, boolean(fields, "hidden"))
			}
		case "MsgSetCurationThreadLocked":
			fill = func(w *canonWriter) {
				w.writeString(100, str(fields, "community"))
				w.writeUvarint(101, u64(fields, "team_id"))
				w.writeString(102, str(fields, "root_hash"))
				writeCanonBool(w, 103, boolean(fields, "locked"))
			}
		case "MsgSetCurationSubscriberOnly":
			fill = func(w *canonWriter) {
				w.writeString(100, str(fields, "community"))
				w.writeUvarint(101, u64(fields, "team_id"))
				writeCanonBool(w, 102, boolean(fields, "enabled"))
			}
		case "MsgSetCurationTag":
			fill = func(w *canonWriter) {
				w.writeString(100, str(fields, "community"))
				w.writeUvarint(101, u64(fields, "team_id"))
				w.writeString(102, str(fields, "tag"))
			}
		case "MsgSetCurationPostTag":
			fill = func(w *canonWriter) {
				w.writeString(100, str(fields, "community"))
				w.writeUvarint(101, u64(fields, "team_id"))
				w.writeString(102, str(fields, "target"))
				w.writeString(103, str(fields, "tag"))
				writeCanonBool(w, 104, boolean(fields, "clear"))
			}
		default:
			t.Fatalf("vector for unknown message %q — add the Go canon layout here", vec.Msg)
		}

		got := hex.EncodeToString(buildCanonV139(
			vec.Msg,
			pubkey,
			blockHash,
			file.Envelope.Difficulty,
			file.Envelope.Timestamp,
			file.Envelope.Nonce,
			fill,
		))
		if got != vec.CanonHex {
			t.Errorf("%s canon mismatch with shared/canon.py\n fields: %v\n go:     %s\n python: %s",
				vec.Msg, fields, got, vec.CanonHex)
		}
	}
}
