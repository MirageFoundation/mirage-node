package cmd

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/spf13/cobra"
	"github.com/spf13/pflag"
	"github.com/spf13/viper"

	"cosmossdk.io/log"
	confixcmd "cosmossdk.io/tools/confix/cmd"
	dbm "github.com/cosmos/cosmos-db"
	"github.com/cosmos/cosmos-sdk/client"
	"github.com/cosmos/cosmos-sdk/client/debug"
	"github.com/cosmos/cosmos-sdk/client/flags"
	"github.com/cosmos/cosmos-sdk/client/keys"
	"github.com/cosmos/cosmos-sdk/client/pruning"
	"github.com/cosmos/cosmos-sdk/client/rpc"
	"github.com/cosmos/cosmos-sdk/client/snapshot"
	"github.com/cosmos/cosmos-sdk/server"
	serverconfig "github.com/cosmos/cosmos-sdk/server/config"
	servertypes "github.com/cosmos/cosmos-sdk/server/types"
	"github.com/cosmos/cosmos-sdk/types/module"
	authcmd "github.com/cosmos/cosmos-sdk/x/auth/client/cli"
	genutilcli "github.com/cosmos/cosmos-sdk/x/genutil/client/cli"

	"mirage/app"
	coremodule "mirage/x/core/module"
)

func initRootCmd(
	rootCmd *cobra.Command,
	txConfig client.TxConfig,
	basicManager module.BasicManager,
) {
	// Build and sanitize init command (minimal flags & help)
	initCmd := genutilcli.InitCmd(basicManager, app.DefaultNodeHome)
	// Allow only --home and --recover for init; hide all others
	initAllow := map[string]bool{"home": true, "recover": true}
	hideNonAllowed := func(fs *pflag.FlagSet) {
		if fs == nil {
			return
		}
		fs.VisitAll(func(f *pflag.Flag) {
			if !initAllow[f.Name] {
				_ = fs.MarkHidden(f.Name)
			}
		})
	}
	hideNonAllowed(initCmd.Flags())
	hideNonAllowed(initCmd.InheritedFlags())
	// Minimal help/usage for init
	initCmd.SetHelpFunc(func(cmd *cobra.Command, args []string) {
		w := cmd.OutOrStdout()
		fmt.Fprintln(w, "Initialize node configuration files under HOME/config.")
		fmt.Fprintln(w)
		fmt.Fprintln(w, "Usage:")
		fmt.Fprintln(w, "  miraged init <moniker> [--home <path>] [--recover]")
		fmt.Fprintln(w)
		fmt.Fprintln(w, "Flags:")
		fmt.Fprintf(w, "  --home string    The application home directory (default \"%s\")\n", app.DefaultNodeHome)
		fmt.Fprintln(w, "  --recover        Recover existing key from seed phrase")
	})
	initCmd.SetUsageFunc(func(cmd *cobra.Command) error {
		w := cmd.OutOrStderr()
		fmt.Fprintln(w)
		fmt.Fprintln(w, "Usage:\n\n  miraged init <moniker> [--home <path>] [--recover]")
		fmt.Fprintln(w)
		fmt.Fprintln(w, "Flags:\n\n  --home string\tThe application home directory (default \""+app.DefaultNodeHome+"\")\n  --recover\t\tRecover existing key from seed phrase")
		return nil
	})
	// Force chain-id to mirage-1 regardless of any hidden flag; ignore non-allowed flags
	initOriginalRunE := initCmd.RunE
	initCmd.RunE = func(cmd *cobra.Command, args []string) error {
		_ = cmd.Flags().Set("chain-id", "mirage-1")
		if initOriginalRunE != nil {
			return initOriginalRunE(cmd, args)
		}
		initCmd.Run(cmd, args)
		return nil
	}

	rootCmd.AddCommand(
		initCmd,
		debug.Cmd(),
		confixcmd.ConfigCommand(),
		pruning.Cmd(newApp, app.DefaultNodeHome),
		snapshot.Cmd(newApp),
	)

	// Add offline export command (app state and validators)
	rootCmd.AddCommand(server.ExportCmd(appExport, app.DefaultNodeHome))

	// Add start command with validation
	startCmd := server.StartCmd(newApp, app.DefaultNodeHome)
	addModuleInitFlags(startCmd)

	// Remove runtime flags entirely: we rely strictly on config files
	// Allowlist only "home"; hide everything else and ban its usage
	allow := map[string]bool{"home": true}

	// Helper to hide non-allowed flags in a FlagSet
	_hideNonAllowed := func(fs *pflag.FlagSet) {
		if fs == nil {
			return
		}
		fs.VisitAll(func(f *pflag.Flag) {
			if !allow[f.Name] {
				_ = fs.MarkHidden(f.Name)
			}
		})
	}
	// Hide local and inherited flags
	_hideNonAllowed(startCmd.Flags())
	_hideNonAllowed(startCmd.InheritedFlags())

	// Minimal help for start: show only optional --home
	startCmd.SetHelpFunc(func(cmd *cobra.Command, args []string) {
		w := cmd.OutOrStdout()
		fmt.Fprintln(w, "Run the full node application using configuration files under HOME/config.")
		fmt.Fprintln(w)
		fmt.Fprintln(w, "Usage:")
		fmt.Fprintln(w, "  miraged start [--home <path>]")
		fmt.Fprintln(w)
		fmt.Fprintln(w, "Flags:")
		fmt.Fprintf(w, "  --home string\tThe application home directory (default \"%s\")\n", app.DefaultNodeHome)
	})

	// Minimal usage for start (used when errors occur and Cobra prints usage)
	startCmd.SetUsageFunc(func(cmd *cobra.Command) error {
		w := cmd.OutOrStderr()
		fmt.Fprintln(w)
		fmt.Fprintln(w, "Usage:\n\n  miraged start [--home <path>]")
		fmt.Fprintln(w)
		fmt.Fprintln(w, "Flags:\n\n  --home string\tThe application home directory (default \""+app.DefaultNodeHome+"\")")
		return nil
	})

	// Wrap the RunE to add validation before starting
	originalRunE := startCmd.RunE
	startCmd.RunE = func(cmd *cobra.Command, args []string) error {
		if err := validateAppConfig(cmd, args); err != nil {
			return err
		}
		// Log rotation handled by shell (cronolog) in entrypoint.sh
		if originalRunE != nil {
			return originalRunE(cmd, args)
		}
		// If RunE is nil, fall back to Run
		startCmd.Run(cmd, args)
		return nil
	}

	rootCmd.AddCommand(startCmd)

	// Hide global logging flags so start shows only optional --home
	for _, name := range []string{"log_format", "log_level", "log_no_color"} {
		if f := rootCmd.PersistentFlags().Lookup(name); f != nil {
			_ = rootCmd.PersistentFlags().MarkHidden(name)
		}
	}

	// Add debug command to dump effective config
	rootCmd.AddCommand(dumpConfigCommand())

	// add keybase, auxiliary RPC, query, genesis, and tx child commands
	rootCmd.AddCommand(
		server.StatusCommand(),
		genutilcli.Commands(txConfig, basicManager, app.DefaultNodeHome),
		queryCommand(),
		txCommand(),
		keys.Commands(),
	)
}

