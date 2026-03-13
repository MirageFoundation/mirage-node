package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gagliardetto/solana-go"

	"mirage/orchestrator/attestor"
	"mirage/orchestrator/config"
	"mirage/orchestrator/mirage"
)

func main() {
	// -------------------------------------------------------------------------
	// HARD DISABLE (v1.20.0)
	// The bridge is offline and the current orchestrator is intentionally blocked
	// from running. This is a safety lock to prevent accidental startup on any
	// node while the replacement is being designed and validated.
	//
	// To re-enable:
	// 1) Remove this panic guard.
	// 2) Revisit verify_upgrade.py checks that enforce the guard.
	// 3) Re-enable ORCHESTRATOR_ENABLED in orchestrator.env only after approval.
	// -------------------------------------------------------------------------
	logger := log.New(os.Stdout, "orchestrator: ", log.LstdFlags|log.Lmicroseconds)
	logger.Println("ORCHESTRATOR_HARD_DISABLED: bridge is offline; do not run this binary")
	panic("ORCHESTRATOR_HARD_DISABLED: bridge is offline; do not run this binary")

	// NOTE: When re-enabling, remove the panic guard above and call:
	// runOrchestrator(logger)
}

func runOrchestrator(logger *log.Logger) {
	cfg, err := config.LoadFromEnv()
	if err != nil {
		logger.Printf("ERROR failed to load config: %v", err)
		os.Exit(1)
	}

	// If explicitly disabled, log and exit
	if !cfg.Enabled {
		logger.Printf("INFO orchestrator disabled (ORCHESTRATOR_ENABLED=false)")
		return
	}

	// Get Solana public key for banner
	var solanaPubkey string
	if cfg.Chains.Solana.Enabled && cfg.Chains.Solana.Keypair != "" {
		if solanaKey, err := solana.PrivateKeyFromSolanaKeygenFile(cfg.Chains.Solana.Keypair); err != nil {
			logger.Printf("WARN failed to read solana keypair: %v", err)
			solanaPubkey = "(failed to load)"
		} else {
			solanaPubkey = solanaKey.PublicKey().String()
		}
	} else {
		solanaPubkey = "(solana disabled)"
	}

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	mirageClient, err := mirage.NewClient(ctx, cfg, logger)
	if err != nil {
		logger.Printf("ERROR failed to create mirage client: %v", err)
		os.Exit(1)
	}
	defer mirageClient.Close()

	// Print startup banner with key addresses
	fmt.Println("------------------------------------------------------------------")
	fmt.Printf("Mirage Valoper: %s\n", mirageClient.ValoperAddress())
	fmt.Printf("Solana Pubkey:  %s\n", solanaPubkey)
	fmt.Println("------------------------------------------------------------------")

	runner, err := attestor.New(cfg, mirageClient, logger)
	if err != nil {
		logger.Printf("ERROR failed to create attestor: %v", err)
		os.Exit(1)
	}

	logger.Printf("INFO orchestrator started")

	if err := runner.Run(ctx); err != nil {
		if err == context.Canceled {
			logger.Printf("INFO orchestrator stopped")
		} else {
			logger.Printf("ERROR orchestrator failed: %v", err)
			// Sleep before exit to allow logs to be seen
			time.Sleep(5 * time.Second)
			os.Exit(1)
		}
	}
}
