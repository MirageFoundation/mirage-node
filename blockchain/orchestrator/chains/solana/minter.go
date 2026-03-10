package solana

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"strings"
	"time"

	"github.com/gagliardetto/solana-go"
	associatedtokenaccount "github.com/gagliardetto/solana-go/programs/associated-token-account"
	"github.com/gagliardetto/solana-go/programs/system"
	"github.com/gagliardetto/solana-go/programs/token"
	"github.com/gagliardetto/solana-go/rpc"

	"mirage/orchestrator/chains"
)

func (w *Watcher) ExecuteMint(ctx context.Context, burn chains.MirageBurnEvent) (string, error) {
	if !w.ready {
		return "", fmt.Errorf("solana watcher not ready")
	}
	// Use TxHash (Mirage transaction hash) as the unique burn identifier for Solana
	// BurnID is the sequence number, TxHash is the 64-char hex hash
	burnHash, err := decodeBurnHash(burn.TxHash)
	if err != nil {
		return "", fmt.Errorf("invalid mirage tx hash: %w", err)
	}
	recipient, err := solana.PublicKeyFromBase58(strings.TrimSpace(burn.DestinationAddress))
	if err != nil {
		return "", fmt.Errorf("invalid solana destination address: %w", err)
	}

	orchestratorKey := w.keypair
	orchestratorPub := orchestratorKey.PublicKey()

	mintPDA, _, err := solana.FindProgramAddress([][]byte{[]byte(mintSeed)}, w.programID)
	if err != nil {
		return "", fmt.Errorf("failed to derive mint PDA: %w", err)
	}
	bridgeConfigPDA, _, err := solana.FindProgramAddress([][]byte{[]byte(bridgeConfigSeed)}, w.programID)
	if err != nil {
		return "", fmt.Errorf("failed to derive bridge config PDA: %w", err)
	}
	bridgeStatePDA, _, err := solana.FindProgramAddress([][]byte{[]byte(bridgeStateSeed)}, w.programID)
	if err != nil {
		return "", fmt.Errorf("failed to derive bridge state PDA: %w", err)
	}
	mintRecordPDA, _, err := solana.FindProgramAddress([][]byte{[]byte(mintRecordSeed), burnHash[:]}, w.programID)
	if err != nil {
		return "", fmt.Errorf("failed to derive mint record PDA: %w", err)
	}
	recipientATA, _, err := solana.FindAssociatedTokenAddress(recipient, mintPDA)
	if err != nil {
		return "", fmt.Errorf("failed to derive recipient ATA: %w", err)
	}
	validatorRegistryPDA, _, err := solana.FindProgramAddress([][]byte{[]byte(validatorRegistrySeed)}, w.programID)
	if err != nil {
		return "", fmt.Errorf("failed to derive validator registry PDA: %w", err)
	}

	// Determine mint_record_payer: if record exists, use stored payer; otherwise orchestrator
	mintRecordPayer := orchestratorPub
	if payer, err := w.getMintRecordPayer(ctx, mintRecordPDA); err == nil && payer != (solana.PublicKey{}) {
		mintRecordPayer = payer
	}

	// Calculate net amount after fee deduction
	if burn.BridgeFee >= burn.Amount {
		w.logger.Printf("WARN skipping burn %s: fee (%d) >= amount (%d)", burn.BurnID, burn.BridgeFee, burn.Amount)
		return "", nil
	}
	mintAmount := burn.Amount - burn.BridgeFee

	// Anchor's init_if_needed handles ATA creation, no separate instruction needed
	instructions := []solana.Instruction{}

	attestationPayload := buildMintAttestationPayload(burnHash, burn.Owner, mintAmount, recipient, "solana")
	attestationSig, err := signMintAttestation(orchestratorKey, burnHash, burn.Owner, mintAmount, recipient, "solana")
	if err != nil {
		return "", err
	}

	// Add Ed25519 verify instruction (must precede mint instruction for on-chain verification)
	ed25519Instr := buildEd25519VerifyInstruction(orchestratorPub, attestationPayload, attestationSig)
	instructions = append(instructions, ed25519Instr)

	data, err := buildMintInstructionData(w.discMint, burnHash, burn.Owner, mintAmount, burn.Sequence)
	if err != nil {
		return "", err
	}

	// Instructions sysvar for Ed25519 signature verification
	instructionsSysvar := solana.MustPublicKeyFromBase58("Sysvar1nstructions1111111111111111111111111")

	// NewAccountMeta signature: (pubKey, WRITABLE, SIGNER)
	mintInstruction := &genericInstruction{
		programID: w.programID,
		accounts: []*solana.AccountMeta{
			solana.NewAccountMeta(orchestratorPub, true, true),                    // orchestrator (writable, signer)
			solana.NewAccountMeta(recipient, false, false),                        // recipient
			solana.NewAccountMeta(mintRecordPayer, true, false),                   // mint_record_payer (writable) - rent refund target
			solana.NewAccountMeta(recipientATA, true, false),                      // recipient_token_account (writable)
			solana.NewAccountMeta(mintPDA, true, false),                           // token_mint (writable)
			solana.NewAccountMeta(bridgeConfigPDA, true, false),                   // bridge_config (writable)
			solana.NewAccountMeta(bridgeStatePDA, true, false),                    // bridge_state (writable)
			solana.NewAccountMeta(mintRecordPDA, true, false),                     // mint_record (writable)
			solana.NewAccountMeta(validatorRegistryPDA, false, false),             // validator_registry
			solana.NewAccountMeta(instructionsSysvar, false, false),               // instructions_sysvar
			solana.NewAccountMeta(token.ProgramID, false, false),                  // token_program
			solana.NewAccountMeta(associatedtokenaccount.ProgramID, false, false), // associated_token_program
			solana.NewAccountMeta(system.ProgramID, false, false),                 // system_program
		},
		data: data,
	}
	instructions = append(instructions, mintInstruction)

	latest, err := w.rpcClient.GetLatestBlockhash(ctx, w.commitment())
	if err != nil {
		return "", fmt.Errorf("failed to get latest blockhash: %w", err)
	}
	tx, err := solana.NewTransaction(
		instructions,
		latest.Value.Blockhash,
		solana.TransactionPayer(orchestratorPub),
	)
	if err != nil {
		return "", fmt.Errorf("failed to build transaction: %w", err)
	}
	_, err = tx.Sign(func(pub solana.PublicKey) *solana.PrivateKey {
		if pub.Equals(orchestratorPub) {
			return &orchestratorKey
		}
		return nil
	})
	if err != nil {
		return "", fmt.Errorf("failed to sign transaction: %w", err)
	}

	sig, err := w.rpcClient.SendTransactionWithOpts(ctx, tx, rpc.TransactionOpts{
		SkipPreflight:       false,
		PreflightCommitment: w.commitment(),
	})
	if err != nil {
		// Check if this is an "AlreadyMinted" error - means Solana mint succeeded previously
		errStr := err.Error()
		if strings.Contains(errStr, "AlreadyMinted") || strings.Contains(errStr, "6021") {
			w.logger.Printf("WARN  [ALREADY_MINTED] burn_id=%s was already minted on Solana; recovering signature", burn.BurnID)
			recoveredSig, sigErr := w.findMintRecordSignature(ctx, mintRecordPDA)
			if sigErr != nil {
				return "", fmt.Errorf("mint already exists but failed to recover signature: %w", sigErr)
			}
			w.logger.Printf("INFO  [ALREADY_MINTED] recovered signature burn_id=%s signature=%s", burn.BurnID, recoveredSig)
			return recoveredSig, nil
		}
		return "", fmt.Errorf("failed to send transaction: %w", err)
	}
	explorerURL := w.solscanURL(sig)
	w.logger.Printf("DEBUG solana mint submitted burn_id=%s signature=%s", burn.BurnID, sig.String())
	w.logger.Printf("INFO  solscan: %s", explorerURL)

	if err := w.waitForConfirmation(ctx, sig); err != nil {
		return "", err
	}

	// Log Solana fee (base fee ~5000 lamports = 0.000005 SOL per signature)
	w.logger.Printf("INFO  [FEES] solana_mint solana_fee=~0.000005 SOL mint_amount=%.2f MIRAGE burn_id=%s signature=%s",
		float64(mintAmount)/1_000_000, burn.BurnID, sig.String())

	return sig.String(), nil
}

