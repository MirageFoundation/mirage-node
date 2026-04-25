package core

// =============================================================================
// DORMANT - Bridge module (offline since v1.20.0)
//
// The Mirage bridge is intentionally OFFLINE. The off-chain orchestrator
// binary is hard-disabled at startup (see blockchain/cmd/orchestrator/main.go)
// and no validator runs it. No bridge_chain is currently enabled in chain
// params either. The CLI subcommands wired here still compile and respond,
// but the queries return state that is not being produced and the tx
// builders submit messages that the chain accepts only as-no-op-because-no-
// attestors-vote.
//
// SECURITY-REVIEW SCOPE: bridge / orchestrator findings are accepted-and-
// deferred. They are tracked in docs/security/blockchain/review-2026-04-24.md
// under "Outstanding bridge-scope" and will be revisited in a dedicated audit
// only when the bridge is reactivated. Do NOT surface findings from this file
// in live remediation queues until that time.
// =============================================================================

import (
	"fmt"
	"strconv"

	"github.com/cosmos/cosmos-sdk/client"
	"github.com/cosmos/cosmos-sdk/client/flags"
	"github.com/cosmos/cosmos-sdk/client/tx"
	"github.com/spf13/cobra"

	"mirage/x/core/types"
)

// GetBridgeQueryCmd returns the CLI query commands for the bridge submodule.
func GetBridgeQueryCmd() *cobra.Command {
	bridgeQueryCmd := &cobra.Command{
		Use:                        "bridge",
		Short:                      "Querying commands for the bridge module",
		DisableFlagParsing:         true,
		SuggestionsMinimumDistance: 2,
		RunE:                       client.ValidateCmd,
	}

	bridgeQueryCmd.AddCommand(
		GetCmdQueryBridgeStatus(),
		GetCmdQueryBridgeAttestation(),
		GetCmdQueryBridgeMint(),
		GetCmdQueryBridgeConfig(),
	)

	return bridgeQueryCmd
}

// GetCmdQueryBridgeMint implements the query bridge mint command.
func GetCmdQueryBridgeMint() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "mint [destination_chain] [burn_id]",
		Short: "Query mint confirmation by destination chain and burn ID",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			clientCtx, err := client.GetClientQueryContext(cmd)
			if err != nil {
				return err
			}

			queryClient := types.NewQueryClient(clientCtx)
			res, err := queryClient.GetBridgeMint(cmd.Context(), &types.QueryBridgeMintRequest{
				DestinationChain: args[0],
				BurnId:           args[1],
			})
			if err != nil {
				return err
			}

			return clientCtx.PrintProto(res)
		},
	}

	flags.AddQueryFlagsToCmd(cmd)
	return cmd
}

// GetCmdQueryBridgeStatus implements the query bridge status command.
func GetCmdQueryBridgeStatus() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "status",
		Short: "Query the current bridge status including enabled chains and pending attestations",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			clientCtx, err := client.GetClientQueryContext(cmd)
			if err != nil {
				return err
			}

			queryClient := types.NewQueryClient(clientCtx)
			res, err := queryClient.GetBridgeStatus(cmd.Context(), &types.QueryBridgeStatusRequest{})
			if err != nil {
				return err
			}

			return clientCtx.PrintProto(res)
		},
	}

	flags.AddQueryFlagsToCmd(cmd)
	return cmd
}

// GetCmdQueryBridgeAttestation implements the query bridge attestation command.
func GetCmdQueryBridgeAttestation() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "attestation [source_chain] [burn_id]",
		Short: "Query a specific bridge attestation by chain and burn ID",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			clientCtx, err := client.GetClientQueryContext(cmd)
			if err != nil {
				return err
			}

			queryClient := types.NewQueryClient(clientCtx)
			res, err := queryClient.GetBridgeAttestation(cmd.Context(), &types.QueryBridgeAttestationRequest{
				SourceChain: args[0],
				BurnId:      args[1],
			})
			if err != nil {
				return err
			}

			return clientCtx.PrintProto(res)
		},
	}

	flags.AddQueryFlagsToCmd(cmd)
	return cmd
}

// GetCmdQueryBridgeConfig implements the query bridge config command.
func GetCmdQueryBridgeConfig() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "config",
		Short: "Query the bridge configuration parameters",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			clientCtx, err := client.GetClientQueryContext(cmd)
			if err != nil {
				return err
			}

			queryClient := types.NewQueryClient(clientCtx)
			res, err := queryClient.GetBridgeConfig(cmd.Context(), &types.QueryBridgeConfigRequest{})
			if err != nil {
				return err
			}

			return clientCtx.PrintProto(res)
		},
	}

	flags.AddQueryFlagsToCmd(cmd)
	return cmd
}

