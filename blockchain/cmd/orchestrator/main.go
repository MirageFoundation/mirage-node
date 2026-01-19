package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/spf13/cobra"

	"mirage/orchestrator/attestor"
	"mirage/orchestrator/config"
	"mirage/orchestrator/mirage"
)

func main() {
	logger := log.New(os.Stdout, "orchestrator: ", log.LstdFlags|log.Lmicroseconds)
	rootCmd := &cobra.Command{
		Use:   "mirage-orchestrator",
		Short: "Mirage bridge orchestrator",
		RunE: func(cmd *cobra.Command, _ []string) error {
			cfgPath, err := cmd.Flags().GetString("config")
			if err != nil {
				return err
			}
			cfg, err := config.Load(cfgPath)
			if err != nil {
				return err
			}

			logger.Printf("DEBUG config loaded: rpc=%s grpc=%s chain_id=%s", cfg.Mirage.RPC, cfg.Mirage.GRPC, cfg.Mirage.ChainID)

			ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
			defer cancel()

			mirageClient, err := mirage.NewClient(ctx, cfg, logger)
			if err != nil {
				return err
			}
			defer mirageClient.Close()

			runner, err := attestor.New(cfg, mirageClient, logger)
			if err != nil {
				return err
			}

			logger.Printf("DEBUG orchestrator started")
			return runner.Run(ctx)
		},
	}

	rootCmd.Flags().String("config", "orchestrator.yaml", "Path to orchestrator config file")

	if err := rootCmd.Execute(); err != nil {
		logger.Printf("ERROR %v", err)
		os.Exit(1)
	}
}
