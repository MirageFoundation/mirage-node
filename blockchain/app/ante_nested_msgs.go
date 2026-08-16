package app

import (
	"fmt"

	sdk "github.com/cosmos/cosmos-sdk/types"
)

// maxMsgNestingDepth bounds the transitive walk so a deeply nested wrapper
// chain cannot turn ante classification into unbounded work.
const maxMsgNestingDepth = 4

// nestedMsgCarrier is any message that carries other messages inside itself and
// dispatches them through the message router directly, so the inner messages
// never pass an ante handler. authz.MsgExec is the shape this exists for.
//
// Matched structurally rather than by concrete type: a wrapper added in a future
// SDK version is covered the day it is wired rather than the day someone
// remembers this file exists.
type nestedMsgCarrier interface {
	GetMessages() ([]sdk.Msg, error)
}

// nestedMsgs returns every message carried *below* the top level of a
// transaction, recursively. The top-level messages themselves are not included.
func nestedMsgs(msgs []sdk.Msg, depth int) ([]sdk.Msg, error) {
	if depth > maxMsgNestingDepth {
		return nil, fmt.Errorf("message nesting exceeds the maximum depth of %d", maxMsgNestingDepth)
	}
	var out []sdk.Msg
	for _, m := range msgs {
		carrier, ok := m.(nestedMsgCarrier)
		if !ok {
			continue
		}
		inner, err := carrier.GetMessages()
		if err != nil {
			return nil, fmt.Errorf("cannot inspect messages nested in %s: %w", sdk.MsgTypeURL(m), err)
		}
		out = append(out, inner...)
		deeper, err := nestedMsgs(inner, depth+1)
		if err != nil {
			return nil, err
		}
		out = append(out, deeper...)
	}
	return out, nil
}

// transitiveMsgs returns the full message set a transaction will actually
// execute: every top-level message plus everything nested inside a carrier.
//
// Every ante check that reasons about "which messages does this transaction
// run" must use this rather than tx.GetMsgs(), because a check that inspects
// only the top level can be stepped around by wrapping the real payload.
func transitiveMsgs(tx sdk.Tx) ([]sdk.Msg, error) {
	top := tx.GetMsgs()
	nested, err := nestedMsgs(top, 0)
	if err != nil {
		return nil, err
	}
	if len(nested) == 0 {
		return top, nil
	}
	out := make([]sdk.Msg, 0, len(top)+len(nested))
	out = append(out, top...)
	out = append(out, nested...)
	return out, nil
}