// GetBridgeTxCmd returns the CLI transaction commands for the bridge submodule.
func GetBridgeTxCmd() *cobra.Command {
	bridgeTxCmd := &cobra.Command{
		Use:                        "bridge",
		Short:                      "Bridge transaction subcommands",
		DisableFlagParsing:         true,
		SuggestionsMinimumDistance: 2,
		RunE:                       client.ValidateCmd,
	}

	bridgeTxCmd.AddCommand(
		GetCmdBridgeBurn(),
		GetCmdBridgeAttest(),
		GetCmdBridgeMinted(),
	)

	return bridgeTxCmd
}

// GetCmdBridgeMinted implements the bridge minted command for validators.
func GetCmdBridgeMinted() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "minted [burn_id] [destination_chain] [destination_tx]",
		Short: "Report successful mint on destination chain (validators only)",
		Args:  cobra.ExactArgs(3),
		RunE: func(cmd *cobra.Command, args []string) error {
			clientCtx, err := client.GetClientTxContext(cmd)
			if err != nil {
				return err
			}

			msg := &types.MsgBridgeAttestMinted{
				Validator:        clientCtx.GetFromAddress().String(),
				BurnId:           args[0],
				DestinationChain: args[1],
				DestinationTx:    args[2],
			}

			return tx.GenerateOrBroadcastTxCLI(clientCtx, cmd.Flags(), msg)
		},
	}

	flags.AddTxFlagsToCmd(cmd)
	return cmd
}

// GetCmdBridgeBurn implements the bridge burn command for non-IBC chains.
// Note: This is for direct CLI usage (e.g., testing). Normal users would use the frontend.
func GetCmdBridgeBurn() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "burn [destination_chain] [destination_address] [amount]",
		Short: "Burn tokens for bridging to an external chain (e.g., Solana)",
		Long: `Burn MIRAGE tokens for bridging to an external non-IBC chain.
The burn will be picked up by orchestrators who will mint equivalent tokens on the destination chain.

Example:
  miraged tx bridge burn solana 5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp9xv3PaqgL6Rj 1000000 --from mykey`,
		Args: cobra.ExactArgs(3),
		RunE: func(cmd *cobra.Command, args []string) error {
			clientCtx, err := client.GetClientTxContext(cmd)
			if err != nil {
				return err
			}

			destChain := args[0]
			destAddr := args[1]
			amount, err := strconv.ParseUint(args[2], 10, 64)
			if err != nil {
				return fmt.Errorf("invalid amount: %w", err)
			}

			msg := &types.MsgBridgeBurn{
				Authority:          clientCtx.GetFromAddress().String(),
				DestinationChain:   destChain,
				DestinationAddress: destAddr,
				Amount:             amount,
			}

			return tx.GenerateOrBroadcastTxCLI(clientCtx, cmd.Flags(), msg)
		},
	}

	flags.AddTxFlagsToCmd(cmd)
	return cmd
}

// GetCmdBridgeAttest implements the bridge attest-burned command for validators (inbound).
func GetCmdBridgeAttest() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "attest-burned [source_chain] [burn_id] [mirage_recipient] [amount]",
		Short: "Attest to a burn on an external chain (validators only, inbound)",
		Long: `Submit an attestation for a burn that occurred on an external chain.
This is typically called by validator orchestrator processes, not manually.
When 2/3 validators attest, tokens are minted on Mirage.

Example:
  miraged tx bridge attest-burned solana abc123txhash mirage1abc... 1000000 --from validator`,
		Args: cobra.ExactArgs(4),
		RunE: func(cmd *cobra.Command, args []string) error {
			clientCtx, err := client.GetClientTxContext(cmd)
			if err != nil {
				return err
			}

			sourceChain := args[0]
			burnID := args[1]
			mirageRecipient := args[2]
			amount, err := strconv.ParseUint(args[3], 10, 64)
			if err != nil {
				return fmt.Errorf("invalid amount: %w", err)
			}

			msg := &types.MsgBridgeAttestBurned{
				Validator:       clientCtx.GetFromAddress().String(),
				SourceChain:     sourceChain,
				BurnId:          burnID,
				MirageRecipient: mirageRecipient,
				Amount:          amount,
			}

			return tx.GenerateOrBroadcastTxCLI(clientCtx, cmd.Flags(), msg)
		},
	}

	flags.AddTxFlagsToCmd(cmd)
	return cmd
}
