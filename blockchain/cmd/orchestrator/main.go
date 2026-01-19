package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"mirage/orchestrator/attestor"
	"mirage/orchestrator/config"
	"mirage/orchestrator/mirage"
)

func main() {
	logger := log.New(os.Stdout, "orchestrator: ", log.LstdFlags|log.Lmicroseconds)

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

	logger.Printf("INFO config loaded: chain_id=%s solana_enabled=%v", cfg.Mirage.ChainID, cfg.Chains.Solana.Enabled)

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	mirageClient, err := mirage.NewClient(ctx, cfg, logger)
	if err != nil {
		logger.Printf("ERROR failed to create mirage client: %v", err)
		os.Exit(1)
	}
	defer mirageClient.Close()

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
