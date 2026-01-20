package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	Enabled  bool
	Mirage   MirageConfig
	Chains   ChainsConfig
	Attestor AttestorConfig
}

type MirageConfig struct {
	GRPC           string
	RPC            string
	ChainID        string
	KeyringDir     string
	KeyringBackend string
	KeyName        string
	FeeDenom       string // Gas limit and fee are determined via simulation
}

type ChainsConfig struct {
	Solana SolanaConfig
}

type SolanaConfig struct {
	Enabled         bool
	RPC             string
	WS              string
	Cluster         string // devnet | testnet | mainnet
	ProgramID       string
	Keypair         string
	Confirmations   uint64
	PollIntervalMin time.Duration
	PollIntervalMax time.Duration
	StateDir        string        // Directory to persist watcher state (lastSig)
}

type AttestorConfig struct {
	BatchSize     int
	RetryInterval time.Duration
	MaxRetries    int
}

// LoadFromEnv loads configuration from environment variables.
// All values including ORCHESTRATOR_ENABLED must be set explicitly.
// Missing or invalid values will cause an error.
func LoadFromEnv() (*Config, error) {
	home := os.Getenv("HOME")
	if home == "" {
		home = "/root"
	}

	// Check if enabled - no default, must be explicitly set
	enabledStr := os.Getenv("ORCHESTRATOR_ENABLED")
	if enabledStr == "" {
		return nil, fmt.Errorf("ORCHESTRATOR_ENABLED is not set - copy template from deploy/templates/env/orchestrator.env to ~/.mirage/env/orchestrator.env")
	}
	enabled, err := strconv.ParseBool(enabledStr)
	if err != nil {
		return nil, fmt.Errorf("ORCHESTRATOR_ENABLED must be true or false, got: %s", enabledStr)
	}

	// If explicitly disabled, return minimal config
	if !enabled {
		return &Config{Enabled: false}, nil
	}

	// All other values are required when enabled
	var errs []string

	// Solana config
	solanaRPC := os.Getenv("ORCHESTRATOR_SOLANA_RPC")
	if solanaRPC == "" {
		errs = append(errs, "ORCHESTRATOR_SOLANA_RPC is required")
	}
	solanaWS := os.Getenv("ORCHESTRATOR_SOLANA_WS")
	if solanaWS == "" {
		errs = append(errs, "ORCHESTRATOR_SOLANA_WS is required")
	}
	solanaCluster := strings.ToLower(strings.TrimSpace(os.Getenv("ORCHESTRATOR_SOLANA_CLUSTER")))
	if solanaCluster == "" {
		errs = append(errs, "ORCHESTRATOR_SOLANA_CLUSTER is required (devnet | testnet | mainnet)")
	} else if solanaCluster != "devnet" && solanaCluster != "testnet" && solanaCluster != "mainnet" {
		errs = append(errs, "ORCHESTRATOR_SOLANA_CLUSTER must be devnet, testnet, or mainnet")
	}
	solanaProgramID := os.Getenv("ORCHESTRATOR_SOLANA_PROGRAM_ID")
	if solanaProgramID == "" {
		errs = append(errs, "ORCHESTRATOR_SOLANA_PROGRAM_ID is required")
	}
	solanaKeypair := os.Getenv("ORCHESTRATOR_SOLANA_KEYPAIR")
	if solanaKeypair == "" {
		errs = append(errs, "ORCHESTRATOR_SOLANA_KEYPAIR is required")
	}
	solanaConfirmations, err := envRequiredUint64("ORCHESTRATOR_SOLANA_CONFIRMATIONS")
	if err != nil {
		errs = append(errs, err.Error())
	}
	solanaPollIntervalMin, err := envRequiredDuration("ORCHESTRATOR_SOLANA_POLL_INTERVAL_MIN")
	if err != nil {
		errs = append(errs, err.Error())
	}
	solanaPollIntervalMax, err := envRequiredDuration("ORCHESTRATOR_SOLANA_POLL_INTERVAL_MAX")
	if err != nil {
		errs = append(errs, err.Error())
	}

	// Mirage config (chain ID and fee denom are constants)
	mirageGRPC := os.Getenv("ORCHESTRATOR_MIRAGE_GRPC")
	if mirageGRPC == "" {
		errs = append(errs, "ORCHESTRATOR_MIRAGE_GRPC is required")
	}
	mirageRPC := os.Getenv("ORCHESTRATOR_MIRAGE_RPC")
	if mirageRPC == "" {
		errs = append(errs, "ORCHESTRATOR_MIRAGE_RPC is required")
	}
	keyringBackend := os.Getenv("ORCHESTRATOR_KEYRING_BACKEND")
	if keyringBackend == "" {
		errs = append(errs, "ORCHESTRATOR_KEYRING_BACKEND is required")
	}
	keyName := os.Getenv("ORCHESTRATOR_KEY_NAME")
	if keyName == "" {
		errs = append(errs, "ORCHESTRATOR_KEY_NAME is required")
	}

	// Attestor config
	batchSize, err := envRequiredInt("ORCHESTRATOR_BATCH_SIZE")
	if err != nil {
		errs = append(errs, err.Error())
	}
	retryInterval, err := envRequiredDuration("ORCHESTRATOR_RETRY_INTERVAL")
	if err != nil {
		errs = append(errs, err.Error())
	}
	maxRetries, err := envRequiredInt("ORCHESTRATOR_MAX_RETRIES")
	if err != nil {
		errs = append(errs, err.Error())
	}

	// Return all errors at once
	if len(errs) > 0 {
		return nil, fmt.Errorf("missing or invalid config:\n  - %s", joinErrors(errs))
	}

	// Check Solana keypair exists
	if _, err := os.Stat(solanaKeypair); os.IsNotExist(err) {
		return nil, fmt.Errorf("solana keypair not found: %s\n\nRun setup script first:\n  python3 deploy/setup_orchestrator.py", solanaKeypair)
	}

	cfg := &Config{
		Enabled: true,
		Mirage: MirageConfig{
			GRPC:           mirageGRPC,
			RPC:            mirageRPC,
			ChainID:        "mirage-1",
			KeyringDir:     home + "/.mirage/node",
			KeyringBackend: keyringBackend,
			KeyName:        keyName,
			FeeDenom:       "umirage",
		},
		Chains: ChainsConfig{
		Solana: SolanaConfig{
			Enabled:         true,
			RPC:             solanaRPC,
			WS:              solanaWS,
			Cluster:         solanaCluster,
			ProgramID:       solanaProgramID,
			Keypair:         solanaKeypair,
			Confirmations:   solanaConfirmations,
			PollIntervalMin: solanaPollIntervalMin,
			PollIntervalMax: solanaPollIntervalMax,
			StateDir:        home + "/.mirage/orchestrator",
		},
		},
		Attestor: AttestorConfig{
			BatchSize:     batchSize,
			RetryInterval: retryInterval,
			MaxRetries:    maxRetries,
		},
	}

	return cfg, nil
}