func (w *Watcher) findMintRecordSignature(ctx context.Context, mintRecordPDA solana.PublicKey) (string, error) {
	const pageLimit = 100
	const maxPages = 5

	var beforeSig solana.Signature
	var oldestSig *rpc.TransactionSignature

	for page := 0; page < maxPages; page++ {
		opts := &rpc.GetSignaturesForAddressOpts{
			Limit: ptr(pageLimit),
		}
		if !beforeSig.IsZero() {
			opts.Before = beforeSig
		}

		sigs, err := w.rpcClient.GetSignaturesForAddressWithOpts(ctx, mintRecordPDA, opts)
		if err != nil {
			return "", fmt.Errorf("failed to fetch mint_record signatures: %w", err)
		}
		if len(sigs) == 0 {
			break
		}

		for _, sig := range sigs {
			if sig.Err != nil {
				continue
			}
			oldestSig = sig
		}

		if len(sigs) < pageLimit {
			break
		}
		if page == maxPages-1 {
			return "", fmt.Errorf("mint_record signature history too long (> %d)", pageLimit*maxPages)
		}
		beforeSig = sigs[len(sigs)-1].Signature
	}

	if oldestSig == nil {
		return "", fmt.Errorf("no successful mint_record signatures found")
	}
	return oldestSig.Signature.String(), nil
}

