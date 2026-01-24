package core

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"

	sdkmath "cosmossdk.io/math"
	sdk "github.com/cosmos/cosmos-sdk/types"

	"mirage/x/core/types"
)

type bridgeBurnKeeper interface {
	GetParams(ctx sdk.Context) types.Params
	GetProfileCore(ctx sdk.Context, addr string) ([]byte, bool, error)
	GetBalance(ctx sdk.Context, owner string, denom string) sdkmath.Int
	BurnFromAccount(ctx sdk.Context, addr string, amount uint64) error
	SendToModule(ctx sdk.Context, from string, amount uint64) error
	GetNextBridgeSequence(ctx sdk.Context, destChain string) (uint64, error)
	SetBridgeBurnRecord(ctx sdk.Context, record *types.BridgeBurnRecord) error
}

type bridgeAttestBurnedKeeper interface {
	GetParams(ctx sdk.Context) types.Params
	IsValidatorBonded(ctx sdk.Context, valoper string) (bool, error)
	GetValidatorPower(ctx sdk.Context, valoper string) (int64, error)
	GetOrCreateBridgeAttestation(ctx sdk.Context, sourceChain, burnID, mirageRecipient string, amount uint64) (*types.BridgeAttestation, error)
	HasBridgeAttestor(ctx sdk.Context, sourceChain, burnID, valoper string) (bool, error)
	SetBridgeAttestor(ctx sdk.Context, sourceChain, burnID, valoper string, power int64) error
	GetTotalBondedValidatorPower(ctx sdk.Context) (int64, error)
	SetBridgeAttestation(ctx sdk.Context, attestation *types.BridgeAttestation) error
	MintToAccount(ctx sdk.Context, recipient string, amount uint64) error
	DecrementBridgePendingCount(ctx sdk.Context) error
}

type bridgeAttestMintedKeeper interface {
	GetParams(ctx sdk.Context) types.Params
	IsValidatorBonded(ctx sdk.Context, valoper string) (bool, error)
	GetValidatorPower(ctx sdk.Context, valoper string) (int64, error)
	GetCurrentBridgeSequence(ctx sdk.Context, destChain string) (uint64, error)
	GetBridgeBurnRecord(ctx sdk.Context, destChain, burnID string) (*types.BridgeBurnRecord, bool, error)
	GetOrCreateBridgeMintAttestation(ctx sdk.Context, burnID, destChain, destTx string) (*types.BridgeMintAttestation, error)
	HasBridgeMintAttestor(ctx sdk.Context, destChain, burnID, valoper string) (bool, error)
	SetBridgeMintAttestor(ctx sdk.Context, destChain, burnID, valoper string, power int64) error
	SetBridgeMintAttestation(ctx sdk.Context, attestation *types.BridgeMintAttestation) error
	SetBridgeMintedRecord(ctx sdk.Context, record *types.BridgeMintedRecord) error
	BurnFromModuleExact(ctx sdk.Context, amount uint64) error
	GetTotalBondedValidatorPower(ctx sdk.Context) (int64, error)
}

