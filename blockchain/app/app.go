package app

import (
	"bytes"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	clienthelpers "cosmossdk.io/client/v2/helpers"
	"cosmossdk.io/core/appmodule"
	"cosmossdk.io/depinject"
	"cosmossdk.io/log/v2"
	storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
	upgradekeeper "github.com/cosmos/cosmos-sdk/x/upgrade/keeper"

	"mirage/docs"
	corekeeper "mirage/x/core/keeper"
	coretypes "mirage/x/core/types"

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
	govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"
	mintkeeper "github.com/cosmos/cosmos-sdk/x/mint/keeper"
	paramskeeper "github.com/cosmos/cosmos-sdk/x/params/keeper"
	paramstypes "github.com/cosmos/cosmos-sdk/x/params/types"
	slashingkeeper "github.com/cosmos/cosmos-sdk/x/slashing/keeper"
	stakingkeeper "github.com/cosmos/cosmos-sdk/x/staking/keeper"
	stakingtypes "github.com/cosmos/cosmos-sdk/x/staking/types"
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
	ParamsKeeper          paramskeeper.Keeper
	CoreKeeper            corekeeper.Keeper

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
	DefaultNodeHome = filepath.Join(os.Getenv("HOME"), ".mirage", "node")
}

// mirageAnteRouter is the ante handler installed on baseapp. It enforces
// cross-cutting policies that must apply to EVERY tx regardless of whether
// the tx eventually routes to the standard SDK ante chain or to the relay
// ante chain.
//
// Order matters here:
//  1. rejectDelegatorStakingMsgs runs FIRST so staking-disable policy is
//     enforced on both paths. Historical bug: this used to live inside the
//     relay chain only, which meant a pure non-relay `MsgUndelegate` /
//     `MsgCancelUnbondingDelegation` submitted via CLI bypassed it entirely.
//  2. Mixed relay + non-relay txs are rejected to prevent signature bypass.
//  3. Pure non-relay txs go to stdAnte (wrapped by govDec).
//  4. Pure relay txs go to relayAnte.
func mirageAnteRouter(
	ctx sdk.Context,
	tx sdk.Tx,
	simulate bool,
	govDec GovAuthorityDecorator,
	stdAnte sdk.AnteHandler,
	relayAnte sdk.AnteHandler,
) (sdk.Context, error) {
	if err := rejectDelegatorStakingMsgs(tx); err != nil {
		return ctx, err
	}

	isRelayTx := false
	hasNonRelay := false
	msgTypes := make([]string, 0, len(tx.GetMsgs()))
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	for _, m := range tx.GetMsgs() {
		msgTypes = append(msgTypes, sdk.MsgTypeURL(m))
		if am, ok := m.(interface{ GetAuthority() string }); ok {
			if strings.TrimSpace(am.GetAuthority()) == govAuthority {
				isRelayTx = false
				hasNonRelay = false
				break
			}
		}
		if isRelayMessage(m) {
			isRelayTx = true
		} else {
			hasNonRelay = true
		}
	}

	if isRelayTx && hasNonRelay {
		ctx.Logger().Error("ante: rejected mixed relay + non-relay tx", "msg_types", msgTypes)
		return ctx, fmt.Errorf("transactions cannot mix relay and non-relay messages")
	}

	if !isRelayTx {
		ctx.Logger().Debug("Relay ante: using standard ante", "msg_types", msgTypes)
		ctxStd, err := govDec.AnteHandle(ctx, tx, simulate, stdAnte)
		if err != nil {
			codespace, code, log := errorsmod.ABCIInfo(err, false)
			ctx.Logger().Warn("StdAnte rejected tx", "code", code, "codespace", codespace, "log", log)
		}
		return ctxStd, err
	}

	ctx.Logger().Debug("Relay ante: using relay ante", "msg_types", msgTypes)
	return relayAnte(ctx, tx, simulate)
}

