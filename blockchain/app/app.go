package app

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"io"
	"os"
	"path/filepath"

	clienthelpers "cosmossdk.io/client/v2/helpers"
	"cosmossdk.io/core/appmodule"
	"cosmossdk.io/depinject"
	"cosmossdk.io/log"
	storetypes "cosmossdk.io/store/types"
	circuitkeeper "cosmossdk.io/x/circuit/keeper"
	upgradekeeper "cosmossdk.io/x/upgrade/keeper"

	errorsmod "cosmossdk.io/errors"
	abci "github.com/cometbft/cometbft/abci/types"
	dbm "github.com/cosmos/cosmos-db"
	"github.com/cosmos/cosmos-sdk/baseapp"
	"github.com/cosmos/cosmos-sdk/client"
	"github.com/cosmos/cosmos-sdk/codec"
	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	ed25519sdk "github.com/cosmos/cosmos-sdk/crypto/keys/ed25519"
	"github.com/cosmos/cosmos-sdk/runtime"
	"github.com/cosmos/cosmos-sdk/server"
	"github.com/cosmos/cosmos-sdk/server/api"
	"github.com/cosmos/cosmos-sdk/server/config"
	servertypes "github.com/cosmos/cosmos-sdk/server/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/cosmos/cosmos-sdk/types/module"
	"github.com/cosmos/cosmos-sdk/x/auth"
	authante "github.com/cosmos/cosmos-sdk/x/auth/ante"
	authkeeper "github.com/cosmos/cosmos-sdk/x/auth/keeper"
	authsims "github.com/cosmos/cosmos-sdk/x/auth/simulation"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	authzkeeper "github.com/cosmos/cosmos-sdk/x/authz/keeper"
	bankkeeper "github.com/cosmos/cosmos-sdk/x/bank/keeper"
	consensuskeeper "github.com/cosmos/cosmos-sdk/x/consensus/keeper"
	distrkeeper "github.com/cosmos/cosmos-sdk/x/distribution/keeper"
	"github.com/cosmos/cosmos-sdk/x/genutil"
	genutiltypes "github.com/cosmos/cosmos-sdk/x/genutil/types"
	govkeeper "github.com/cosmos/cosmos-sdk/x/gov/keeper"
	mintkeeper "github.com/cosmos/cosmos-sdk/x/mint/keeper"
	paramskeeper "github.com/cosmos/cosmos-sdk/x/params/keeper"
	paramstypes "github.com/cosmos/cosmos-sdk/x/params/types"
	slashingkeeper "github.com/cosmos/cosmos-sdk/x/slashing/keeper"
	stakingkeeper "github.com/cosmos/cosmos-sdk/x/staking/keeper"
	stakingtypes "github.com/cosmos/cosmos-sdk/x/staking/types"
	icacontrollerkeeper "github.com/cosmos/ibc-go/v10/modules/apps/27-interchain-accounts/controller/keeper"
	icahostkeeper "github.com/cosmos/ibc-go/v10/modules/apps/27-interchain-accounts/host/keeper"
	ibctransferkeeper "github.com/cosmos/ibc-go/v10/modules/apps/transfer/keeper"
	ibckeeper "github.com/cosmos/ibc-go/v10/modules/core/keeper"

	"mirage/docs"
	corekeeper "mirage/x/core/keeper"
	coretypes "mirage/x/core/types"
)

const (
	// Name is the name of the application.
	Name = "mirage"
	// AccountAddressPrefix is the prefix for accounts addresses.
	AccountAddressPrefix = "mirage"
	// ChainCoinType is the coin type of the chain.
	ChainCoinType = 118
)

// DefaultNodeHome default home directories for the application daemon
var DefaultNodeHome string

var (
	_ runtime.AppI            = (*App)(nil)
	_ servertypes.Application = (*App)(nil)
)

