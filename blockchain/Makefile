BRANCH := $(shell git rev-parse --abbrev-ref HEAD)
COMMIT := $(shell git log -1 --format='%H')
APPNAME := mirage
BUILD_TAGS := pebbledb
GOVULNCHECK := go run golang.org/x/vuln/cmd/govulncheck@v1.6.0

# Verify module and auto-downloaded toolchain checksums even if a host-level Go
# configuration disabled the checksum database.
export GOSUMDB := sum.golang.org
export GOTOOLCHAIN := auto

VERSION_FILE := $(CURDIR)/../VERSION
# do not override user values
ifeq (,$(VERSION))
  VERSION := $(shell cat "$(VERSION_FILE)" 2>/dev/null)
endif
ifeq (,$(VERSION))
  $(error VERSION file missing at $(VERSION_FILE))
endif
ifeq ($(shell printf '%s' "$(VERSION)" | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$$'),)
  $(error VERSION '$(VERSION)' does not match vX.Y.Z)
endif

# Update the ldflags with the app, client & server names
ldflags = -X github.com/cosmos/cosmos-sdk/version.Name=$(APPNAME) \
	-X github.com/cosmos/cosmos-sdk/version.AppName=$(APPNAME)d \
	-X github.com/cosmos/cosmos-sdk/version.Version=$(VERSION) \
	-X github.com/cosmos/cosmos-sdk/version.Commit=$(COMMIT)

BUILD_FLAGS := -tags $(BUILD_TAGS) -ldflags '$(ldflags)'

##############
###  Test  ###
##############

test-unit:
	@echo Running unit tests...
	@go test -mod=readonly -v -timeout 30m ./...

test-race:
	@echo Running unit tests with race condition reporting...
	@go test -mod=readonly -v -race -timeout 30m ./...

test-cover:
	@echo Running unit tests and creating coverage report...
	@go test -mod=readonly -v -timeout 30m -coverprofile=$(COVER_FILE) -covermode=atomic ./...
	@go tool cover -html=$(COVER_FILE) -o $(COVER_HTML_FILE)
	@rm $(COVER_FILE)

bench:
	@echo Running unit tests with benchmarking...
	@go test -mod=readonly -v -timeout 30m -bench=. ./...

test: govet govulncheck test-unit test-iavl

# Fast test for CI/deploy - no race detector, shorter timeout.
# test-iavl is included so the patches/iavl regression suite (consensus
# read-path correctness when fast-node index is incomplete) runs in every
# CI/deploy gate alongside ./... — patches/iavl is a separate go module
# (replace directive in go.mod) and is NOT picked up by ./...
test-fast: test-fast-app test-iavl test-store test-patch-provenance
	@echo "--> All fast tests passed (./... + patches/iavl + patches/cosmos-sdk-store-v2)"

test-fast-app:
	@echo "--> Running blockchain tests (./...)"
	@go test -mod=readonly -timeout 5m ./...

# patches/iavl is a forked IAVL with mirage-specific consensus-correctness
# fixes (see docs/troubleshooting/state-sync-bonddenom-panic.md). It lives in
# its own go module so upstream cosmos/iavl tooling treats it as a drop-in.
# Running it as part of test-fast guarantees that any future change to the
# patch is gated by the regression suite that catches the BondDenom /
# app-hash divergence shape.
test-iavl:
	@echo "--> Running patched IAVL tests (patches/iavl)"
	@cd patches/iavl && go test -mod=readonly -timeout 10m ./...

# patches/cosmos-sdk-store-v2 is a forked store/v2 (the rootmulti module the
# v0.54 baseapp actually links) carrying the commit-info pruning fix (upstream
# #26551 — PruneStores never deletes s/<version> commit-info, so it grows
# unbounded). Like patches/iavl it is a separate go module (replace directive)
# and is NOT picked up by ./..., so it gets its own gate in test-fast to pin
# the commit-info prune regression.
# Every package except streaming/, whose upstream suite launches a go-plugin
# binary over stdio and fails on any machine that has not built one. Nothing in
# Mirage links it.
test-store:
	@echo "--> Running patched store/v2 tests (patches/cosmos-sdk-store-v2)"
	@cd patches/cosmos-sdk-store-v2 && go test -mod=readonly -timeout 10m $$(go list ./... | grep -v '/streaming')

test-patch-provenance:
	@echo "--> Checking consensus patch provenance"
	@../scripts/check_patches.sh

.PHONY: test test-unit test-race test-cover test-fast test-fast-app test-iavl test-store test-patch-provenance bench

#################
###  Install  ###
#################

all: install

install:
	@echo "--> ensure dependencies have not been modified"
	@go mod verify
	@echo "--> building $(APPNAME)d version $(VERSION)"
	@mkdir -p ./bin
	@go build $(BUILD_FLAGS) -mod=readonly -o ./bin/$(APPNAME)d ./cmd/$(APPNAME)d

build: install

build-compact-db:
	@echo "--> building compact-db"
	@mkdir -p ./bin
	@go build $(BUILD_FLAGS) -mod=readonly -o ./bin/compact-db ./cmd/compact-db

build-all: test-fast build build-compact-db

# Build a specific version for upgrades (version embedded via ldflags; binary is always miraged)
build-version:
	@if [ -z "$(V)" ]; then echo "Usage: make build-version V=v2.0.0"; exit 1; fi
	@$(MAKE) build VERSION=$(V)

.PHONY: all install build build-version build-compact-db build-all

##################
###  Protobuf  ###
##################

# Use this target if you do not want to use Ignite for generating proto files

proto-deps:
	@echo "Installing proto deps"
	@echo "Proto deps present, run 'go tool' to see them"

proto-gen:
	@echo "Generating protobuf files..."
	@ignite generate proto-go --yes

.PHONY: proto-gen

#################
###  Linting  ###
#################

lint:
	@echo "--> Running linter"
	@go tool github.com/golangci/golangci-lint/cmd/golangci-lint run ./... --timeout 15m

lint-fix:
	@echo "--> Running linter and fixing issues"
	@go tool github.com/golangci/golangci-lint/cmd/golangci-lint run ./... --fix --timeout 15m

.PHONY: lint lint-fix

###################
### Development ###
###################

govet:
	@echo Running go vet...
	@go vet ./...

# The forks are scanned with ./... like the main module. Scoping them to a single
# package left iavl/db, iavl/cache, iavl/fastnode and store/v2's snapshots/,
# cachekv/, iavl/ and pruning/ unscanned — re-creating, inside the vulnerability
# gate itself, the blind spot the `replace` directives create. snapshots/ is the
# one of those with a remote attack surface.
govulncheck:
	@status=0; \
	echo "Running govulncheck for main module..."; \
	$(GOVULNCHECK) ./... || status=1; \
	echo "Running govulncheck for patched IAVL..."; \
	(cd patches/iavl && $(GOVULNCHECK) ./...) || status=1; \
	echo "Running govulncheck for patched store/v2..."; \
	(cd patches/cosmos-sdk-store-v2 && $(GOVULNCHECK) ./...) || status=1; \
	exit $$status

.PHONY: govet govulncheck