// validateAppConfig validates critical app configuration before starting the server.
// This prevents silent failures when configuration is invalid.
func validateAppConfig(cmd *cobra.Command, _ []string) error {
	// Resolve home: prefer flag, then env, else default
	homeDir := ""
	if cmd.Flags().Lookup(flags.FlagHome) != nil {
		if hval, err := cmd.Flags().GetString(flags.FlagHome); err == nil && strings.TrimSpace(hval) != "" {
			homeDir = hval
		}
	}
	if strings.TrimSpace(homeDir) == "" {
		homeDir = app.DefaultNodeHome
	}

	appConfigPath := filepath.Join(homeDir, "config", "app.toml")
	// If config files are missing, fail fast with init instruction
	if _, err := os.Stat(appConfigPath); os.IsNotExist(err) {
		cfgDir := filepath.Dir(appConfigPath)
		return errors.New(
			"FATAL: configuration files not found in " + cfgDir + "\n" +
				"Please run 'miraged init <moniker> --home " + homeDir + "' first.",
		)
	}
	appConfig, err := serverconfig.GetConfig(viper.GetViper())
	if err != nil {
		// If config file doesn't exist, that's ok (will be created on init)
		if !os.IsNotExist(err) {
			return err
		}
		return nil
	}

	// Validate minimum-gas-prices is exactly "5000umirage"
	// This is critical for v1.8.0 economics - the relay fee math expects this exact value
	minGasPrices := strings.TrimSpace(appConfig.MinGasPrices)
	const requiredMinGasPrice = "5000umirage"
	if minGasPrices != requiredMinGasPrice {
		return errors.New(
			"FATAL: minimum-gas-prices must be exactly \"" + requiredMinGasPrice + "\" in app.toml.\n" +
				"Current value: \"" + minGasPrices + "\"\n" +
				"Please update " + appConfigPath + " and set:\n" +
				"  minimum-gas-prices = \"" + requiredMinGasPrice + "\"",
		)
	}

	return nil
}

// addModuleInitFlags adds more flags to the start command.
func addModuleInitFlags(startCmd *cobra.Command) {
}

func queryCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:                        "query",
		Aliases:                    []string{"q"},
		Short:                      "Querying subcommands",
		DisableFlagParsing:         false,
		SuggestionsMinimumDistance: 2,
		RunE:                       client.ValidateCmd,
	}

	cmd.AddCommand(
		rpc.WaitTxCmd(),
		rpc.ValidatorCommand(),
		server.QueryBlockCmd(),
		authcmd.QueryTxsByEventsCmd(),
		server.QueryBlocksCmd(),
		authcmd.QueryTxCmd(),
		server.QueryBlockResultsCmd(),
		coremodule.GetQueryCmd(),
		coremodule.GetBridgeQueryCmd(),
	)

	return cmd
}

func txCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:                        "tx",
		Short:                      "Transactions subcommands",
		DisableFlagParsing:         false,
		SuggestionsMinimumDistance: 2,
		RunE:                       client.ValidateCmd,
	}

	cmd.AddCommand(
		authcmd.GetSignCommand(),
		authcmd.GetSignBatchCommand(),
		authcmd.GetMultiSignCommand(),
		authcmd.GetMultiSignBatchCmd(),
		authcmd.GetValidateSignaturesCommand(),
		flags.LineBreak,
		authcmd.GetBroadcastCommand(),
		authcmd.GetEncodeCommand(),
		authcmd.GetDecodeCommand(),
		authcmd.GetSimulateCmd(),
		coremodule.GetBridgeTxCmd(),
	)

	return cmd
}

// dumpConfigCommand prints effective configuration parsed from HOME/config files
func dumpConfigCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "dump-config",
		Short: "Print effective configuration from HOME/config files",
		RunE: func(cmd *cobra.Command, args []string) error {
			homeDir := app.DefaultNodeHome
			// Allow optional --home
			if cmd.Flags().Lookup(flags.FlagHome) != nil {
				if hval, err := cmd.Flags().GetString(flags.FlagHome); err == nil && strings.TrimSpace(hval) != "" {
					homeDir = hval
				}
			}
			cfgDir := filepath.Join(homeDir, "config")

			// Read app.toml
			appV := viper.New()
			appV.SetConfigFile(filepath.Join(cfgDir, "app.toml"))
			if err := appV.ReadInConfig(); err != nil {
				return err
			}
			// Read config.toml
			cmtV := viper.New()
			cmtV.SetConfigFile(filepath.Join(cfgDir, "config.toml"))
			if err := cmtV.ReadInConfig(); err != nil {
				return err
			}
			// Read client.toml
			cliV := viper.New()
			cliV.SetConfigFile(filepath.Join(cfgDir, "client.toml"))
			if err := cliV.ReadInConfig(); err != nil {
				return err
			}

			out := map[string]any{
				"home":  homeDir,
				"files": map[string]string{"app": appV.ConfigFileUsed(), "config": cmtV.ConfigFileUsed(), "client": cliV.ConfigFileUsed()},
				"network": map[string]any{
					"chain_id":        cliV.GetString("chain-id"),
					"keyring_backend": cliV.GetString("keyring-backend"),
					"consensus": map[string]any{
						"timeout_commit": cmtV.GetString("consensus.timeout_commit"),
					},
					"ports": map[string]any{
						"rpc_laddr": cmtV.GetString("rpc.laddr"),
						"p2p_laddr": cmtV.GetString("p2p.laddr"),
						"grpc_addr": appV.GetString("grpc.address"),
						"api_addr":  appV.GetString("api.address"),
					},
					"economics": map[string]any{
						"minimum_gas_prices": appV.GetString("minimum-gas-prices"),
					},
				},
				"logging": map[string]any{
					"format": appV.GetString("logging.format"),
					"level":  appV.GetString("logging.level"),
				},
			}
			// Encode as JSON
			enc := json.NewEncoder(os.Stdout)
			enc.SetIndent("", "  ")
			return enc.Encode(out)
		},
	}
}

// newApp creates the application
func newApp(
	logger log.Logger,
	db dbm.DB,
	traceStore io.Writer,
	appOpts servertypes.AppOptions,
) servertypes.Application {
	baseappOptions := server.DefaultBaseappOptions(appOpts)

	return app.New(
		logger, db, traceStore, true,
		appOpts,
		baseappOptions...,
	)
}

// appExport creates a new app (optionally at a given height) and exports state.
func appExport(
	logger log.Logger,
	db dbm.DB,
	traceStore io.Writer,
	height int64,
	forZeroHeight bool,
	jailAllowedAddrs []string,
	appOpts servertypes.AppOptions,
	modulesToExport []string,
) (servertypes.ExportedApp, error) {
	var bApp *app.App

	// this check is necessary as we use the flag in x/upgrade.
	// we can exit more gracefully by checking the flag here.
	homePath, ok := appOpts.Get(flags.FlagHome).(string)
	if !ok || strings.TrimSpace(homePath) == "" {
		homePath = app.DefaultNodeHome
	}

	viperAppOpts, ok := appOpts.(*viper.Viper)
	if !ok {
		return servertypes.ExportedApp{}, errors.New("appOpts is not viper.Viper")
	}

	appOpts = viperAppOpts
	if height != -1 {
		bApp = app.New(logger, db, traceStore, false, appOpts)
		if err := bApp.LoadHeight(height); err != nil {
			return servertypes.ExportedApp{}, err
		}
	} else {
		bApp = app.New(logger, db, traceStore, true, appOpts)
	}

	return bApp.ExportAppStateAndValidators(forZeroHeight, jailAllowedAddrs, modulesToExport)
}