// App extends an ABCI application, but with most of its parameters exported.
// They are exported for convenience in creating helper functions, as object
// capabilities aren't needed for testing.
type App struct {
	*runtime.App
	legacyAmino       *codec.LegacyAmino
	appCodec          codec.Codec
	txConfig          client.TxConfig
	interfaceRegistry codectypes.InterfaceRegistry

	// keepers
	// only keepers required by the app are exposed
	// the list of all modules is available in the app_config
	AuthKeeper            authkeeper.AccountKeeper
	BankKeeper            bankkeeper.Keeper
	StakingKeeper         *stakingkeeper.Keeper
	SlashingKeeper        slashingkeeper.Keeper
	MintKeeper            mintkeeper.Keeper
	DistrKeeper           distrkeeper.Keeper
	GovKeeper             *govkeeper.Keeper
	UpgradeKeeper         *upgradekeeper.Keeper
	AuthzKeeper           authzkeeper.Keeper
	ConsensusParamsKeeper consensuskeeper.Keeper
	CircuitBreakerKeeper  circuitkeeper.Keeper
	ParamsKeeper          paramskeeper.Keeper
	CoreKeeper            corekeeper.Keeper

	// ibc keepers
	IBCKeeper           *ibckeeper.Keeper
	ICAControllerKeeper icacontrollerkeeper.Keeper
	ICAHostKeeper       icahostkeeper.Keeper
	TransferKeeper      ibctransferkeeper.Keeper

	// Posts module removed. No keeper.
	// this line is used by starport scaffolding # stargate/app/keeperDeclaration

	// simulation manager
	sm *module.SimulationManager
}

func init() {
	// Set prefixes
	accountPubKeyPrefix := AccountAddressPrefix + "pub"
	validatorAddressPrefix := AccountAddressPrefix + "valoper"
	validatorPubKeyPrefix := AccountAddressPrefix + "valoperpub"
	consNodeAddressPrefix := AccountAddressPrefix + "valcons"
	consNodePubKeyPrefix := AccountAddressPrefix + "valconspub"

	// Set and seal config
	config := sdk.GetConfig()
	config.SetCoinType(ChainCoinType)
	config.SetBech32PrefixForAccount(AccountAddressPrefix, accountPubKeyPrefix)
	config.SetBech32PrefixForValidator(validatorAddressPrefix, validatorPubKeyPrefix)
	config.SetBech32PrefixForConsensusNode(consNodeAddressPrefix, consNodePubKeyPrefix)
	config.Seal()

	// Follow Cosmos SDK norm: base denom uses micro prefix (u)
	// Base denom for staking and fees
	sdk.DefaultBondDenom = "umirage"

	clienthelpers.EnvPrefix = Name
	DefaultNodeHome = filepath.Join(os.Getenv("HOME"), ".mirage", "main")
}

// AppConfig returns the default app config.
func AppConfig() depinject.Config {
	return depinject.Configs(
		appConfig,
		depinject.Supply(
			// supply custom module basics
			map[string]module.AppModuleBasic{
				genutiltypes.ModuleName: genutil.NewAppModuleBasic(genutiltypes.DefaultMessageValidator),
			},
		),
	)
}

