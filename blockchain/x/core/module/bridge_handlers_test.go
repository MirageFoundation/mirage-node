package core

import (
	"bytes"
	"fmt"
	"testing"

	sdkmath "cosmossdk.io/math"
	sdk "github.com/cosmos/cosmos-sdk/types"

	"mirage/x/core/types"
)

type bridgeMockKeeper struct {
	params            types.Params
	balances          map[string]uint64
	moduleBalance     uint64
	sequences         map[string]uint64
	burnRecords       map[string]*types.BridgeBurnRecord
	mintedRecords     map[string]*types.BridgeMintedRecord
	attestations      map[string]*types.BridgeAttestation
	mintAttestations  map[string]*types.BridgeMintAttestation
	bondedValidators  map[string]bool
	validatorPowers   map[string]int64
	totalPower        int64
	pendingCount      int64
}

func newBridgeMockKeeper(params types.Params) *bridgeMockKeeper {
	return &bridgeMockKeeper{
		params:           params,
		balances:         make(map[string]uint64),
		sequences:        make(map[string]uint64),
		burnRecords:      make(map[string]*types.BridgeBurnRecord),
		mintedRecords:    make(map[string]*types.BridgeMintedRecord),
		attestations:     make(map[string]*types.BridgeAttestation),
		mintAttestations: make(map[string]*types.BridgeMintAttestation),
		bondedValidators: make(map[string]bool),
		validatorPowers:  make(map[string]int64),
	}
}

func (mk *bridgeMockKeeper) GetParams(ctx sdk.Context) types.Params {
	return mk.params
}

func (mk *bridgeMockKeeper) GetProfileCore(ctx sdk.Context, addr string) ([]byte, bool, error) {
	return nil, false, nil
}

func (mk *bridgeMockKeeper) GetBalance(ctx sdk.Context, owner string, denom string) sdkmath.Int {
	return sdkmath.NewIntFromUint64(mk.balances[owner])
}

func (mk *bridgeMockKeeper) BurnFromAccount(ctx sdk.Context, addr string, amount uint64) error {
	bal := mk.balances[addr]
	if bal < amount {
		return fmt.Errorf("insufficient balance")
	}
	mk.balances[addr] = bal - amount
	return nil
}

func (mk *bridgeMockKeeper) SendToModule(ctx sdk.Context, from string, amount uint64) error {
	bal := mk.balances[from]
	if bal < amount {
		return fmt.Errorf("insufficient balance")
	}
	mk.balances[from] = bal - amount
	mk.moduleBalance += amount
	return nil
}

func (mk *bridgeMockKeeper) SendFromModule(ctx sdk.Context, to string, amount uint64) error {
	if mk.moduleBalance < amount {
		return fmt.Errorf("insufficient module balance")
	}
	mk.moduleBalance -= amount
	mk.balances[to] += amount
	return nil
}

func (mk *bridgeMockKeeper) GetNextBridgeSequence(ctx sdk.Context, destChain string) (uint64, error) {
	mk.sequences[destChain]++
	return mk.sequences[destChain], nil
}

func (mk *bridgeMockKeeper) GetCurrentBridgeSequence(ctx sdk.Context, destChain string) (uint64, error) {
	return mk.sequences[destChain], nil
}

func (mk *bridgeMockKeeper) SetBridgeBurnRecord(ctx sdk.Context, record *types.BridgeBurnRecord) error {
	key := fmt.Sprintf("%s/%s", record.DestinationChain, record.BurnID)
	mk.burnRecords[key] = record
	return nil
}

func (mk *bridgeMockKeeper) GetBridgeBurnRecord(ctx sdk.Context, destChain, burnID string) (*types.BridgeBurnRecord, bool, error) {
	key := fmt.Sprintf("%s/%s", destChain, burnID)
	record, found := mk.burnRecords[key]
	return record, found, nil
}

func (mk *bridgeMockKeeper) GetOrCreateBridgeAttestation(ctx sdk.Context, sourceChain, burnID, mirageRecipient string, amount uint64) (*types.BridgeAttestation, error) {
	key := fmt.Sprintf("%s/%s", sourceChain, burnID)
	if att, found := mk.attestations[key]; found {
		return att, nil
	}
	att := types.NewBridgeAttestation(sourceChain, burnID, mirageRecipient, amount, ctx.BlockHeight())
	mk.attestations[key] = att
	mk.pendingCount++
	return att, nil
}

func (mk *bridgeMockKeeper) SetBridgeAttestation(ctx sdk.Context, attestation *types.BridgeAttestation) error {
	key := fmt.Sprintf("%s/%s", attestation.SourceChain, attestation.BurnID)
	mk.attestations[key] = attestation
	return nil
}

func (mk *bridgeMockKeeper) GetOrCreateBridgeMintAttestation(ctx sdk.Context, burnID, destChain, destTx string) (*types.BridgeMintAttestation, error) {
	key := fmt.Sprintf("%s/%s", destChain, burnID)
	if att, found := mk.mintAttestations[key]; found {
		return att, nil
	}
	att := types.NewBridgeMintAttestation(burnID, destChain, destTx, ctx.BlockHeight())
	mk.mintAttestations[key] = att
	return att, nil
}