func bridgeBurn(ctx sdk.Context, k bridgeBurnKeeper, req *types.MsgBridgeBurn, deductRelayGasFee func(ctx sdk.Context, owner string, userLevel int) error) (*types.MsgBridgeBurnResponse, error) {
	params := k.GetParams(ctx)

	// Derive owner from envelope_pubkey
	if len(req.GetEnvelopePubkey()) != 33 {
		return nil, fmt.Errorf("invalid envelope_pubkey length")
	}
	owner, err := deriveOwnerFromPubkey(req.GetEnvelopePubkey())
	if err != nil {
		return nil, err
	}

	// Get user level for gas fee
	var userLevel int
	if bz, found, _ := k.GetProfileCore(ctx, owner); found {
		var core types.ProfileCore
		_ = json.Unmarshal(bz, &core)
		userLevel = int(core.Level)
	}

	// Validate amount
	amount := req.GetAmount()
	if amount == 0 {
		return nil, fmt.Errorf("amount must be > 0")
	}

	// Validate destination chain (must be in bridge_chains and enabled)
	destChain := strings.TrimSpace(req.GetDestinationChain())
	chainConfig, err := types.ValidateBridgeChain(destChain, params.BridgeChains)
	if err != nil {
		return nil, err
	}

	// Get bridge fee from chain config (per-chain fee)
	bridgeFee := chainConfig.Fee
	if bridgeFee >= amount {
		return nil, fmt.Errorf("amount must be greater than bridge fee")
	}
	burnAmount := amount - bridgeFee
	totalSpend := amount

	// Check balance
	balance := k.GetBalance(ctx, owner, types.MintDenom)
	if balance.LT(sdkmath.NewIntFromUint64(totalSpend)) {
		return nil, fmt.Errorf("insufficient balance: need %d (amount includes fee %d), have %s",
			totalSpend, bridgeFee, balance.String())
	}

	// Validate destination address format for the target chain
	destAddr := strings.TrimSpace(req.GetDestinationAddress())
	if err := types.ValidateBridgeDestinationAddress(destChain, destAddr); err != nil {
		return nil, err
	}

	// Get next sequence for this destination
	sequence, err := k.GetNextBridgeSequence(ctx, destChain)
	if err != nil {
		return nil, fmt.Errorf("failed to get next sequence: %w", err)
	}

	ctx.Logger().Debug("BridgeBurn amounts",
		"amount", amount,
		"bridge_fee", bridgeFee,
		"burn_amount", burnAmount,
	)

	// Burn the net amount (gross amount minus fee)
	if err := k.BurnFromAccount(ctx, owner, burnAmount); err != nil {
		return nil, fmt.Errorf("failed to burn tokens: %w", err)
	}

	// Escrow the bridge fee in the core module account (burned when mint is confirmed)
	if bridgeFee > 0 {
		if err := k.SendToModule(ctx, owner, bridgeFee); err != nil {
			return nil, fmt.Errorf("failed to escrow bridge fee: %w", err)
		}
	}

	// Persist burn record for fee burning and auditing
	burnIDStr := fmt.Sprintf("%d", sequence)
	record := &types.BridgeBurnRecord{
		BurnID:             burnIDStr,
		Owner:              owner,
		DestinationChain:   destChain,
		DestinationAddress: destAddr,
		Amount:             amount,
		BridgeFee:          bridgeFee,
		Sequence:           sequence,
		CreatedAt:          ctx.BlockHeight(),
	}
	if err := k.SetBridgeBurnRecord(ctx, record); err != nil {
		return nil, fmt.Errorf("failed to store bridge burn record: %w", err)
	}

	// Deduct relay gas fee
	if err := deductRelayGasFee(ctx, owner, userLevel); err != nil {
		return nil, err
	}

	// Emit event for orchestrators to pick up
	// NOTE: We persist a burn record for fee burning; attestations track confirmation.
	ctx.EventManager().EmitEvent(
		buildBridgeBurnEvent(owner, destChain, destAddr, amount, bridgeFee, sequence),
	)

	ctx.Logger().Info("BridgeBurn",
		"burn_id", sequence,
		"sender", owner,
		"destination_chain", destChain,
		"destination_address", destAddr,
		"amount", amount,
		"bridge_fee", bridgeFee,
	)

	// Return sequence as burn_id (orchestrators use this to attest)
	return &types.MsgBridgeBurnResponse{BurnId: sequence}, nil
}

