package keeper

import (
	"bytes"
	"testing"

	sdkmath "cosmossdk.io/math"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/stretchr/testify/require"
)

// testValoper returns a valid bech32 valoper address based on a seed byte.
func testValoper(seed byte) string {
	return sdk.ValAddress(bytes.Repeat([]byte{seed}, 20)).String()
}

func TestBuildMintRecipients_AllValid(t *testing.T) {
	addrs := []string{testValoper(0x01), testValoper(0x02), testValoper(0x03)}
	amounts := []sdkmath.Int{sdkmath.NewInt(10), sdkmath.NewInt(20), sdkmath.NewInt(30)}

	recipients, skipped, totalMint, mismatch := buildMintRecipients(addrs, amounts)
	require.False(t, mismatch)
	require.Empty(t, skipped)
	require.Len(t, recipients, 3)
	require.Equal(t, sdkmath.NewInt(60), totalMint)
	valAddr, err := sdk.ValAddressFromBech32(addrs[0])
	require.NoError(t, err)
	require.Equal(t, sdk.AccAddress(valAddr), recipients[0].accountAddress)
	require.Equal(t, sdkmath.NewInt(20), recipients[1].amount)
}

// TestBuildMintRecipients_SkipsZeroAmount verifies that recipients with a
// zero (or non-positive) reward are silently dropped without affecting
// totalMint and without being flagged as "invalid address", even when the
// address string itself is malformed — their row is skipped before the
// bech32 parse runs.
func TestBuildMintRecipients_SkipsZeroAmount(t *testing.T) {
	addrs := []string{testValoper(0x01), "not-a-real-address", testValoper(0x03)}
	amounts := []sdkmath.Int{sdkmath.NewInt(10), sdkmath.ZeroInt(), sdkmath.NewInt(30)}

	recipients, skipped, totalMint, mismatch := buildMintRecipients(addrs, amounts)
	require.False(t, mismatch)
	require.Empty(t, skipped)
	require.Len(t, recipients, 2)
	require.Equal(t, sdkmath.NewInt(40), totalMint)
}

func TestBuildMintRecipients_SkipsInvalidAddress(t *testing.T) {
	addrs := []string{testValoper(0x01), "not-a-real-address", testValoper(0x03)}
	amounts := []sdkmath.Int{sdkmath.NewInt(10), sdkmath.NewInt(20), sdkmath.NewInt(30)}

	recipients, skipped, totalMint, mismatch := buildMintRecipients(addrs, amounts)
	require.False(t, mismatch)
	require.Equal(t, []string{"not-a-real-address"}, skipped)
	require.Len(t, recipients, 2)
	require.Equal(t, sdkmath.NewInt(40), totalMint)
}

func TestBuildMintRecipients_LengthMismatchReturnsFlagNoPanic(t *testing.T) {
	recipients, skipped, totalMint, mismatch := buildMintRecipients(
		[]string{testValoper(0x01)},
		[]sdkmath.Int{sdkmath.NewInt(1), sdkmath.NewInt(2)},
	)
	require.True(t, mismatch, "mismatch flag must be set on length mismatch")
	require.Nil(t, recipients)
	require.Nil(t, skipped)
	require.True(t, totalMint.IsZero())
}

func TestBuildMintRecipients_EmptyInputs(t *testing.T) {
	recipients, skipped, totalMint, mismatch := buildMintRecipients(nil, nil)
	require.False(t, mismatch)
	require.Empty(t, recipients)
	require.Empty(t, skipped)
	require.True(t, totalMint.IsZero())
}

func TestBuildMintRecipients_AllInvalid(t *testing.T) {
	addrs := []string{"bad1", "bad2"}
	amounts := []sdkmath.Int{sdkmath.NewInt(10), sdkmath.NewInt(20)}

	recipients, skipped, totalMint, mismatch := buildMintRecipients(addrs, amounts)
	require.False(t, mismatch)
	require.Empty(t, recipients)
	require.Equal(t, []string{"bad1", "bad2"}, skipped)
	require.True(t, totalMint.IsZero())
}
