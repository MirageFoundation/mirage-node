package cmd

import (
	"time"

	cmtcfg "github.com/cometbft/cometbft/config"
	serverconfig "github.com/cosmos/cosmos-sdk/server/config"
)

// initCometBFTConfig configures CometBFT (config.toml).
// NOTE: This affects consensus/p2p/rpc settings written to config.toml, not app.toml.
// Return cmtcfg.DefaultConfig if no custom configuration is required for the application.
func initCometBFTConfig() *cmtcfg.Config {
	cfg := cmtcfg.DefaultConfig()

	// Set timeout_commit to 3s
	cfg.Consensus.TimeoutCommit = 3 * time.Second

	// Skip empty blocks to reduce storage/memory usage
	// When false, blocks are only created when there are transactions
	// This significantly reduces the number of blocks (and state versions) created
	cfg.Consensus.CreateEmptyBlocks = false

	// Still create an empty block every 5 minutes to maintain some time consistency
	// This prevents the chain from appearing "stuck" during quiet periods
	cfg.Consensus.CreateEmptyBlocksInterval = 600 * time.Second

	// these values put a higher strain on node memory
	// cfg.P2P.MaxNumInboundPeers = 100
	// cfg.P2P.MaxNumOutboundPeers = 40

	return cfg
}

// initAppConfig configures Cosmos SDK server settings (app.toml).
// NOTE: This controls pruning, snapshots, min gas prices, min-retain-blocks, etc.
// Return "", nil if no custom configuration is required for the application.
func initAppConfig() (string, interface{}) {
	// The following code snippet is just for reference.
	type CustomAppConfig struct {
		serverconfig.Config `mapstructure:",squash"`
	}

	// Optionally allow the chain developer to overwrite the SDK's default
	// server config.
	srvCfg := serverconfig.DefaultConfig()

	srvCfg.MinGasPrices = "1000umirage"

	// Pruning (app state only): keep a rolling window of recent committed heights.
	// IMPORTANT (Mirage):
	// - This controls IAVL/multistore state versions for historical ABCI/gRPC queries.
	// - It DOES NOT keep CometBFT blocks or transactions. The Mirage indexer consumes
	//   txs from blocks; pruning here does not impact the indexer’s ability to read txs.
	// - Safe to keep short unless you specifically need proofed historical state queries.

	srvCfg.Pruning = "custom"
	srvCfg.PruningKeepRecent = "1000" // Keep last X committed heights (app state versions only)
	srvCfg.PruningInterval = "100"    // prune every 100 blocks
	// srvCfg.Pruning = "nothing"

	// Retain a window of recent CometBFT blocks for historical RPC (/block) access.
	// MinRetainBlocks (blockstore):
	// - Keeps recent blocks/commits/txs so /block, /commit and tx lookups work.
	// - Set this to how far back you want to serve blocks/txs (e.g., 500–1000).
	// - Does NOT affect WAL replay duration; WAL replay depends on last shutdown and
	//   how many blocks were committed since then.
	srvCfg.MinRetainBlocks = 60 * 60 * 24 / 3

	// Enable state sync snapshot production with sensible defaults
	// Snapshots are produced every 1000 blocks and we keep the last 2
	srvCfg.StateSync.SnapshotInterval = 1000
	srvCfg.StateSync.SnapshotKeepRecent = 2

	customAppConfig := CustomAppConfig{
		Config: *srvCfg,
	}

	// Append a simple [logging] section used by our app for format/level
	customAppTemplate := serverconfig.DefaultConfigTemplate + `

[logging]
# format: "plain" or "json"
format = "plain"
# level: "trace|debug|info|warn|error"
level = "info"
`

	return customAppTemplate, customAppConfig
}