func (w *Watcher) accountExists(ctx context.Context, pubkey solana.PublicKey) (bool, error) {
	info, err := w.rpcClient.GetAccountInfo(ctx, pubkey)
	if err != nil {
		// Account not found is not an error, it means the account doesn't exist
		if strings.Contains(err.Error(), "not found") {
			return false, nil
		}
		return false, err
	}
	return info != nil && info.Value != nil, nil
}

// getMintRecordPayer fetches the payer pubkey from an existing MintRecord account.
// Returns zero pubkey if account doesn't exist or can't be read.
func (w *Watcher) getMintRecordPayer(ctx context.Context, mintRecordPDA solana.PublicKey) (solana.PublicKey, error) {
	info, err := w.rpcClient.GetAccountInfo(ctx, mintRecordPDA)
	if err != nil {
		if strings.Contains(err.Error(), "not found") {
			return solana.PublicKey{}, nil // Account doesn't exist yet
		}
		return solana.PublicKey{}, err
	}
	if info == nil || info.Value == nil || info.Value.Data == nil {
		return solana.PublicKey{}, nil // Account doesn't exist
	}

	data := info.Value.Data.GetBinary()
	// MintRecord layout: 8 (discriminator) + 32 (payer) + ...
	// Payer starts at offset 8
	if len(data) < 40 {
		return solana.PublicKey{}, fmt.Errorf("mint record data too short: %d bytes", len(data))
	}

	var payer solana.PublicKey
	copy(payer[:], data[8:40])
	return payer, nil
}

func (w *Watcher) waitForConfirmation(ctx context.Context, sig solana.Signature) error {
	sub, err := w.wsClient.SignatureSubscribe(sig, w.commitment())
	if err != nil {
		return fmt.Errorf("failed to subscribe to signature: %w", err)
	}
	defer sub.Unsubscribe()

	select {
	case <-ctx.Done():
		return ctx.Err()
	case resp := <-sub.Response():
		if resp.Value.Err != nil {
			return fmt.Errorf("transaction failed: %v", resp.Value.Err)
		}
	case <-time.After(60 * time.Second):
		return fmt.Errorf("timed out waiting for mint confirmation")
	}
	return nil
}

func decodeBurnHash(burnID string) ([32]byte, error) {
	var out [32]byte
	burnID = strings.TrimSpace(burnID)
	if len(burnID) != 64 {
		return out, fmt.Errorf("burn_id must be 64 hex characters")
	}
	bz, err := hex.DecodeString(burnID)
	if err != nil {
		return out, fmt.Errorf("invalid burn_id hex: %w", err)
	}
	copy(out[:], bz)
	return out, nil
}