// Load is kept for backward compatibility but now just calls LoadFromEnv.
func Load(_ string) (*Config, error) {
	return LoadFromEnv()
}

func joinErrors(errs []string) string {
	result := errs[0]
	for i := 1; i < len(errs); i++ {
		result += "\n  - " + errs[i]
	}
	return result
}

func envBool(key string, defaultVal bool) bool {
	val := os.Getenv(key)
	if val == "" {
		return defaultVal
	}
	b, err := strconv.ParseBool(val)
	if err != nil {
		return defaultVal
	}
	return b
}

func envRequiredUint64(key string) (uint64, error) {
	val := os.Getenv(key)
	if val == "" {
		return 0, fmt.Errorf("%s is required", key)
	}
	n, err := strconv.ParseUint(val, 10, 64)
	if err != nil {
		return 0, fmt.Errorf("%s must be a valid number: %v", key, err)
	}
	return n, nil
}

func envRequiredInt(key string) (int, error) {
	val := os.Getenv(key)
	if val == "" {
		return 0, fmt.Errorf("%s is required", key)
	}
	n, err := strconv.Atoi(val)
	if err != nil {
		return 0, fmt.Errorf("%s must be a valid integer: %v", key, err)
	}
	return n, nil
}

func envRequiredDuration(key string) (time.Duration, error) {
	val := os.Getenv(key)
	if val == "" {
		return 0, fmt.Errorf("%s is required", key)
	}
	d, err := time.ParseDuration(val)
	if err != nil {
		return 0, fmt.Errorf("%s must be a valid duration (e.g., '5s', '10m'): %v", key, err)
	}
	return d, nil
}
