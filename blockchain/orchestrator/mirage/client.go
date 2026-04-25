package mirage

// =============================================================================
// DORMANT - Bridge / Orchestrator (offline since v1.20.0)
//
// The off-chain orchestrator is intentionally OFFLINE. Its main binary is
// hard-disabled at startup (panic guard in blockchain/cmd/orchestrator/main.go)
// and no validator currently runs it. The Mirage gRPC/RPC client wired here is
// not connected in production. The code is retained to keep the package
// compilable and preserve the design while a bridge replacement is being
// scoped.
//
// SECURITY-REVIEW SCOPE: bridge / orchestrator findings are accepted-and-
// deferred. They are tracked in docs/security/blockchain/review-2026-04-24.md
// under "Outstanding bridge-scope" and will be revisited in a dedicated audit
// only when the bridge is reactivated. Do NOT surface findings from this file
// in live remediation queues until that time.
// =============================================================================

import (
	"context"
	"fmt"
	"log"
	"os"

	"cosmossdk.io/depinject"
	cosmoslog "cosmossdk.io/log"
	"github.com/cometbft/cometbft/rpc/client/http"
	"github.com/cosmos/cosmos-sdk/client"
	"github.com/cosmos/cosmos-sdk/codec"
	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	"github.com/cosmos/cosmos-sdk/crypto/keyring"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/cosmos/cosmos-sdk/x/auth/tx"
	authtxconfig "github.com/cosmos/cosmos-sdk/x/auth/tx/config"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"

	"mirage/app"
	"mirage/orchestrator/config"
)

type Client struct {
	cfg              *config.Config
	logger           *log.Logger
	grpcConn         *grpc.ClientConn
	rpcClient        *http.HTTP
	clientCtx        client.Context
	keyring          keyring.Keyring
	fromAddress      string
	accountRetriever authtypes.AccountRetriever
	appCodec         codec.Codec
}

func NewClient(ctx context.Context, cfg *config.Config, logger *log.Logger) (*Client, error) {
	clientCtx, appCodec, err := buildClientContext()
	if err != nil {
		return nil, err
	}
	clientCtx = clientCtx.WithChainID(cfg.Mirage.ChainID)

	keyringBackend := cfg.Mirage.KeyringBackend
	keyringDir := cfg.Mirage.KeyringDir
	kr, err := keyring.New(app.Name, keyringBackend, keyringDir, os.Stdin, appCodec)
	if err != nil {
		return nil, fmt.Errorf("failed to init keyring: %w", err)
	}
	keyInfo, err := kr.Key(cfg.Mirage.KeyName)
	if err != nil {
		return nil, fmt.Errorf("failed to load key %s: %w", cfg.Mirage.KeyName, err)
	}
	fromAddr, err := keyInfo.GetAddress()
	if err != nil {
		return nil, fmt.Errorf("failed to read key address: %w", err)
	}

	clientCtx = clientCtx.WithKeyring(kr).WithFromName(cfg.Mirage.KeyName).WithFromAddress(fromAddr)

	var transportCreds grpc.DialOption
	if cfg.Mirage.TLS {
		transportCreds = grpc.WithTransportCredentials(credentials.NewClientTLSFromCert(nil, ""))
	} else {
		transportCreds = grpc.WithTransportCredentials(insecure.NewCredentials())
	}
	grpcConn, err := grpc.DialContext(ctx, cfg.Mirage.GRPC, transportCreds)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to gRPC: %w", err)
	}

	rpcClient, err := http.New(cfg.Mirage.RPC, "/websocket")
	if err != nil {
		return nil, fmt.Errorf("failed to connect to RPC: %w", err)
	}
	// Don't set logger - CometBFT HTTP client doesn't expose SetLogger in v0.38

	logger.Printf("DEBUG mirage client ready: from=%s chain_id=%s", fromAddr.String(), cfg.Mirage.ChainID)

	return &Client{
		cfg:              cfg,
		logger:           logger,
		grpcConn:         grpcConn,
		rpcClient:        rpcClient,
		clientCtx:        clientCtx,
		keyring:          kr,
		fromAddress:      fromAddr.String(),
		accountRetriever: authtypes.AccountRetriever{},
		appCodec:         appCodec,
	}, nil
}

func (c *Client) Close() {
	if c.grpcConn != nil {
		_ = c.grpcConn.Close()
	}
}

func (c *Client) RPC() *http.HTTP {
	return c.rpcClient
}

func (c *Client) ClientContext() client.Context {
	return c.clientCtx.WithGRPCClient(c.grpcConn)
}

func (c *Client) FromAddress() string {
	return c.fromAddress
}

// ValoperAddress returns the validator operator address derived from the account address.
// Used for logging/display purposes only - the module handles acc→valoper conversion.
func (c *Client) ValoperAddress() string {
	addr := c.ClientContext().GetFromAddress()
	return sdk.ValAddress(addr).String()
}

func buildClientContext() (client.Context, codec.Codec, error) {
	var clientCtx client.Context
	var appCodec codec.Codec

	if err := depinject.Inject(
		depinject.Configs(app.AppConfig(),
			depinject.Supply(cosmoslog.NewNopLogger()),
			depinject.Provide(
				ProvideClientContext,
			),
		),
		&clientCtx,
		&appCodec,
	); err != nil {
		return client.Context{}, nil, fmt.Errorf("failed to build client context: %w", err)
	}

	return clientCtx, appCodec, nil
}

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
		WithAccountRetriever(authtypes.AccountRetriever{}).
		WithHomeDir(app.DefaultNodeHome)

	txConfigOpts.TextualCoinMetadataQueryFn = authtxconfig.NewGRPCCoinMetadataQueryFn(clientCtx)
	txConfig, err := tx.NewTxConfigWithOptions(clientCtx.Codec, txConfigOpts)
	if err != nil {
		panic(err)
	}
	clientCtx = clientCtx.WithTxConfig(txConfig)

	return clientCtx
}
