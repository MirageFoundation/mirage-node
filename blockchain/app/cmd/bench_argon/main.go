package main

import (
	"crypto/rand"
	"fmt"
	"time"

	"golang.org/x/crypto/argon2"
)

func main() {
	password := make([]byte, 300)
	rand.Read(password)
	salt := make([]byte, 32)
	rand.Read(salt)

	start := time.Now()
	iterations := 50
	for i := 0; i < iterations; i++ {
		_ = argon2.IDKey(password, salt, 1, 4096, 1, 32)
	}
	elapsed := time.Since(start)
	avg := elapsed / time.Duration(iterations)

	fmt.Printf("Average Argon2 duration: %v\n", avg)
}
