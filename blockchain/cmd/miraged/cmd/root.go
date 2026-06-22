package cmd

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"cosmossdk.io/client/v2/autocli"
	"cosmossdk.io/depinject"
	"cosmossdk.io/log/v2"
	"github.com/cosmos/cosmos-sdk/client"
	"github.com/cosmos/cosmos-sdk/client/config"
	"github.com/cosmos/cosmos-sdk/codec"
	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	"github.com/cosmos/cosmos-sdk/server"
	"github.com/cosmos/cosmos-sdk/types/module"
	"github.com/cosmos/cosmos-sdk/version"
	"github.com/cosmos/cosmos-sdk/x/auth/tx"
	authtxconfig "github.com/cosmos/cosmos-sdk/x/auth/tx/config"
	"github.com/cosmos/cosmos-sdk/x/auth/types"
	"github.com/spf13/cobra"

	"mirage/app"
)

// requiresConfigDir checks if a command requires a configured home directory.
// Commands that need config: start, query/q, tx, status, genesis, debug, pruning, snapshot, config, and AutoCLI module commands.
// Commands that don't need config: keys, version, help, init, query/tx with --node flag.
func requiresConfigDir(cmd *cobra.Command) bool {
	// Get the command path (e.g., "miraged keys list" or "miraged query bank balances")
	cmdPath := cmd.CommandPath()

	// Commands that explicitly don't need config
	if cmdPath == "miraged" || cmdPath == "miraged version" || cmdPath == "miraged help" {
		return false
	}

	// Commands that create config (don't need existing config)
	if strings.HasPrefix(cmdPath, "miraged init") {
		return false
	}

	// Commands that don't need config (keyring operations)
	if strings.HasPrefix(cmdPath, "miraged keys") {
		return false
	}

	// Check if --node flag is provided (query/tx commands don't need config when using --node)
	nodeFlag, _ := cmd.Flags().GetString("node")
	if nodeFlag != "" {
		// Query and tx commands with --node don't need local config
		if strings.HasPrefix(cmdPath, "miraged query ") ||
			strings.HasPrefix(cmdPath, "miraged q ") ||
			strings.HasPrefix(cmdPath, "miraged tx ") {
			return false
		}
	}

	// Commands that require config
	requiresConfig := []string{
		"miraged start",
		"miraged export",
		"miraged query",
		"miraged q",
		"miraged tx",
		"miraged status",
		"miraged genesis",
		"miraged debug",
		"miraged pruning",
		"miraged snapshot",
		"miraged config",
	}

	for _, prefix := range requiresConfig {
		if strings.HasPrefix(cmdPath, prefix) {
			return true
		}
	}

	// AutoCLI module commands (query/tx subcommands) also need config
	// These are typically module-specific commands like "miraged query bank balances"
	// or "miraged tx bank send"
	if strings.HasPrefix(cmdPath, "miraged query ") || strings.HasPrefix(cmdPath, "miraged q ") || strings.HasPrefix(cmdPath, "miraged tx ") {
		return true
	}

	// Default: don't require config (fail-safe for unknown commands)
	return false
}

// checkConfigExists verifies that the config directory exists at the given home path.
func checkConfigExists(homeDir string) error {
	if homeDir == "" {
		return fmt.Errorf("home directory not set")
	}

	configDir := filepath.Join(homeDir, "config")
	clientToml := filepath.Join(configDir, "client.toml")
	appToml := filepath.Join(configDir, "app.toml")
	cmtToml := filepath.Join(configDir, "config.toml")

	// Check if config directory exists
	if _, err := os.Stat(configDir); os.IsNotExist(err) {
		return fmt.Errorf("config directory not found at: %s", configDir)
	}

	// Check required files exist
	if _, err := os.Stat(clientToml); os.IsNotExist(err) {
		return fmt.Errorf("config file not found at: %s", clientToml)
	}
	if _, err := os.Stat(appToml); os.IsNotExist(err) {
		return fmt.Errorf("config file not found at: %s", appToml)
	}
	if _, err := os.Stat(cmtToml); os.IsNotExist(err) {
		return fmt.Errorf("config file not found at: %s", cmtToml)
	}

	return nil
}

