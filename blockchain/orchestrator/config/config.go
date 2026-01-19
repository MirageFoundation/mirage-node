package config

import (
	"fmt"
	"os"
	"time"

	"gopkg.in/yaml.v3"
)

type Config struct {
	Mirage   MirageConfig   `yaml:"mirage"`
	Chains   ChainsConfig   `yaml:"chains"`
	Attestor AttestorConfig `yaml:"attestor"`
}

type MirageConfig struct {
	GRPC           string `yaml:"grpc"`
	RPC            string `yaml:"rpc"`
	ChainID        string `yaml:"chain_id"`
	KeyringDir     string `yaml:"keyring_dir"`
	KeyringBackend string `yaml:"keyring_backend"`
	KeyName        string `yaml:"key_name"`
	GasLimit       uint64 `yaml:"gas_limit"`
	FeeAmount      uint64 `yaml:"fee_amount"`
	FeeDenom       string `yaml:"fee_denom"`
}

type ChainsConfig struct {
	Solana SolanaConfig `yaml:"solana"`
}

type SolanaConfig struct {
	Enabled       bool          `yaml:"enabled"`
	RPC           string        `yaml:"rpc"`
	WS            string        `yaml:"ws"`
	ProgramID     string        `yaml:"program_id"`
	Keypair       string        `yaml:"keypair"`
	Confirmations uint64        `yaml:"confirmations"`
	PollInterval  time.Duration `yaml:"poll_interval"`
}

type AttestorConfig struct {
	BatchSize     int           `yaml:"batch_size"`
	RetryInterval time.Duration `yaml:"retry_interval"`
	MaxRetries    int           `yaml:"max_retries"`
}

func Load(path string) (*Config, error) {
	if path == "" {
		return nil, fmt.Errorf("config path cannot be empty")
	}
	bz, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("failed to read config: %w", err)
	}
	var cfg Config
	if err := yaml.Unmarshal(bz, &cfg); err != nil {
		return nil, fmt.Errorf("failed to parse config: %w", err)
	}
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	return &cfg, nil
}

func (c *Config) Validate() error {
	if c.Mirage.GRPC == "" {
		return fmt.Errorf("mirage.grpc is required")
	}
	if c.Mirage.RPC == "" {
		return fmt.Errorf("mirage.rpc is required")
	}
	if c.Mirage.ChainID == "" {
		return fmt.Errorf("mirage.chain_id is required")
	}
	if c.Mirage.KeyringDir == "" {
		return fmt.Errorf("mirage.keyring_dir is required")
	}
	if c.Mirage.KeyringBackend == "" {
		return fmt.Errorf("mirage.keyring_backend is required")
	}
	if c.Mirage.KeyName == "" {
		return fmt.Errorf("mirage.key_name is required")
	}
	if c.Mirage.GasLimit == 0 {
		return fmt.Errorf("mirage.gas_limit must be > 0")
	}
	if c.Mirage.FeeAmount == 0 {
		return fmt.Errorf("mirage.fee_amount must be > 0")
	}
	if c.Mirage.FeeDenom == "" {
		return fmt.Errorf("mirage.fee_denom is required")
	}
	if c.Attestor.BatchSize <= 0 {
		return fmt.Errorf("attestor.batch_size must be > 0")
	}
	if c.Attestor.RetryInterval <= 0 {
		return fmt.Errorf("attestor.retry_interval must be > 0")
	}
	if c.Attestor.MaxRetries <= 0 {
		return fmt.Errorf("attestor.max_retries must be > 0")
	}
	if c.Chains.Solana.Enabled {
		if c.Chains.Solana.RPC == "" {
			return fmt.Errorf("chains.solana.rpc is required when solana enabled")
		}
		if c.Chains.Solana.WS == "" {
			return fmt.Errorf("chains.solana.ws is required when solana enabled")
		}
		if c.Chains.Solana.ProgramID == "" {
			return fmt.Errorf("chains.solana.program_id is required when solana enabled")
		}
		if c.Chains.Solana.Keypair == "" {
			return fmt.Errorf("chains.solana.keypair is required when solana enabled")
		}
		if c.Chains.Solana.Confirmations == 0 {
			return fmt.Errorf("chains.solana.confirmations must be > 0 when solana enabled")
		}
		if c.Chains.Solana.PollInterval <= 0 {
			return fmt.Errorf("chains.solana.poll_interval must be > 0 when solana enabled")
		}
	}
	return nil
}
