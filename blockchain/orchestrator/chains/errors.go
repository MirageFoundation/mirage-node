package chains

import "errors"

var (
	ErrTransactionTooOld         = errors.New("transaction too old")
	ErrBridgeMintAlreadyRecorded = errors.New("bridge mint already recorded")
)