// NewRootCmd creates a new root command for miraged. It is called once in the main function.
func NewRootCmd() *cobra.Command {
	var (
		autoCliOpts        autocli.AppOptions
		moduleBasicManager module.BasicManager
		clientCtx          client.Context
	)

	if err := depinject.Inject(
		depinject.Configs(app.AppConfig(),
			depinject.Supply(log.NewNopLogger()),
			depinject.Provide(
				ProvideClientContext,
			),
		),
		&autoCliOpts,
		&moduleBasicManager,
		&clientCtx,
	); err != nil {
		panic(err)
	}

	rootCmd := &cobra.Command{
		Use:           app.Name + "d",
		Short:         "mirage node",
		SilenceErrors: true,
		PersistentPreRunE: func(cmd *cobra.Command, _ []string) error {
			// set the default command outputs
			cmd.SetOut(cmd.OutOrStdout())
			cmd.SetErr(cmd.ErrOrStderr())

			clientCtx = clientCtx.WithCmdContext(cmd.Context()).WithViper(app.Name)
			clientCtx, err := client.ReadPersistentCommandFlags(clientCtx, cmd.Flags())
			if err != nil {
				return err
			}

			// Check if this command requires config directory
			needsConfig := requiresConfigDir(cmd)

			if needsConfig {
				// Verify config directory exists before proceeding
				homeDir := clientCtx.HomeDir
				if err := checkConfigExists(homeDir); err != nil {
					cmdName := cmd.CommandPath()
					return fmt.Errorf(
						"error: command '%s' requires a configured home directory\n%s\nplease run 'miraged init <moniker> --home %s' to initialize, or provide --home with an existing config directory",
						cmdName, err.Error(), homeDir,
					)
				}

				// Read client config for commands that need it
				clientCtx, err = config.ReadFromClientConfig(clientCtx)
				if err != nil {
					return err
				}
			} else {
				// For commands that don't need config, try to read it but ignore errors
				// This allows commands like 'keys' to work with OS keyring without config
				clientCtx, _ = config.ReadFromClientConfig(clientCtx)
			}

			if err := client.SetCmdClientContextHandler(clientCtx, cmd); err != nil {
				return err
			}

			// DO NOT redirect stdout/stderr here - this runs for ALL commands
			// Log rotation is only enabled in the start command's RunE (see commands.go)
			// This ensures client commands (tx, query, keys, etc.) output to stdout/stderr directly

			// Skip heavy config initialization for commands that don't need it,
			// EXCEPT commands that generate configuration (e.g. "init"). For those
			// we must still provide our custom defaults so the generated app.toml
			// contains the desired values (like minimum-gas-prices).
			if !needsConfig {
				cmdPath := cmd.CommandPath()
				generatesConfig := strings.HasPrefix(cmdPath, "miraged init")
				if generatesConfig {
					customAppTemplate, customAppConfig := initAppConfig()
					customCMTConfig := initCometBFTConfig()
					return server.InterceptConfigsPreRunHandler(cmd, customAppTemplate, customAppConfig, customCMTConfig)
				}
				return nil
			}

			customAppTemplate, customAppConfig := initAppConfig()
			customCMTConfig := initCometBFTConfig()

			return server.InterceptConfigsPreRunHandler(cmd, customAppTemplate, customAppConfig, customCMTConfig)
		},
	}

	initRootCmd(rootCmd, clientCtx.TxConfig, moduleBasicManager)

	// Add version command
	rootCmd.AddCommand(version.NewVersionCommand())

	if err := autoCliOpts.EnhanceRootCommand(rootCmd); err != nil {
		panic(err)
	}

	// Hide global logging flags from help to enforce config-file-only behavior
	for _, name := range []string{"log_format", "log_level", "log_no_color"} {
		if f := rootCmd.PersistentFlags().Lookup(name); f != nil {
			_ = rootCmd.PersistentFlags().MarkHidden(name)
		}
	}

	return rootCmd
}

// ProvideClientContext creates and provides a fully initialized client.Context,
// allowing it to be used for dependency injection and CLI operations.
func ProvideClientContext(
	appCodec codec.Codec,
	interfaceRegistry codectypes.InterfaceRegistry,
	txConfigOpts tx.ConfigOptions,
	legacyAmino *codec.LegacyAmino,
) client.Context {
	clientCtx := client.Context{}.
		WithCodec(appCodec).
		WithInterfaceRegistry(interfaceRegistry).
		WithLegacyAmino(legacyAmino).
		WithInput(os.Stdin).
		WithAccountRetriever(types.AccountRetriever{}).
		WithHomeDir(app.DefaultNodeHome).
		WithViper(app.Name) // env variable prefix

	// Read the config again to overwrite the default values with the values from the config file
	clientCtx, _ = config.ReadFromClientConfig(clientCtx)

	// textual is enabled by default, we need to re-create the tx config grpc instead of bank keeper.
	txConfigOpts.TextualCoinMetadataQueryFn = authtxconfig.NewGRPCCoinMetadataQueryFn(clientCtx)
	txConfig, err := tx.NewTxConfigWithOptions(clientCtx.Codec, txConfigOpts)
	if err != nil {
		panic(err)
	}
	clientCtx = clientCtx.WithTxConfig(txConfig)

	return clientCtx
}