// New returns a reference to an initialized App.
func New(
	logger log.Logger,
	db dbm.DB,
	traceStore io.Writer,
	loadLatest bool,
	appOpts servertypes.AppOptions,
	baseAppOptions ...func(*baseapp.BaseApp),
) *App {
	var (
		app        = &App{}
		appBuilder *runtime.AppBuilder

		// merge the AppConfig and other configuration in one config
		appConfig = depinject.Configs(
			AppConfig(),
			depinject.Supply(
				appOpts, // supply app options
				logger,  // supply logger
			),
			// Custom signers removed - now using cosmos.msg.v1.signer annotation in proto files
		)
	)

	var appModules map[string]appmodule.AppModule
	if err := depinject.Inject(appConfig,
		&appBuilder,
		&appModules,
		&app.appCodec,
		&app.legacyAmino,
		&app.txConfig,
		&app.interfaceRegistry,
		&app.AuthKeeper,
		&app.BankKeeper,
		&app.StakingKeeper,
		&app.SlashingKeeper,
		&app.MintKeeper,
		&app.DistrKeeper,
		&app.GovKeeper,
		&app.UpgradeKeeper,
		&app.AuthzKeeper,
		&app.ConsensusParamsKeeper,
		&app.CircuitBreakerKeeper,
		&app.ParamsKeeper,
		&app.CoreKeeper,
	); err != nil {
		panic(err)
	}

	// Register core message types so the tx decoder can resolve /mirage.core.v1 messages
	coretypes.RegisterInterfaces(app.interfaceRegistry)

	// Also register into the codec's registry if exposed
	if pc, ok := app.appCodec.(interface {
		InterfaceRegistry() codectypes.InterfaceRegistry
	}); ok {
		coretypes.RegisterInterfaces(pc.InterfaceRegistry())
	}

	// add to default baseapp options
	// Optimistic execution disabled - causes hash mismatches due to non-determinism
	// baseAppOptions = append(baseAppOptions, baseapp.SetOptimisticExecution())

	// build app
	app.App = appBuilder.Build(db, traceStore, baseAppOptions...)

	// Signature-less ante chain for relay flow
	if app.App != nil {
		if base := app.App.GetBaseApp(); base != nil {
			// Build a minimal auth ante chain skipping tx-level signature verification
			sigless := sdk.ChainAnteDecorators(
				authante.NewSetUpContextDecorator(),
				authante.NewTxTimeoutHeightDecorator(),
				authante.NewConsumeGasForTxSizeDecorator(app.AuthKeeper),
			)

			ensure := NewEnsureAccountsDecorator(app.AuthKeeper)

			// Initialize PowDecorator (params will be refreshed at runtime)
			powDec := &PowDecorator{
				Window:            60,         // Initial value, will be updated from params
				DefaultDifficulty: 10,         // Initial value, will be updated to current difficulty
				MinFee:            sdk.Coin{}, // do not skip PoW based on SDK fee; node pays gas separately
				Keeper:            app.CoreKeeper,
			}
			meta := RelaySigDecorator{Keeper: app.CoreKeeper}
			metaFees := RelayGasFeeDecorator{BankKeeper: app.BankKeeper}
			accDec := RelayAccountingDecorator{Keeper: app.CoreKeeper}
			logDec := LoggingDecorator{}
			disableDel := DisableDelegatorStakingDecorator{}

			// Build the standard SDK ante handler for normal (signed) txs
			stdOpts := authante.HandlerOptions{
				AccountKeeper:   app.AuthKeeper,
				BankKeeper:      app.BankKeeper,
				SignModeHandler: app.txConfig.SignModeHandler(),
				FeegrantKeeper:  nil,
				SigGasConsumer:  authante.DefaultSigVerificationGasConsumer,
			}
			stdAnte, _ := authante.NewAnteHandler(stdOpts)

			base.SetAnteHandler(func(ctx sdk.Context, tx sdk.Tx, simulate bool) (sdk.Context, error) {
				// Detect if this tx contains any relay core messages
				containsMeta := false
				for _, m := range tx.GetMsgs() {
					switch m.(type) {
					case *coretypes.MsgPost, *coretypes.MsgVote, *coretypes.MsgSetUsername,
						*coretypes.MsgFollowModerator, *coretypes.MsgUnfollowModerator,
						*coretypes.MsgFollowUser, *coretypes.MsgUnfollowUser,
						*coretypes.MsgFollowTopic, *coretypes.MsgUnfollowTopic,
						*coretypes.MsgBlockPost, *coretypes.MsgUnblockPost,
						*coretypes.MsgBlockUser, *coretypes.MsgUnblockUser,
						*coretypes.MsgDelete, *coretypes.MsgSendTokens, *coretypes.MsgEdit,
						*coretypes.MsgUpgradeLevel, *coretypes.MsgSetAutoRenewal:
						containsMeta = true
					}
				}

				if !containsMeta {
					// Use the standard SDK ante chain for normal signed txs (gas + fees + sig checks)
					ctxStd, err := stdAnte(ctx, tx, simulate)
					if err != nil {
						codespace, code, log := errorsmod.ABCIInfo(err, false)
						ctx.Logger().Warn("StdAnte rejected tx", "code", code, "codespace", codespace, "log", log)
					}
					return ctxStd, err
				}

				// Relay flow for core messages
				ctx2, err := logDec.AnteHandle(ctx, tx, simulate, func(c sdk.Context, t sdk.Tx, s bool) (sdk.Context, error) { return c, nil })
				if err != nil {
					return ctx2, err
				}
				ctx3, err := ensure.AnteHandle(ctx2, tx, simulate, func(c sdk.Context, t sdk.Tx, s bool) (sdk.Context, error) { return c, nil })
				if err != nil {
					return ctx3, err
				}
				ctx3b, err := metaFees.AnteHandle(ctx3, tx, simulate, func(c sdk.Context, t sdk.Tx, s bool) (sdk.Context, error) { return c, nil })
				if err != nil {
					return ctx3b, err
				}
				ctx3c, err := accDec.AnteHandle(ctx3b, tx, simulate, func(c sdk.Context, t sdk.Tx, s bool) (sdk.Context, error) { return c, nil })
				if err != nil {
					return ctx3c, err
				}
				// Proceed to PoW checks; SDK's ConsumeGasForTxSize already charges for tx size
				ctx4, err := powDec.AnteHandle(ctx3c, tx, simulate, func(c sdk.Context, t sdk.Tx, s bool) (sdk.Context, error) { return c, nil })
				if err != nil {
					return ctx4, err
				}
				ctx4b, err := disableDel.AnteHandle(ctx4, tx, simulate, func(c sdk.Context, t sdk.Tx, s bool) (sdk.Context, error) { return c, nil })
				if err != nil {
					return ctx4b, err
				}
				ctx5, err := meta.AnteHandle(ctx4b, tx, simulate, func(c sdk.Context, t sdk.Tx, s bool) (sdk.Context, error) { return c, nil })
				if err != nil {
					return ctx5, err
				}
				return sigless(ctx5, tx, simulate)
			})

			// Always propose all txs and accept proposals to avoid filtering in proposal phases
			base.SetPrepareProposal(func(ctx sdk.Context, req *abci.RequestPrepareProposal) (*abci.ResponsePrepareProposal, error) {
				return &abci.ResponsePrepareProposal{Txs: req.Txs}, nil
			})
			base.SetProcessProposal(func(ctx sdk.Context, req *abci.RequestProcessProposal) (*abci.ResponseProcessProposal, error) {
				resp := &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_ACCEPT}
				return resp, nil
			})
		}
	}

	// register legacy modules
	if err := app.registerIBCModules(appOpts); err != nil {
		panic(err)
	}

	// Register upgrade handlers
	app.RegisterUpgradeHandlers()

	/****  Module Options ****/

	// create the simulation manager and define the order of the modules for deterministic simulations
	overrideModules := map[string]module.AppModuleSimulation{
		authtypes.ModuleName: auth.NewAppModule(app.appCodec, app.AuthKeeper, authsims.RandomGenesisAccounts, nil),
	}
	app.sm = module.NewSimulationManagerFromAppModules(app.ModuleManager.Modules, overrideModules)

	app.sm.RegisterStoreDecoders()

	// A custom InitChainer sets if extra pre-init-genesis logic is required.
	// This is necessary for manually registered modules that do not support app wiring.
	// Manually set the module version map as shown below.
	// The upgrade module will automatically handle de-duplication of the module version map.
	app.SetInitChainer(func(ctx sdk.Context, req *abci.RequestInitChain) (*abci.ResponseInitChain, error) {
		if err := app.UpgradeKeeper.SetModuleVersionMap(ctx, app.ModuleManager.GetVersionMap()); err != nil {
			return nil, err
		}
		// Post-init hard check: ensure local consensus pubkey is a validator (uses in-state staking, not genesis)
		if homeRaw := appOpts.Get("home"); homeRaw != nil {
			if home, ok := homeRaw.(string); ok && home != "" {
				pvPath := filepath.Join(home, "config", "priv_validator_key.json")
				pvBz, err := os.ReadFile(pvPath)
				if err == nil {
					var pv map[string]any
					if json.Unmarshal(pvBz, &pv) == nil {
						if pkMap, _ := pv["pub_key"].(map[string]any); pkMap != nil {
							if valB64, _ := pkMap["value"].(string); valB64 != "" {
								if local, err := base64.StdEncoding.DecodeString(valB64); err == nil {
									// iterate current validators from staking keeper
									// Use current context directly; InitChain runs before any blocks, so bonded set may be empty on fresh init
									sctx := ctx
									_ = app.StakingKeeper.IterateValidators(sctx, func(_ int64, valI stakingtypes.ValidatorI) (stop bool) {
										v, ok := valI.(stakingtypes.Validator)
										if !ok {
											return false
										}
										cp := v.ConsensusPubkey
										if cp == nil || cp.TypeUrl != "/cosmos.crypto.ed25519.PubKey" {
											return false
										}
										// cp.Value is amino/json encoded of ed25519 pubkey? In SDK 0.53 it holds proto bytes of ed25519sdk.PubKey
										var ed ed25519sdk.PubKey
										if err := ed.Unmarshal(cp.Value); err != nil {
											return false
										}
										if bytes.Equal(ed.Key, local) {
											stop = true
										}
										return stop
									})
								}
							}
						}
					}
				}
			}
		}
		return app.App.InitChainer(ctx, req)
	})

	if err := app.Load(loadLatest); err != nil {
		panic(err)
	}

	return app
}

