package app

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"reflect"
	"strings"
	"testing"

	coretypes "mirage/x/core/types"
)

// populateFields fills the struct with unique values based on field name/type
func populateFields(t *testing.T, obj interface{}) {
	v := reflect.ValueOf(obj).Elem()
	typ := v.Type()

	for i := 0; i < v.NumField(); i++ {
		field := v.Field(i)
		fieldName := typ.Field(i).Name

		// Skip internal fields (protobuf XXX fields)
		if strings.HasPrefix(fieldName, "XXX_") {
			continue
		}

		switch field.Kind() {
		case reflect.String:
			// Use a distinct string for each field
			field.SetString(fmt.Sprintf("%s_unique_val", fieldName))
		case reflect.Uint64:
			// Use a unique value based on index to distinguish fields
			// Ensure it's large enough to likely not collide with small constants
			field.SetUint(uint64(1000000 + i))
		case reflect.Int32:
			// Enums often small, hope 10+i is valid or just int32
			field.SetInt(int64(10 + i))
		case reflect.Slice:
			if field.Type().Elem().Kind() == reflect.Uint8 { // []byte
				field.SetBytes([]byte(fmt.Sprintf("%s_bytes", fieldName)))
			} else if field.Type().Elem().Kind() == reflect.String { // []string
				s := []string{fmt.Sprintf("%s_1", fieldName), fmt.Sprintf("%s_2", fieldName)}
				field.Set(reflect.ValueOf(s))
			}
		}
	}
}

func verifyCanon(t *testing.T, obj interface{}, canon []byte, ignoredFields ...string) {
	v := reflect.ValueOf(obj).Elem()
	typ := v.Type()

	ignored := make(map[string]bool)
	for _, f := range ignoredFields {
		ignored[f] = true
	}
	// Always ignore standard excluded fields if they exist
	ignored["Authority"] = true
	ignored["EnvelopeSignature"] = true
	ignored["EnvelopePow"] = true // Explicitly excluded in ante_pow.go comments

	for i := 0; i < v.NumField(); i++ {
		field := v.Field(i)
		fieldName := typ.Field(i).Name

		if strings.HasPrefix(fieldName, "XXX_") {
			continue
		}
		if ignored[fieldName] {
			continue
		}

		var search []byte
		var valStr string

		switch field.Kind() {
		case reflect.String:
			str := field.String()
			// The builder writes: uvarint(len) + bytes
			// We just search for the bytes to be safe, as uvarint might overlap with other data
			search = []byte(str)
			valStr = str
		case reflect.Slice:
			if field.Type().Elem().Kind() == reflect.Uint8 {
				b := field.Bytes()
				search = b
				valStr = string(b)
			} else if field.Type().Elem().Kind() == reflect.String {
				s := field.Interface().([]string)
				for _, item := range s {
					if !bytes.Contains(canon, []byte(item)) {
						t.Errorf("Field %s item (%s) missing from canonical bytes", fieldName, item)
					}
				}
				continue
			}
		case reflect.Uint64:
			u := field.Uint()
			var tmp [10]byte
			n := binary.PutUvarint(tmp[:], u)
			search = tmp[:n]
			valStr = fmt.Sprintf("%d", u)
		case reflect.Int32:
			// cast to uint64 for uvarint encoding in canonWriter
			u := uint64(field.Int())
			var tmp [10]byte
			n := binary.PutUvarint(tmp[:], u)
			search = tmp[:n]
			valStr = fmt.Sprintf("%d", u)
		case reflect.Uint32:
			u := uint64(field.Uint())
			var tmp [10]byte
			n := binary.PutUvarint(tmp[:], u)
			search = tmp[:n]
			valStr = fmt.Sprintf("%d", u)
		}

		if len(search) > 0 {
			if !bytes.Contains(canon, search) {
				t.Errorf("Field %s (%s) missing from canonical bytes. If this is intentional, add it to excluded fields in verifyCanon call.", fieldName, valStr)
			}
		}
	}
}