func bridgeAttestBurned(ctx sdk.Context, k bridgeAttestBurnedKeeper, req *types.MsgBridgeAttestBurned) (*types.MsgBridgeAttestBurnedResponse, error) {
	params := k.GetParams(ctx)

	// Validate signer is a bonded validator
	signer := strings.TrimSpace(req.GetValidator())
	if signer == "" {
		return nil, fmt.Errorf("validator cannot be empty")
	}

	signerAcc, err := sdk.AccAddressFromBech32(signer)
	if err != nil {
		return nil, fmt.Errorf("invalid validator address: %w", err)
	}
	valoper := sdk.ValAddress(signerAcc).String()
	ctx.Logger().Debug("BridgeAttest signer resolved", "signer", signer, "valoper", valoper)

	bonded, err := k.IsValidatorBonded(ctx, valoper)
	if err != nil {
		return nil, fmt.Errorf("failed to check validator status: %w", err)
	}
	if !bonded {
		return nil, fmt.Errorf("validator %s is not bonded", valoper)
	}

	// Get validator's voting power
	valPower, err := k.GetValidatorPower(ctx, valoper)
	if err != nil {
		return nil, fmt.Errorf("failed to get validator power: %w", err)
	}

	// Validate source chain (must be in bridge_chains and enabled)
	sourceChain := strings.TrimSpace(req.GetSourceChain())
	if _, err := types.ValidateBridgeChain(sourceChain, params.BridgeChains); err != nil {
		return nil, err
	}

	// Validate burn_id
	burnID := strings.TrimSpace(req.GetBurnId())
	if burnID == "" {
		return nil, fmt.Errorf("burn_id cannot be empty")
	}
	// Basic sanity limits (avoid store key weirdness / accidental DoS)
	if len(burnID) > 128 {
		return nil, fmt.Errorf("burn_id too long")
	}
	if strings.Contains(burnID, "/") {
		return nil, fmt.Errorf("burn_id contains invalid character: /")
	}

	// Validate recipient
	mirageRecipient := strings.TrimSpace(req.GetMirageRecipient())
	if err := validateAddress(mirageRecipient); err != nil {
		return nil, fmt.Errorf("invalid mirage_recipient: %w", err)
	}

	// Validate amount
	amount := req.GetAmount()
	if amount == 0 {
		return nil, fmt.Errorf("amount must be > 0")
	}

	// Get or create attestation
	attestation, err := k.GetOrCreateBridgeAttestation(ctx, sourceChain, burnID, mirageRecipient, amount)
	if err != nil {
		return nil, fmt.Errorf("failed to get/create attestation: %w", err)
	}

	// Verify attestation details match
	if attestation.MirageRecipient != mirageRecipient {
		return nil, fmt.Errorf("recipient mismatch: existing %s, provided %s", attestation.MirageRecipient, mirageRecipient)
	}
	if attestation.Amount != amount {
		return nil, fmt.Errorf("amount mismatch: existing %d, provided %d", attestation.Amount, amount)
	}

	// Check if already confirmed (minted)
	if attestation.Minted {
		totalPower, _ := k.GetTotalBondedValidatorPower(ctx)
		requiredPower := types.RequiredPower(totalPower, params.BridgeAttestationThreshold)

		// Emit event even for late attestations so indexers can track all participants
		ctx.EventManager().EmitEvent(
			sdk.NewEvent(
				"bridge_attest",
				sdk.NewAttribute("validator", valoper),
				sdk.NewAttribute("source_chain", sourceChain),
				sdk.NewAttribute("burn_id", burnID),
				sdk.NewAttribute("power", fmt.Sprintf("%d", valPower)),
				sdk.NewAttribute("attested_power", fmt.Sprintf("%d", attestation.AttestedPower)),
				sdk.NewAttribute("required_power", fmt.Sprintf("%d", requiredPower)),
				sdk.NewAttribute("minted", "true"),
				sdk.NewAttribute("late", "true"),
			),
		)

		return &types.MsgBridgeAttestBurnedResponse{
			Confirmed:     true,
			AttestedPower: attestation.AttestedPower,
			RequiredPower: requiredPower,
		}, nil
	}

	// Check if validator already attested
	alreadyAttested, err := k.HasBridgeAttestor(ctx, sourceChain, burnID, valoper)
	if err != nil {
		return nil, fmt.Errorf("failed to check attestor: %w", err)
	}
	if alreadyAttested {
		totalPower, _ := k.GetTotalBondedValidatorPower(ctx)
		requiredPower := types.RequiredPower(totalPower, params.BridgeAttestationThreshold)

		// Emit event for duplicate attestation (idempotent - validator already recorded)
		ctx.EventManager().EmitEvent(
			sdk.NewEvent(
				"bridge_attest",
				sdk.NewAttribute("validator", valoper),
				sdk.NewAttribute("source_chain", sourceChain),
				sdk.NewAttribute("burn_id", burnID),
				sdk.NewAttribute("power", fmt.Sprintf("%d", valPower)),
				sdk.NewAttribute("attested_power", fmt.Sprintf("%d", attestation.AttestedPower)),
				sdk.NewAttribute("required_power", fmt.Sprintf("%d", requiredPower)),
				sdk.NewAttribute("minted", fmt.Sprintf("%t", attestation.Minted)),
				sdk.NewAttribute("duplicate", "true"),
			),
		)

		return &types.MsgBridgeAttestBurnedResponse{
			Confirmed:     attestation.Minted,
			AttestedPower: attestation.AttestedPower,
			RequiredPower: requiredPower,
		}, nil
	}

	// Add attestation (stored separately to avoid variable-size writes)
	if err := k.SetBridgeAttestor(ctx, sourceChain, burnID, valoper, valPower); err != nil {
		return nil, fmt.Errorf("failed to store attestor: %w", err)
	}
	attestation.AttestedPower += valPower

	// Check if threshold is met
	totalPower, err := k.GetTotalBondedValidatorPower(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to get total voting power: %w", err)
	}

	requiredPower := types.RequiredPower(totalPower, params.BridgeAttestationThreshold)
	minted := false

	if attestation.MeetsThreshold(totalPower, params.BridgeAttestationThreshold) {
		// Mint tokens to recipient
		if err := k.MintToAccount(ctx, mirageRecipient, amount); err != nil {
			return nil, fmt.Errorf("failed to mint tokens: %w", err)
		}

		attestation.Minted = true
		minted = true

		// Decrement pending count
		_ = k.DecrementBridgePendingCount(ctx)

		// Emit mint event
		ctx.EventManager().EmitEvent(
			sdk.NewEvent(
				"bridge_mint",
				sdk.NewAttribute("source_chain", sourceChain),
				sdk.NewAttribute("burn_id", burnID),
				sdk.NewAttribute("recipient", mirageRecipient),
				sdk.NewAttribute("amount", fmt.Sprintf("%d", amount)),
				sdk.NewAttribute("attested_power", fmt.Sprintf("%d", attestation.AttestedPower)),
				sdk.NewAttribute("required_power", fmt.Sprintf("%d", requiredPower)),
			),
		)

		ctx.Logger().Info("BridgeMint",
			"source_chain", sourceChain,
			"burn_id", burnID,
			"recipient", mirageRecipient,
			"amount", amount,
			"attested_power", attestation.AttestedPower,
		)
	}

	// Save attestation state
	if err := k.SetBridgeAttestation(ctx, attestation); err != nil {
		return nil, fmt.Errorf("failed to save attestation: %w", err)
	}

	// Emit attestation event
	ctx.EventManager().EmitEvent(
		sdk.NewEvent(
			"bridge_attest",
			sdk.NewAttribute("validator", valoper),
			sdk.NewAttribute("source_chain", sourceChain),
			sdk.NewAttribute("burn_id", burnID),
			sdk.NewAttribute("power", fmt.Sprintf("%d", valPower)),
			sdk.NewAttribute("attested_power", fmt.Sprintf("%d", attestation.AttestedPower)),
			sdk.NewAttribute("required_power", fmt.Sprintf("%d", requiredPower)),
			sdk.NewAttribute("minted", fmt.Sprintf("%t", minted)),
		),
	)

	ctx.Logger().Info("BridgeAttest",
		"validator", valoper,
		"signer", signer,
		"source_chain", sourceChain,
		"burn_id", burnID,
		"power", valPower,
		"attested_power", attestation.AttestedPower,
		"required_power", requiredPower,
		"minted", minted,
	)

	return &types.MsgBridgeAttestBurnedResponse{
		Confirmed:     minted,
		AttestedPower: attestation.AttestedPower,
		RequiredPower: requiredPower,
	}, nil
}

