package app

import (
	"encoding/hex"
	"encoding/json"
	"os"
	"testing"

	coretypes "mirage/x/core/types"
)

// The relay signature and the PoW preimage are produced independently by the
// chain (Go), the backend/tests (shared/canon.py) and the browser
// (TransactionHandler.js). A single byte of disagreement makes an otherwise
// valid transaction unverifiable, and the failure only shows up for the exact
// field combination that diverged — a false boolean, for instance. These
// vectors are generated from shared/canon.py so the two implementations are
// pinned to each other byte for byte.

type canonEnvelope struct {
	PubkeyHex    string `json:"pubkey_hex"`
	BlockHashHex string `json:"block_hash_hex"`
	Difficulty   uint64 `json:"difficulty"`
	Timestamp    uint64 `json:"timestamp"`
	Nonce        uint64 `json:"nonce"`
}

type canonVectorFile struct {
	Envelope             canonEnvelope `json:"envelope"`
	LegacyMobileEnvelope canonEnvelope `json:"legacy_mobile_envelope"`
	Vectors              []struct {
		Msg      string         `json:"msg"`
		Fields   map[string]any `json:"fields"`
		CanonHex string         `json:"canon_hex"`
		Envelope string         `json:"envelope"`
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
	stringsList := func(fields map[string]any, key string) []string {
		v, ok := fields[key]
		if !ok {
			t.Fatalf("vector missing list field %q", key)
		}
		values, ok := v.([]any)
		if !ok {
			t.Fatalf("vector field %q is not a list", key)
		}
		out := make([]string, len(values))
		for i, value := range values {
			s, ok := value.(string)
			if !ok {
				t.Fatalf("vector field %q item %d is not a string", key, i)
			}
			out[i] = s
		}
		return out
	}

	for _, vec := range file.Vectors {
		envelope := file.Envelope
		if vec.Envelope == "legacy_mobile" {
			envelope = file.LegacyMobileEnvelope
		} else if vec.Envelope != "" {
			t.Fatalf("vector uses unknown envelope %q", vec.Envelope)
		}
		pubkey, err := hex.DecodeString(envelope.PubkeyHex)
		if err != nil {
			t.Fatalf("decode pubkey: %v", err)
		}
		blockHash, err := hex.DecodeString(envelope.BlockHashHex)
		if err != nil {
			t.Fatalf("decode block hash: %v", err)
		}
		fields := vec.Fields
		var fill func(w *canonWriter)
		var gotBytes []byte
		switch vec.Msg {
		case "MsgPost":
			gotBytes = buildCanonForPost(&coretypes.MsgPost{
				EnvelopePubkey:     pubkey,
				EnvelopeBlockHash:  blockHash,
				EnvelopeDifficulty: envelope.Difficulty,
				EnvelopeTimestamp:  envelope.Timestamp,
				EnvelopeNonce:      envelope.Nonce,
				Target:             str(fields, "target"),
				Community:          str(fields, "community"),
				Title:              str(fields, "title"),
				Content:            str(fields, "content"),
				Tag:                str(fields, "tag"),
				Media:              stringsList(fields, "media"),
				ProtocolVersion:    uint32(u64(fields, "protocol_version")),
			})
		case "MsgSubscribe":
			gotBytes = buildCanonForSubscribe(&coretypes.MsgSubscribe{
				EnvelopePubkey:     pubkey,
				EnvelopeBlockHash:  blockHash,
				EnvelopeDifficulty: envelope.Difficulty,
				EnvelopeTimestamp:  envelope.Timestamp,
				EnvelopeNonce:      envelope.Nonce,
				Level:              uint32(u64(fields, "level")),
				Target:             str(fields, "target"),
				PeriodCount:        uint32(u64(fields, "period_count")),
			})
		case "MsgFollowTopic":
			gotBytes = buildCanonForFollowTopic(&coretypes.MsgFollowTopic{
				EnvelopePubkey: pubkey, EnvelopeBlockHash: blockHash,
				EnvelopeDifficulty: envelope.Difficulty, EnvelopeTimestamp: envelope.Timestamp,
				EnvelopeNonce: envelope.Nonce, Target: str(fields, "target"), Topic: str(fields, "topic"),
			})
		case "MsgUnfollowTopic":
			gotBytes = buildCanonForUnfollowTopic(&coretypes.MsgUnfollowTopic{
				EnvelopePubkey: pubkey, EnvelopeBlockHash: blockHash,
				EnvelopeDifficulty: envelope.Difficulty, EnvelopeTimestamp: envelope.Timestamp,
				EnvelopeNonce: envelope.Nonce, Target: str(fields, "target"), Topic: str(fields, "topic"),
			})
		case "MsgBlockTopic":
			gotBytes = buildCanonForBlockTopic(&coretypes.MsgBlockTopic{
				EnvelopePubkey: pubkey, EnvelopeBlockHash: blockHash,
				EnvelopeDifficulty: envelope.Difficulty, EnvelopeTimestamp: envelope.Timestamp,
				EnvelopeNonce: envelope.Nonce, Target: str(fields, "target"), Topic: str(fields, "topic"),
			})
		case "MsgUnblockTopic":
			gotBytes = buildCanonForUnblockTopic(&coretypes.MsgUnblockTopic{
				EnvelopePubkey: pubkey, EnvelopeBlockHash: blockHash,
				EnvelopeDifficulty: envelope.Difficulty, EnvelopeTimestamp: envelope.Timestamp,
				EnvelopeNonce: envelope.Nonce, Target: str(fields, "target"), Topic: str(fields, "topic"),
			})
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
		case "MsgJoinCommunity":
			fill = func(w *canonWriter) {
				w.writeString(100, str(fields, "community"))
				w.writeUvarint(101, u64(fields, "mode"))
				w.writeUvarint(102, u64(fields, "pinned_team_id"))
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

		if gotBytes == nil {
			gotBytes = buildCanonV139(
				vec.Msg,
				pubkey,
				blockHash,
				envelope.Difficulty,
				envelope.Timestamp,
				envelope.Nonce,
				fill,
			)
		}
		got := hex.EncodeToString(gotBytes)
		if got != vec.CanonHex {
			t.Errorf("%s canon mismatch with shared/canon.py\n fields: %v\n go:     %s\n python: %s",
				vec.Msg, fields, got, vec.CanonHex)
		}
	}
}

func TestLegacyCanonDiffersOnlyByOmittedVersionFields(t *testing.T) {
	post := &coretypes.MsgPost{Media: []string{"https://example.com/a.jpg"}}
	legacyPost := buildCanonForPost(post)
	post.ProtocolVersion = 1
	modernPost := buildCanonForPost(post)
	expectedPost := append(append([]byte{}, legacyPost...), 106, 1)
	if string(modernPost) != string(expectedPost) {
		t.Fatalf("modern post canon does not differ only by tag 106")
	}

	subscribe := &coretypes.MsgSubscribe{Level: 1}
	legacySubscribe := buildCanonForSubscribe(subscribe)
	subscribe.PeriodCount = 1
	modernSubscribe := buildCanonForSubscribe(subscribe)
	expectedSubscribe := append(append([]byte{}, legacySubscribe...), 102, 1)
	if string(modernSubscribe) != string(expectedSubscribe) {
		t.Fatalf("modern subscribe canon does not differ only by tag 102")
	}
}