func signMintAttestation(key solana.PrivateKey, burnHash [32]byte, mirageSender string, amount uint64, recipient solana.PublicKey, destinationChain string) ([64]byte, error) {
	payload := buildMintAttestationPayload(burnHash, mirageSender, amount, recipient, destinationChain)
	sig := ed25519.Sign(ed25519.PrivateKey(key), payload)
	var out [64]byte
	copy(out[:], sig)
	return out, nil
}

func buildMintAttestationPayload(burnHash [32]byte, mirageSender string, amount uint64, recipient solana.PublicKey, destinationChain string) []byte {
	buf := bytes.NewBuffer(nil)
	buf.Write(burnHash[:])
	writeBorshString(buf, mirageSender)
	_ = binary.Write(buf, binary.LittleEndian, amount)
	buf.Write(recipient[:]) // 32 bytes - binds recipient to prevent redirection attacks
	writeBorshString(buf, destinationChain) // binds destination chain to prevent cross-chain replay
	return buf.Bytes()
}

func buildMintInstructionData(discriminator [8]byte, burnHash [32]byte, mirageSender string, amount uint64, sequence uint64) ([]byte, error) {
	buf := bytes.NewBuffer(nil)
	if _, err := buf.Write(discriminator[:]); err != nil {
		return nil, err
	}
	buf.Write(burnHash[:])
	writeBorshString(buf, mirageSender)
	if err := binary.Write(buf, binary.LittleEndian, amount); err != nil {
		return nil, err
	}
	if err := binary.Write(buf, binary.LittleEndian, sequence); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

func writeBorshString(buf *bytes.Buffer, value string) {
	length := uint32(len(value))
	_ = binary.Write(buf, binary.LittleEndian, length)
	buf.WriteString(value)
}

// Ed25519 program ID
var ed25519ProgramID = solana.MustPublicKeyFromBase58("Ed25519SigVerify111111111111111111111111111")

// buildEd25519VerifyInstruction creates an Ed25519 signature verification instruction.
// This must precede the mint instruction for on-chain signature verification.
func buildEd25519VerifyInstruction(pubkey solana.PublicKey, message []byte, signature [64]byte) solana.Instruction {
	// Ed25519 instruction format:
	// [0]: num_signatures (1)
	// [1]: padding (0)
	// [2-3]: signature_offset (16 for first signature)
	// [4-5]: signature_instruction_index (0xFFFF = same transaction)
	// [6-7]: public_key_offset
	// [8-9]: public_key_instruction_index (0xFFFF)
	// [10-11]: message_offset
	// [12-13]: message_size
	// [14-15]: message_instruction_index (0xFFFF)
	// Then: signature (64 bytes), pubkey (32 bytes), message (variable)

	signatureOffset := uint16(16) // Starts right after header
	pubkeyOffset := signatureOffset + 64
	messageOffset := pubkeyOffset + 32
	messageSize := uint16(len(message))

	buf := bytes.NewBuffer(nil)
	buf.WriteByte(1)    // num_signatures
	buf.WriteByte(0)    // padding
	binary.Write(buf, binary.LittleEndian, signatureOffset)
	binary.Write(buf, binary.LittleEndian, uint16(0xFFFF)) // signature_instruction_index
	binary.Write(buf, binary.LittleEndian, pubkeyOffset)
	binary.Write(buf, binary.LittleEndian, uint16(0xFFFF)) // public_key_instruction_index
	binary.Write(buf, binary.LittleEndian, messageOffset)
	binary.Write(buf, binary.LittleEndian, messageSize)
	binary.Write(buf, binary.LittleEndian, uint16(0xFFFF)) // message_instruction_index
	buf.Write(signature[:])
	buf.Write(pubkey[:])
	buf.Write(message)

	return &genericInstruction{
		programID: ed25519ProgramID,
		accounts:  []*solana.AccountMeta{}, // Ed25519 program takes no accounts
		data:      buf.Bytes(),
	}
}

// genericInstruction implements solana.Instruction for custom program instructions
type genericInstruction struct {
	programID solana.PublicKey
	accounts  []*solana.AccountMeta
	data      []byte
}

func (i *genericInstruction) ProgramID() solana.PublicKey {
	return i.programID
}

func (i *genericInstruction) Accounts() []*solana.AccountMeta {
	return i.accounts
}

func (i *genericInstruction) Data() ([]byte, error) {
	return i.data, nil
}
