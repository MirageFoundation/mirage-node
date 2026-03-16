package main

import (
	"encoding/hex"
	"fmt"
	"os"

	"github.com/cosmos/cosmos-sdk/types/tx"
)

func main() {
	// Exact auth_info_bytes hex from backend log
	authHex := "0a4e0a460a1f2f636f736d6f732e63727970746f2e736563703235366b312e5075624b657912230a21034dc8e89664762b84ac0a319b4c554a95d8391215c75b9024d786d174bf2bfd7712040a02080112470a130a07756d69726167651208313039343430303010c0551a2d6d697261676531766b646163666535337834616b37726564677936776c6567646c676c6e6c7374387034376435"

	authBytes, err := hex.DecodeString(authHex)
	if err != nil {
		fmt.Fprintf(os.Stderr, "hex decode error: %v\n", err)
		os.Exit(1)
	}

	var authInfo tx.AuthInfo
	err = authInfo.Unmarshal(authBytes)
	if err != nil {
		fmt.Fprintf(os.Stderr, "unmarshal error: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("AuthInfo.Fee == nil: %v\n", authInfo.Fee == nil)
	if authInfo.Fee != nil {
		fmt.Printf("Fee.GasLimit: %d\n", authInfo.Fee.GasLimit)
		fmt.Printf("Fee.Amount: %s\n", authInfo.Fee.Amount)
		fmt.Printf("Fee.Payer: %s\n", authInfo.Fee.Payer)
	}
	fmt.Printf("SignerInfos count: %d\n", len(authInfo.SignerInfos))

	// Also test the fee bytes directly
	feeHex := "0a130a07756d69726167651208313039343430303010c0551a2d6d697261676531766b646163666535337834616b37726564677936776c6567646c676c6e6c7374387034376435"
	feeBytes, _ := hex.DecodeString(feeHex)
	var fee tx.Fee
	err = fee.Unmarshal(feeBytes)
	if err != nil {
		fmt.Fprintf(os.Stderr, "fee unmarshal error: %v\n", err)
		os.Exit(1)
	}
	fmt.Printf("\nDirect Fee.GasLimit: %d\n", fee.GasLimit)
	fmt.Printf("Direct Fee.Amount: %s\n", fee.Amount)
	fmt.Printf("Direct Fee.Payer: %s\n", fee.Payer)
}