// isRelayMessage returns true if the message is a relay-routed core message
// (uses envelope PoW + signature instead of standard SDK signatures).
func isRelayMessage(m sdk.Msg) bool {
	switch m.(type) {
	case *coretypes.MsgPost, *coretypes.MsgVote, *coretypes.MsgSetUsername,
		*coretypes.MsgEnableAgent, *coretypes.MsgDisableAgent, *coretypes.MsgSetAgents,
		*coretypes.MsgFollowUser, *coretypes.MsgUnfollowUser,
		*coretypes.MsgFollowTopic, *coretypes.MsgUnfollowTopic,
		*coretypes.MsgBlockPost, *coretypes.MsgUnblockPost,
		*coretypes.MsgBlockUser, *coretypes.MsgUnblockUser,
		*coretypes.MsgBlockTopic, *coretypes.MsgUnblockTopic,
		*coretypes.MsgDelete, *coretypes.MsgDeleteUser, *coretypes.MsgSendTokens, *coretypes.MsgEdit,
		*coretypes.MsgSubscribe, *coretypes.MsgSetAutoRenewal,
		*coretypes.MsgBridgeBurn, *coretypes.MsgAward,
		*coretypes.MsgSetBiography, *coretypes.MsgAnnotate:
		return true
	default:
		return false
	}
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
	app.App = appBuilder.Build(db, baseAppOptions...)

	// Signature-less ante chain for relay flow
	if app.App != nil {
		if base := app.App.GetBaseApp(); base != nil {
			// Build individual decorators for granular control
			setup := authante.NewSetUpContextDecorator()
			timeout := authante.NewTxTimeoutHeightDecorator()
			gasSize := authante.NewConsumeGasForTxSizeDecorator(app.AuthKeeper)

			ensure := NewEnsureAccountsDecorator(app.AuthKeeper)

			// Initialize PowDecorator. The recent-block-hash window is now
			// read from on-chain state (params.BlockHashWindow controls its
			// length); no per-process cache or window field is required.
			powDec := &PowDecorator{
				MinFee: sdk.Coin{}, // do not skip PoW based on SDK fee; node pays gas separately
				Keeper: app.CoreKeeper,
			}
			meta := RelaySigDecorator{Keeper: app.CoreKeeper}
			metaFees := RelayGasFeeDecorator{BankKeeper: app.BankKeeper}
			accDec := RelayAccountingDecorator{Keeper: app.CoreKeeper}
			logDec := LoggingDecorator{}
			validateBasic := authante.NewValidateBasicDecorator()
			govDec := GovAuthorityDecorator{}

			// Build the standard SDK ante handler for normal (signed) txs
			stdOpts := authante.HandlerOptions{
				AccountKeeper:   app.AuthKeeper,
				BankKeeper:      app.BankKeeper,
				SignModeHandler: app.txConfig.SignModeHandler(),
				FeegrantKeeper:  nil,
				SigGasConsumer:  authante.DefaultSigVerificationGasConsumer,
			}
			stdAnte, err := authante.NewAnteHandler(stdOpts)
			if err != nil {
				panic(fmt.Errorf("app: NewAnteHandler failed: %w", err))
			}

			// Relay ante chain (must start with SetUpContextDecorator)
			relayAnte := sdk.ChainAnteDecorators(
				setup,
				validateBasic,
				govDec,
				timeout,
				gasSize,
				logDec,
				powDec,
				ensure,
				metaFees,
				accDec,
				meta,
			)

			base.SetAnteHandler(func(ctx sdk.Context, tx sdk.Tx, simulate bool) (sdk.Context, error) {
				return mirageAnteRouter(ctx, tx, simulate, govDec, stdAnte, relayAnte)
			})

			// Always propose all txs and accept proposals to avoid filtering in proposal phases
			base.SetPrepareProposal(func(ctx sdk.Context, req *abci.RequestPrepareProposal) (*abci.ResponsePrepareProposal, error) {
				return &abci.ResponsePrepareProposal{Txs: req.Txs}, nil
			})
			base.SetProcessProposal(func(ctx sdk.Context, req *abci.RequestProcessProposal) (*abci.ResponseProcessProposal, error) {
				for _, txBytes := range req.Txs {
					if len(txBytes) == 0 {
						return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_REJECT}, nil
					}
					tx, err := app.TxConfig().TxDecoder()(txBytes)
					if err != nil {
						return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_REJECT}, nil
					}
					if len(tx.GetMsgs()) == 0 {
						return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_REJECT}, nil
					}
				}
				return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_ACCEPT}, nil
			})
		}
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

	// Fix Cosmos SDK pruning bug: state-synced nodes have a stale
	// pruneSnapshotHeights[0]=0 that caps the prune limit at
	// snapshotInterval-1, effectively disabling all IAVL pruning.
	// Must run before Load() so LoadSnapshotHeights reads the corrected data.
	if loadLatest {
		fixStalePruneSnapshotHeights(db, logger)
	}

	if err := app.Load(loadLatest); err != nil {
		panic(err)
	}

	return app
}

// fixStalePruneSnapshotHeights trims the pruning snapshot height list to just
// the most recent entry. The Cosmos SDK's pruning manager uses
// pruneSnapshotHeights[0]+snapshotInterval-1 as the prune ceiling. On
// state-synced nodes, old entries accumulate (the SDK only evicts when a new
// snapshot completes via HandleSnapshotHeight) and block all IAVL pruning.
// Keeping only the latest entry matches the steady-state after SDK eviction.
func fixStalePruneSnapshotHeights(db dbm.DB, logger log.Logger) {
	key := []byte("s/prunesnapshotheights")
	bz, err := db.Get(key)
	if err != nil {
		logger.Error("failed reading pruneSnapshotHeights", "err", err)
		panic(err)
	}
	if len(bz) == 0 {
		logger.Debug("pruneSnapshotHeights not set")
		return
	}
	if len(bz)%8 != 0 {
		err := fmt.Errorf("pruneSnapshotHeights malformed length: %d", len(bz))
		logger.Error("invalid pruneSnapshotHeights", "err", err)
		panic(err)
	}

	entries := make([]uint64, 0, len(bz)/8)
	for i := 0; i < len(bz); i += 8 {
		entries = append(entries, binary.BigEndian.Uint64(bz[i:i+8]))
	}

	if len(entries) <= 1 {
		logger.Debug("pruneSnapshotHeights already minimal", "entries", len(entries))
		return
	}

	for i := 1; i < len(entries); i++ {
		if entries[i] <= entries[i-1] {
			err := fmt.Errorf("pruneSnapshotHeights non-increasing: prev=%d cur=%d", entries[i-1], entries[i])
			logger.Error("invalid pruneSnapshotHeights", "err", err)
			panic(err)
		}
	}

	last := entries[len(entries)-1]
	fixedEntries := []uint64{last}

	logger.Info("trimming pruneSnapshotHeights to latest entry (unblock pruning)",
		"old_first", entries[0],
		"old_last", last,
		"old_entries", len(entries),
	)

	fixed := make([]byte, 0, len(fixedEntries)*8)
	for _, h := range fixedEntries {
		buf := make([]byte, 8)
		binary.BigEndian.PutUint64(buf, h)
		fixed = append(fixed, buf...)
	}

	if err := db.SetSync(key, fixed); err != nil {
		logger.Error("failed to write pruneSnapshotHeights", "err", err)
		panic(err)
	}
	logger.Debug("pruneSnapshotHeights updated")
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
