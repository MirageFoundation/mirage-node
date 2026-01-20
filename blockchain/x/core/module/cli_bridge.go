package core

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
		GetCmdQueryBridgeMinted(),
		GetCmdQueryBridgeConfig(),
	)

	return bridgeQueryCmd
}

// GetCmdQueryBridgeMinted implements the query bridge minted command.
func GetCmdQueryBridgeMinted() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "minted [burn_id]",
		Short: "Query mint confirmation by burn ID",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			clientCtx, err := client.GetClientQueryContext(cmd)
			if err != nil {
				return err
			}

			queryClient := types.NewQueryClient(clientCtx)
			res, err := queryClient.GetBridgeMinted(cmd.Context(), &types.QueryBridgeMintedRequest{
				BurnId: args[0],
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

			fromAddr := clientCtx.GetFromAddress()
			valoper, err := convertAccToValoper(fromAddr.String())
			if err != nil {
				return fmt.Errorf("failed to convert to validator address: %w", err)
			}

			msg := &types.MsgBridgeMinted{
				Authority:        valoper,
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

// GetCmdBridgeAttest implements the bridge attest command for validators.
func GetCmdBridgeAttest() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "attest [source_chain] [burn_id] [mirage_recipient] [amount]",
		Short: "Attest to a burn on an external chain (validators only)",
		Long: `Submit an attestation for a burn that occurred on an external chain.
This is typically called by validator orchestrator processes, not manually.

Example:
  miraged tx bridge attest solana abc123txhash mirage1abc... 1000000 --from validator`,
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

			// The signer should be a validator operator address
			fromAddr := clientCtx.GetFromAddress()
			valoper, err := convertAccToValoper(fromAddr.String())
			if err != nil {
				return fmt.Errorf("failed to convert to validator address: %w", err)
			}

			msg := &types.MsgBridgeAttest{
				Validator:       valoper,
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

// convertAccToValoper converts a bech32 account address to a validator operator address.
// This is needed because validators sign with their operator key.
func convertAccToValoper(accAddr string) (string, error) {
	// For Mirage, the prefix conversion is: mirage -> miragevaloper
	// The SDK handles this conversion automatically when we use the same bytes
	// but with different prefix
	if len(accAddr) < 7 {
		return "", fmt.Errorf("invalid address")
	}
	// Simple prefix replacement for mirage chain
	// In production, this should use SDK's address conversion
	return "miragevaloper" + accAddr[6:], nil
}