// ProvideCustomGetSigners removed - now using cosmos.msg.v1.signer annotation in proto files
// The authority field in each message is automatically used as the signer by the SDK

// GetSubspace returns a param subspace for a given module name.
func (app *App) GetSubspace(moduleName string) paramstypes.Subspace {
	subspace, _ := app.ParamsKeeper.GetSubspace(moduleName)
	return subspace
}

// LegacyAmino returns App's amino codec.
func (app *App) LegacyAmino() *codec.LegacyAmino {
	return app.legacyAmino
}

// AppCodec returns App's app codec.
func (app *App) AppCodec() codec.Codec {
	return app.appCodec
}

// InterfaceRegistry returns App's InterfaceRegistry.
func (app *App) InterfaceRegistry() codectypes.InterfaceRegistry {
	return app.interfaceRegistry
}

// TxConfig returns App's TxConfig
func (app *App) TxConfig() client.TxConfig {
	return app.txConfig
}

// GetKey returns the KVStoreKey for the provided store key.
func (app *App) GetKey(storeKey string) *storetypes.KVStoreKey {
	kvStoreKey, ok := app.UnsafeFindStoreKey(storeKey).(*storetypes.KVStoreKey)
	if !ok {
		return nil
	}
	return kvStoreKey
}

// SimulationManager implements the SimulationApp interface
func (app *App) SimulationManager() *module.SimulationManager {
	return app.sm
}