func (mk *bridgeMockKeeper) SetBridgeMintAttestation(ctx sdk.Context, attestation *types.BridgeMintAttestation) error {
	key := fmt.Sprintf("%s/%s", attestation.DestinationChain, attestation.BurnID)
	mk.mintAttestations[key] = attestation
	return nil
}

func (mk *bridgeMockKeeper) SetBridgeMintedRecord(ctx sdk.Context, record *types.BridgeMintedRecord) error {
	key := fmt.Sprintf("%s/%s", record.DestinationChain, record.BurnID)
	mk.mintedRecords[key] = record
	return nil
}

func (mk *bridgeMockKeeper) GetTotalBondedValidatorPower(ctx sdk.Context) (int64, error) {
	if mk.totalPower > 0 {
		return mk.totalPower, nil
	}
	var total int64
	for _, power := range mk.validatorPowers {
		total += power
	}
	return total, nil
}

func (mk *bridgeMockKeeper) GetValidatorPower(ctx sdk.Context, valoper string) (int64, error) {
	power, ok := mk.validatorPowers[valoper]
	if !ok {
		return 0, fmt.Errorf("validator not found")
	}
	return power, nil
}

func (mk *bridgeMockKeeper) IsValidatorBonded(ctx sdk.Context, valoper string) (bool, error) {
	return mk.bondedValidators[valoper], nil
}

func (mk *bridgeMockKeeper) MintToAccount(ctx sdk.Context, recipient string, amount uint64) error {
	mk.balances[recipient] += amount
	return nil
}

func (mk *bridgeMockKeeper) DecrementBridgePendingCount(ctx sdk.Context) error {
	if mk.pendingCount > 0 {
		mk.pendingCount--
	}
	return nil
}

func testBridgeParams(chain string, fee uint64) types.Params {
	params := types.DefaultParams()
	params.BridgeChains = []*types.BridgeChainConfig{
		{
			ChainId:  chain,
			Enabled:  true,
			Fee:      fee,
			IbcChannel: "",
		},
	}
	return params
}

func TestBridgeBurnHandlerHappyPath(t *testing.T) {
	ctx := newMockContext()
	params := testBridgeParams("solana", 10)
	mk := newBridgeMockKeeper(params)

	envelopePubkey := bytes.Repeat([]byte{0x02}, 33)
	owner, err := deriveOwnerFromPubkey(envelopePubkey)
	if err != nil {
		t.Fatalf("deriveOwnerFromPubkey error: %v", err)
	}
	mk.balances[owner] = 1000

	req := &types.MsgBridgeBurn{
		EnvelopePubkey:     envelopePubkey,
		DestinationChain:   "solana",
		DestinationAddress: "7EYnhQoR9YM3N7UoaKRoA44Uy8JeaZV3qyouov87awMs",
		Amount:             100,
	}

	resp, err := bridgeBurn(ctx, mk, req, func(_ sdk.Context, _ string, _ int) error { return nil })
	if err != nil {
		t.Fatalf("bridgeBurn error: %v", err)
	}
	if resp.BurnId != 1 {
		t.Fatalf("BurnId = %d, want 1", resp.BurnId)
	}
	if mk.balances[owner] != 900 {
		t.Fatalf("owner balance = %d, want 900", mk.balances[owner])
	}
	if mk.moduleBalance != 10 {
		t.Fatalf("module balance = %d, want 10", mk.moduleBalance)
	}
	record, found := mk.burnRecords["solana/1"]
	if !found {
		t.Fatal("expected burn record to be stored")
	}
	if record.BridgeFee != 10 || record.Amount != 100 {
		t.Fatalf("burn record mismatch: fee=%d amount=%d", record.BridgeFee, record.Amount)
	}
}

func TestBridgeAttestBurnedHandlerThreshold(t *testing.T) {
	ctx := newMockContext()
	params := testBridgeParams("solana", 0)
	mk := newBridgeMockKeeper(params)

	validator := testAccAddressString()
	valoper := testValoperAddressString()
	mk.bondedValidators[valoper] = true
	mk.validatorPowers[valoper] = 70
	mk.totalPower = 100

	recipient := testAccAddressString()
	req := &types.MsgBridgeAttestBurned{
		Validator:        validator,
		SourceChain:      "solana",
		BurnId:           "burn123",
		MirageRecipient:  recipient,
		Amount:           1000,
	}

	resp, err := bridgeAttestBurned(ctx, mk, req)
	if err != nil {
		t.Fatalf("bridgeAttestBurned error: %v", err)
	}
	if !resp.Confirmed {
		t.Fatal("expected attestation to be confirmed")
	}
	if resp.AttestedPower != 70 {
		t.Fatalf("AttestedPower = %d, want 70", resp.AttestedPower)
	}
	required := types.RequiredPower(100, params.BridgeAttestationThreshold)
	if resp.RequiredPower != required {
		t.Fatalf("RequiredPower = %d, want %d", resp.RequiredPower, required)
	}
	if mk.balances[recipient] != 1000 {
		t.Fatalf("recipient balance = %d, want 1000", mk.balances[recipient])
	}
}

