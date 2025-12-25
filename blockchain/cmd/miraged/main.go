package main

import (
	"fmt"
	"os"
	"runtime/debug"

	clienthelpers "cosmossdk.io/client/v2/helpers"
	svrcmd "github.com/cosmos/cosmos-sdk/server/cmd"

	"mirage/app"
	"mirage/cmd/miraged/cmd"
)

func main() {
	// Ensure panics are logged with a stack trace to stderr (redirected to file later).
	defer func() {
		if r := recover(); r != nil {
			fmt.Fprintf(os.Stderr, "FATAL: panic: %v\n%s", r, string(debug.Stack()))
			os.Exit(1)
		}
	}()

	rootCmd := cmd.NewRootCmd()
	if err := svrcmd.Execute(rootCmd, clienthelpers.EnvPrefix, app.DefaultNodeHome); err != nil {
		// Print a fatal error marker so it lands in logs even if logger isn't initialized yet.
		fmt.Fprintf(os.Stderr, "FATAL: %v\n", err)
		os.Exit(1)
	}
}