// RegisterAPIRoutes registers all application module routes with the provided
// API server.
func (app *App) RegisterAPIRoutes(apiSvr *api.Server, apiConfig config.APIConfig) {
	app.App.RegisterAPIRoutes(apiSvr, apiConfig)
	// register swagger API in app.go so that other applications can override easily
	if err := server.RegisterSwaggerAPI(apiSvr.ClientCtx, apiSvr.Router, apiConfig.Swagger); err != nil {
		panic(err)
	}

	// register app's OpenAPI routes.
	docs.RegisterOpenAPIService(Name, apiSvr.Router)
}

// GetMaccPerms returns a copy of the module account permissions
//
// NOTE: This is solely to be used for testing purposes.
func GetMaccPerms() map[string][]string {
	dup := make(map[string][]string)
	for _, perms := range moduleAccPerms {
		dup[perms.GetAccount()] = perms.GetPermissions()
	}

	return dup
}

// BlockedAddresses returns all the app's blocked account addresses.
func BlockedAddresses() map[string]bool {
	result := make(map[string]bool)

	if len(blockAccAddrs) > 0 {
		for _, addr := range blockAccAddrs {
			result[addr] = true
		}
	} else {
		for addr := range GetMaccPerms() {
			result[addr] = true
		}
	}

	return result
}