func TestCanonicalSerializationCompleteness(t *testing.T) {
	tests := []struct {
		name string
		obj  interface{}
		fn   func(interface{}) []byte
	}{
		{
			name: "MsgPost",
			obj:  &coretypes.MsgPost{},
			fn:   func(v interface{}) []byte { return buildCanonForPost(v.(*coretypes.MsgPost)) },
		},
		{
			name: "MsgVote",
			obj:  &coretypes.MsgVote{},
			fn:   func(v interface{}) []byte { return buildCanonForVote(v.(*coretypes.MsgVote)) },
		},
		{
			name: "MsgSetUsername",
			obj:  &coretypes.MsgSetUsername{},
			fn:   func(v interface{}) []byte { return buildCanonForSetUsername(v.(*coretypes.MsgSetUsername)) },
		},
		{
			name: "MsgDelete",
			obj:  &coretypes.MsgDelete{},
			fn:   func(v interface{}) []byte { return buildCanonForDelete(v.(*coretypes.MsgDelete)) },
		},
		{
			name: "MsgSendTokens",
			obj:  &coretypes.MsgSendTokens{},
			fn:   func(v interface{}) []byte { return buildCanonForSendTokens(v.(*coretypes.MsgSendTokens)) },
		},
		{
			name: "MsgBridgeBurn",
			obj:  &coretypes.MsgBridgeBurn{},
			fn:   func(v interface{}) []byte { return buildCanonForBridgeBurn(v.(*coretypes.MsgBridgeBurn)) },
		},
		{
			name: "MsgAward",
			obj:  &coretypes.MsgAward{},
			fn:   func(v interface{}) []byte { return buildCanonForAward(v.(*coretypes.MsgAward)) },
		},
		{
			name: "MsgFollowModerator",
			obj:  &coretypes.MsgFollowModerator{},
			fn:   func(v interface{}) []byte { return buildCanonForFollowModerator(v.(*coretypes.MsgFollowModerator)) },
		},
		{
			name: "MsgUnfollowModerator",
			obj:  &coretypes.MsgUnfollowModerator{},
			fn:   func(v interface{}) []byte { return buildCanonForUnfollowModerator(v.(*coretypes.MsgUnfollowModerator)) },
		},
		{
			name: "MsgFollowUser",
			obj:  &coretypes.MsgFollowUser{},
			fn:   func(v interface{}) []byte { return buildCanonForFollowUser(v.(*coretypes.MsgFollowUser)) },
		},
		{
			name: "MsgUnfollowUser",
			obj:  &coretypes.MsgUnfollowUser{},
			fn:   func(v interface{}) []byte { return buildCanonForUnfollowUser(v.(*coretypes.MsgUnfollowUser)) },
		},
		{
			name: "MsgFollowTopic",
			obj:  &coretypes.MsgFollowTopic{},
			fn:   func(v interface{}) []byte { return buildCanonForFollowTopic(v.(*coretypes.MsgFollowTopic)) },
		},
		{
			name: "MsgUnfollowTopic",
			obj:  &coretypes.MsgUnfollowTopic{},
			fn:   func(v interface{}) []byte { return buildCanonForUnfollowTopic(v.(*coretypes.MsgUnfollowTopic)) },
		},
		{
			name: "MsgBlockPost",
			obj:  &coretypes.MsgBlockPost{},
			fn:   func(v interface{}) []byte { return buildCanonForBlockPost(v.(*coretypes.MsgBlockPost)) },
		},
		{
			name: "MsgUnblockPost",
			obj:  &coretypes.MsgUnblockPost{},
			fn:   func(v interface{}) []byte { return buildCanonForUnblockPost(v.(*coretypes.MsgUnblockPost)) },
		},
		{
			name: "MsgBlockUser",
			obj:  &coretypes.MsgBlockUser{},
			fn:   func(v interface{}) []byte { return buildCanonForBlockUser(v.(*coretypes.MsgBlockUser)) },
		},
		{
			name: "MsgUnblockUser",
			obj:  &coretypes.MsgUnblockUser{},
			fn:   func(v interface{}) []byte { return buildCanonForUnblockUser(v.(*coretypes.MsgUnblockUser)) },
		},
		{
			name: "MsgBlockTopic",
			obj:  &coretypes.MsgBlockTopic{},
			fn:   func(v interface{}) []byte { return buildCanonForBlockTopic(v.(*coretypes.MsgBlockTopic)) },
		},
		{
			name: "MsgUnblockTopic",
			obj:  &coretypes.MsgUnblockTopic{},
			fn:   func(v interface{}) []byte { return buildCanonForUnblockTopic(v.(*coretypes.MsgUnblockTopic)) },
		},
		{
			name: "MsgEdit",
			obj:  &coretypes.MsgEdit{},
			fn:   func(v interface{}) []byte { return buildCanonForEdit(v.(*coretypes.MsgEdit)) },
		},
		{
			name: "MsgUpgradeLevel",
			obj:  &coretypes.MsgUpgradeLevel{},
			fn:   func(v interface{}) []byte { return buildCanonForUpgradeLevel(v.(*coretypes.MsgUpgradeLevel)) },
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			populateFields(t, tc.obj)
			canon := tc.fn(tc.obj)
			verifyCanon(t, tc.obj, canon)
		})
	}
}
