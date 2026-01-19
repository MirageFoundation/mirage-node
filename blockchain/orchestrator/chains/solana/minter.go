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

func (w *Watcher) ExecuteMint(ctx context.Context, burn chains.MirageBurnEvent) error {
	if !w.ready {
		return fmt.Errorf("solana watcher not ready")
	}
	burnHash, err := decodeBurnHash(burn.BurnID)
	if err != nil {
		return err
	}
	recipient, err := solana.PublicKeyFromBase58(strings.TrimSpace(burn.DestinationAddress))
	if err != nil {
		return fmt.Errorf("invalid solana destination address: %w", err)
	}

	orchestratorKey, err := solana.PrivateKeyFromSolanaKeygenFile(w.cfg.Keypair)
	if err != nil {
		return fmt.Errorf("failed to read solana keypair: %w", err)
	}
	orchestratorPub := orchestratorKey.PublicKey()

	mintPDA, _, err := solana.FindProgramAddress([][]byte{[]byte(mintSeed)}, w.programID)
	if err != nil {
		return fmt.Errorf("failed to derive mint PDA: %w", err)
	}
	bridgeConfigPDA, _, err := solana.FindProgramAddress([][]byte{[]byte(bridgeConfigSeed)}, w.programID)
	if err != nil {
		return fmt.Errorf("failed to derive bridge config PDA: %w", err)
	}
	mintRecordPDA, _, err := solana.FindProgramAddress([][]byte{[]byte(mintRecordSeed), burnHash[:]}, w.programID)
	if err != nil {
		return fmt.Errorf("failed to derive mint record PDA: %w", err)
	}
	recipientATA, _, err := solana.FindAssociatedTokenAddress(recipient, mintPDA)
	if err != nil {
		return fmt.Errorf("failed to derive recipient ATA: %w", err)
	}

	// Build instructions list - create ATA if it doesn't exist
	instructions := []solana.Instruction{}

	ataExists, err := w.accountExists(ctx, recipientATA)
	if err != nil {
		return fmt.Errorf("failed to check recipient ATA: %w", err)
	}
	if !ataExists {
		// Create ATA instruction (idempotent - will succeed even if account exists)
		createATAInstr := associatedtokenaccount.NewCreateInstruction(
			orchestratorPub, // payer
			recipient,       // wallet
			mintPDA,         // mint
		).Build()
		instructions = append(instructions, createATAInstr)
		w.logger.Printf("DEBUG creating ATA for recipient=%s", recipient.String())
	}

	attestationSig, err := signMintAttestation(orchestratorKey, burnHash, burn.Owner, burn.Amount, recipient)
	if err != nil {
		return err
	}

	data, err := buildMintInstructionData(w.discMint, burnHash, burn.Owner, burn.Amount, attestationSig)
	if err != nil {
		return err
	}

	mintInstruction := &genericInstruction{
		programID: w.programID,
		accounts: []*solana.AccountMeta{
			solana.NewAccountMeta(orchestratorPub, true, true),
			solana.NewAccountMeta(recipient, false, false),
			solana.NewAccountMeta(recipientATA, false, true),
			solana.NewAccountMeta(mintPDA, false, true),
			solana.NewAccountMeta(bridgeConfigPDA, false, true),
			solana.NewAccountMeta(mintRecordPDA, false, true),
			solana.NewAccountMeta(token.ProgramID, false, false),
			solana.NewAccountMeta(associatedtokenaccount.ProgramID, false, false),
			solana.NewAccountMeta(system.ProgramID, false, false),
		},
		data: data,
	}
	instructions = append(instructions, mintInstruction)

	latest, err := w.rpcClient.GetLatestBlockhash(ctx, w.commitment())
	if err != nil {
		return fmt.Errorf("failed to get latest blockhash: %w", err)
	}
	tx, err := solana.NewTransaction(
		instructions,
		latest.Value.Blockhash,
		solana.TransactionPayer(orchestratorPub),
	)
	if err != nil {
		return fmt.Errorf("failed to build transaction: %w", err)
	}
	_, err = tx.Sign(func(pub solana.PublicKey) *solana.PrivateKey {
		if pub.Equals(orchestratorPub) {
			return &orchestratorKey
		}
		return nil
	})
	if err != nil {
		return fmt.Errorf("failed to sign transaction: %w", err)
	}

	sig, err := w.rpcClient.SendTransactionWithOpts(ctx, tx, rpc.TransactionOpts{
		SkipPreflight:       false,
		PreflightCommitment: w.commitment(),
	})
	if err != nil {
		return fmt.Errorf("failed to send transaction: %w", err)
	}
	w.logger.Printf("DEBUG solana mint submitted burn_id=%s signature=%s", burn.BurnID, sig.String())

	if err := w.waitForConfirmation(ctx, sig); err != nil {
		return err
	}
	return nil
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

func signMintAttestation(key solana.PrivateKey, burnHash [32]byte, mirageSender string, amount uint64, recipient solana.PublicKey) ([64]byte, error) {
	payload := buildMintAttestationPayload(burnHash, mirageSender, amount, recipient)
	sig := ed25519.Sign(ed25519.PrivateKey(key), payload)
	var out [64]byte
	copy(out[:], sig)
	return out, nil
}

func buildMintAttestationPayload(burnHash [32]byte, mirageSender string, amount uint64, recipient solana.PublicKey) []byte {
	buf := bytes.NewBuffer(nil)
	buf.Write(burnHash[:])
	writeBorshString(buf, mirageSender)
	_ = binary.Write(buf, binary.LittleEndian, amount)
	buf.Write(recipient[:]) // 32 bytes - binds recipient to prevent redirection attacks
	return buf.Bytes()
}

func buildMintInstructionData(discriminator [8]byte, burnHash [32]byte, mirageSender string, amount uint64, sig [64]byte) ([]byte, error) {
	buf := bytes.NewBuffer(nil)
	if _, err := buf.Write(discriminator[:]); err != nil {
		return nil, err
	}
	buf.Write(burnHash[:])
	writeBorshString(buf, mirageSender)
	if err := binary.Write(buf, binary.LittleEndian, amount); err != nil {
		return nil, err
	}
	buf.Write(sig[:])
	return buf.Bytes(), nil
}

func writeBorshString(buf *bytes.Buffer, value string) {
	length := uint32(len(value))
	_ = binary.Write(buf, binary.LittleEndian, length)
	buf.WriteString(value)
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
