package app

import (
	sdk "github.com/cosmos/cosmos-sdk/types"
)

// Legacy no-op: posts module removed, and decoder bypass disabled.
// Kept only to avoid import churn.

// unsignedOkTx wraps an sdk.Tx and bypasses ValidateBasic.
// Deprecated: not used.
type unsignedOkTx struct{ sdk.Tx }

func (u unsignedOkTx) ValidateBasic() error { return nil }