func TestBridgeAttestBurnedHandlerDuplicate(t *testing.T) {
	ctx := newMockContext()
	params := testBridgeParams("solana", 0)
	mk := newBridgeMockKeeper(params)

	validator := testAccAddressString()
	valoper := testValoperAddressString()
	mk.bondedValidators[valoper] = true
	mk.validatorPowers[valoper] = 30
	mk.totalPower = 100

	recipient := testAccAddressString()
	req := &types.MsgBridgeAttestBurned{
		Validator:       validator,
		SourceChain:     "solana",
		BurnId:          "burn456",
		MirageRecipient: recipient,
		Amount:          500,
	}

	resp, err := bridgeAttestBurned(ctx, mk, req)
	if err != nil {
		t.Fatalf("bridgeAttestBurned error: %v", err)
	}
	if resp.Confirmed {
		t.Fatal("expected attestation to not be confirmed")
	}
	if resp.AttestedPower != 30 {
		t.Fatalf("AttestedPower = %d, want 30", resp.AttestedPower)
	}

	resp, err = bridgeAttestBurned(ctx, mk, req)
	if err != nil {
		t.Fatalf("bridgeAttestBurned duplicate error: %v", err)
	}
	if resp.AttestedPower != 30 {
		t.Fatalf("duplicate AttestedPower = %d, want 30", resp.AttestedPower)
	}
}

func TestBridgeAttestMintedHandlerHappyPath(t *testing.T) {
	ctx := newMockContext()
	params := testBridgeParams("solana", 0)
	mk := newBridgeMockKeeper(params)

	mk.sequences["solana"] = 1
	mk.moduleBalance = 100
	mk.burnRecords["solana/1"] = &types.BridgeBurnRecord{
		BurnID:           "1",
		DestinationChain: "solana",
		BridgeFee:        100,
	}

	validator := testAccAddressString()
	valoper := testValoperAddressString()
	mk.bondedValidators[valoper] = true
	mk.validatorPowers[valoper] = 70
	mk.totalPower = 100

	req := &types.MsgBridgeAttestMinted{
		Validator:        validator,
		BurnId:           "1",
		DestinationChain: "solana",
		DestinationTx:    "sig123",
		MirageTxHash:     "miragehash",
	}

	resp, err := bridgeAttestMinted(ctx, mk, req)
	if err != nil {
		t.Fatalf("bridgeAttestMinted error: %v", err)
	}
	if !resp.Confirmed {
		t.Fatal("expected mint attestation to be confirmed")
	}
	if _, found := mk.mintedRecords["solana/1"]; !found {
		t.Fatal("expected mint record to be stored")
	}
	if mk.moduleBalance != 0 {
		t.Fatalf("module balance = %d, want 0", mk.moduleBalance)
	}
	if mk.balances[validator] != 100 {
		t.Fatalf("validator balance = %d, want 100", mk.balances[validator])
	}
}

func TestBridgeAttestMintedCanonicalDestinationTx(t *testing.T) {
	ctx := newMockContext()
	params := testBridgeParams("solana", 0)
	mk := newBridgeMockKeeper(params)

	mk.sequences["solana"] = 1
	mk.burnRecords["solana/1"] = &types.BridgeBurnRecord{
		BurnID:           "1",
		DestinationChain: "solana",
		BridgeFee:        0,
	}

	validator1 := testAccAddressString()
	valoper1 := testValoperAddressString()

	validator2 := sdk.AccAddress(bytes.Repeat([]byte{0x02}, 20)).String()
	valoper2 := sdk.ValAddress(bytes.Repeat([]byte{0x02}, 20)).String()

	mk.bondedValidators[valoper1] = true
	mk.bondedValidators[valoper2] = true
	mk.validatorPowers[valoper1] = 40
	mk.validatorPowers[valoper2] = 40
	mk.totalPower = 100

	req1 := &types.MsgBridgeAttestMinted{
		Validator:        validator1,
		BurnId:           "1",
		DestinationChain: "solana",
		DestinationTx:    "sig-first",
		MirageTxHash:     "miragehash",
	}
	resp, err := bridgeAttestMinted(ctx, mk, req1)
	if err != nil {
		t.Fatalf("bridgeAttestMinted first error: %v", err)
	}
	if resp.Confirmed {
		t.Fatal("expected first attestation to be unconfirmed")
	}

	req2 := &types.MsgBridgeAttestMinted{
		Validator:        validator2,
		BurnId:           "1",
		DestinationChain: "solana",
		DestinationTx:    "sig-second",
		MirageTxHash:     "miragehash",
	}
	resp, err = bridgeAttestMinted(ctx, mk, req2)
	if err != nil {
		t.Fatalf("bridgeAttestMinted second error: %v", err)
	}
	if !resp.Confirmed {
		t.Fatal("expected second attestation to confirm mint")
	}

	record, found := mk.mintedRecords["solana/1"]
	if !found {
		t.Fatal("expected mint record to be stored")
	}
	if record.DestinationTx != "sig-first" {
		t.Fatalf("DestinationTx = %s, want sig-first", record.DestinationTx)
	}
}