func bridgeAttestMinted(ctx sdk.Context, k bridgeAttestMintedKeeper, req *types.MsgBridgeAttestMinted) (*types.MsgBridgeAttestMintedResponse, error) {
	params := k.GetParams(ctx)

	validator := strings.TrimSpace(req.GetValidator())
	if validator == "" {
		return nil, fmt.Errorf("validator cannot be empty")
	}

	validatorAcc, err := sdk.AccAddressFromBech32(validator)
	if err != nil {
		return nil, fmt.Errorf("invalid validator address: %w", err)
	}
	valoper := sdk.ValAddress(validatorAcc).String()
	ctx.Logger().Debug("BridgeAttestMinted signer resolved", "signer", validator, "valoper", valoper)

	bonded, err := k.IsValidatorBonded(ctx, valoper)
	if err != nil {
		return nil, fmt.Errorf("failed to check validator status: %w", err)
	}
	if !bonded {
		return nil, fmt.Errorf("validator %s is not bonded", valoper)
	}

	// Get validator's voting power
	valPower, err := k.GetValidatorPower(ctx, valoper)
	if err != nil {
		return nil, fmt.Errorf("failed to get validator power: %w", err)
	}

	burnIDStr := strings.TrimSpace(req.GetBurnId())
	burnIDNum, err := strconv.ParseUint(burnIDStr, 10, 64)
	if err != nil {
		return nil, fmt.Errorf("invalid burn_id (must be numeric sequence): %w", err)
	}

	destChain := strings.TrimSpace(req.GetDestinationChain())
	if destChain == "" {
		return nil, fmt.Errorf("destination_chain cannot be empty")
	}
	if len(destChain) > 64 {
		return nil, fmt.Errorf("destination_chain too long")
	}

	destTx := strings.TrimSpace(req.GetDestinationTx())
	if destTx == "" {
		return nil, fmt.Errorf("destination_tx cannot be empty")
	}
	if len(destTx) > 128 {
		return nil, fmt.Errorf("destination_tx too long")
	}
	for _, c := range destTx {
		if c <= ' ' || c == '/' {
			return nil, fmt.Errorf("destination_tx contains invalid character")
		}
	}

	mirageTxHash := strings.TrimSpace(req.GetMirageTxHash())

	// Validate burn_id against burn_sequence counter
	// burn_id must be <= current sequence (0 means no burns yet)
	currentSeq, err := k.GetCurrentBridgeSequence(ctx, destChain)
	if err != nil {
		return nil, fmt.Errorf("failed to get current sequence: %w", err)
	}
	if burnIDNum == 0 || burnIDNum > currentSeq {
		return nil, fmt.Errorf("invalid burn_id: %d (current sequence: %d)", burnIDNum, currentSeq)
	}

	// Load burn record to verify it exists for this destination chain
	burnRecord, found, err := k.GetBridgeBurnRecord(ctx, destChain, burnIDStr)
	if err != nil {
		return nil, fmt.Errorf("failed to load bridge burn record: %w", err)
	}
	if !found {
		return nil, fmt.Errorf("bridge burn record not found for %s/%s", destChain, burnIDStr)
	}

	// Get or create mint attestation
	attestation, err := k.GetOrCreateBridgeMintAttestation(ctx, burnIDStr, destChain, destTx)
	if err != nil {
		return nil, fmt.Errorf("failed to get/create mint attestation: %w", err)
	}

	// Check if already confirmed
	if attestation.Confirmed {
		totalPower, _ := k.GetTotalBondedValidatorPower(ctx)
		requiredPower := types.RequiredPower(totalPower, params.BridgeAttestationThreshold)

		// Emit event even for late attestations so indexers can track all participants
		ctx.EventManager().EmitEvent(
			sdk.NewEvent(
				"bridge_attest_minted",
				sdk.NewAttribute("burn_id", burnIDStr),
				sdk.NewAttribute("destination_chain", destChain),
				sdk.NewAttribute("destination_tx", attestation.DestinationTx),
				sdk.NewAttribute("validator", valoper),
				sdk.NewAttribute("power", fmt.Sprintf("%d", valPower)),
				sdk.NewAttribute("attested_power", fmt.Sprintf("%d", attestation.AttestedPower)),
				sdk.NewAttribute("required_power", fmt.Sprintf("%d", requiredPower)),
				sdk.NewAttribute("minted", "true"),
				sdk.NewAttribute("late", "true"),
			),
		)

		return &types.MsgBridgeAttestMintedResponse{
			Confirmed:     true,
			AttestedPower: attestation.AttestedPower,
			RequiredPower: requiredPower,
		}, nil
	}

	canonicalDestTx := attestation.DestinationTx
	if canonicalDestTx == "" {
		return nil, fmt.Errorf("mint attestation missing canonical destination_tx")
	}
	if canonicalDestTx != destTx {
		ctx.Logger().Debug("BridgeAttestMinted destination_tx differs; using canonical",
			"burn_id", burnIDStr,
			"destination_chain", destChain,
			"canonical_destination_tx", canonicalDestTx,
			"provided_destination_tx", destTx,
			"validator", valoper,
		)
	}

	// Check if already attested by this validator
	alreadyAttested, err := k.HasBridgeMintAttestor(ctx, destChain, burnIDStr, valoper)
	if err != nil {
		return nil, fmt.Errorf("failed to check mint attestor: %w", err)
	}
	if alreadyAttested {
		totalPower, _ := k.GetTotalBondedValidatorPower(ctx)
		requiredPower := types.RequiredPower(totalPower, params.BridgeAttestationThreshold)

		ctx.Logger().Debug("BridgeAttestMinted validator already attested",
			"burn_id", burnIDStr,
			"validator", valoper,
		)

		// Emit event for duplicate attestation (idempotent - validator already recorded)
		ctx.EventManager().EmitEvent(
			sdk.NewEvent(
				"bridge_attest_minted",
				sdk.NewAttribute("burn_id", burnIDStr),
				sdk.NewAttribute("destination_chain", destChain),
				sdk.NewAttribute("destination_tx", attestation.DestinationTx),
				sdk.NewAttribute("validator", valoper),
				sdk.NewAttribute("power", fmt.Sprintf("%d", valPower)),
				sdk.NewAttribute("attested_power", fmt.Sprintf("%d", attestation.AttestedPower)),
				sdk.NewAttribute("required_power", fmt.Sprintf("%d", requiredPower)),
				sdk.NewAttribute("minted", fmt.Sprintf("%t", attestation.Confirmed)),
				sdk.NewAttribute("duplicate", "true"),
			),
		)

		return &types.MsgBridgeAttestMintedResponse{
			Confirmed:     attestation.Confirmed,
			AttestedPower: attestation.AttestedPower,
			RequiredPower: requiredPower,
		}, nil
	}

	// Add attestation (stored separately to avoid variable-size writes)
	if err := k.SetBridgeMintAttestor(ctx, destChain, burnIDStr, valoper, valPower); err != nil {
		return nil, fmt.Errorf("failed to store mint attestor: %w", err)
	}
	attestation.AttestedPower += valPower
	ctx.Logger().Debug("BridgeAttestMinted attestor recorded",
		"burn_id", burnIDStr,
		"destination_chain", destChain,
		"validator", valoper,
		"power", valPower,
		"attested_power", attestation.AttestedPower,
	)

	// Get total voting power
	totalPower, err := k.GetTotalBondedValidatorPower(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to get total voting power: %w", err)
	}

	requiredPower := types.RequiredPower(totalPower, params.BridgeAttestationThreshold)
	confirmed := false

	// Check if threshold is met
	if attestation.MeetsThreshold(totalPower, params.BridgeAttestationThreshold) {
		// Threshold met - confirm the mint
		attestation.Confirmed = true
		attestation.ConfirmedBy = validator
		confirmed = true

		// Store final mint record
		record := &types.BridgeMintedRecord{
			BurnID:           burnIDStr,
			DestinationChain: destChain,
			DestinationTx:    canonicalDestTx,
			CreatedAt:        ctx.BlockHeight(),
		}
		if err := k.SetBridgeMintedRecord(ctx, record); err != nil {
			return nil, fmt.Errorf("failed to store mint record: %w", err)
		}

		// Burn bridge fee immediately when threshold is reached
		if burnRecord.BridgeFee > 0 {
			if err := k.BurnFromModuleExact(ctx, burnRecord.BridgeFee); err != nil {
				return nil, fmt.Errorf("failed to burn bridge fee: %w", err)
			}
		}
		ctx.Logger().Debug("BridgeAttestMinted fee burned",
			"destination_chain", destChain,
			"burn_id", burnIDStr,
			"fee", burnRecord.BridgeFee,
		)

		ctx.Logger().Info("BridgeAttestMinted threshold met",
			"burn_id", burnIDStr,
			"destination_chain", destChain,
			"destination_tx", canonicalDestTx,
			"attested_power", attestation.AttestedPower,
			"required_power", requiredPower,
		)
	}

	// Save attestation
	if err := k.SetBridgeMintAttestation(ctx, attestation); err != nil {
		return nil, fmt.Errorf("failed to save mint attestation: %w", err)
	}

	// Emit attestation event (always, with current progress)
	ctx.EventManager().EmitEvent(
		sdk.NewEvent(
			"bridge_attest_minted",
			sdk.NewAttribute("burn_id", burnIDStr),
			sdk.NewAttribute("destination_chain", destChain),
			sdk.NewAttribute("destination_tx", canonicalDestTx),
			sdk.NewAttribute("validator", valoper),
			sdk.NewAttribute("power", fmt.Sprintf("%d", valPower)),
			sdk.NewAttribute("attested_power", fmt.Sprintf("%d", attestation.AttestedPower)),
			sdk.NewAttribute("required_power", fmt.Sprintf("%d", requiredPower)),
			sdk.NewAttribute("minted", fmt.Sprintf("%t", confirmed)),
			sdk.NewAttribute("mirage_tx_hash", mirageTxHash),
		),
	)

	ctx.Logger().Info("BridgeAttestMinted",
		"burn_id", burnIDStr,
		"destination_chain", destChain,
		"destination_tx", canonicalDestTx,
		"validator", valoper,
		"power", valPower,
		"attested_power", attestation.AttestedPower,
		"required_power", requiredPower,
		"confirmed", confirmed,
	)

	return &types.MsgBridgeAttestMintedResponse{
		Confirmed:     confirmed,
		AttestedPower: attestation.AttestedPower,
		RequiredPower: requiredPower,
	}, nil
}
