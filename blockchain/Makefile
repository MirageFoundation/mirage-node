BRANCH := $(shell git rev-parse --abbrev-ref HEAD)
COMMIT := $(shell git log -1 --format='%H')
APPNAME := mirage

# do not override user values
ifeq (,$(VERSION))
  # Try git describe for tags (includes distance from tag)
  VERSION := $(shell git describe --tags --always --dirty 2>/dev/null)
  # if VERSION is still empty, use branch and commit
  ifeq (,$(VERSION))
    VERSION := $(BRANCH)-$(COMMIT)
  endif
endif

# Update the ldflags with the app, client & server names
ldflags = -X github.com/cosmos/cosmos-sdk/version.Name=$(APPNAME) \
	-X github.com/cosmos/cosmos-sdk/version.AppName=$(APPNAME)d \
	-X github.com/cosmos/cosmos-sdk/version.Version=$(VERSION) \
	-X github.com/cosmos/cosmos-sdk/version.Commit=$(COMMIT)

BUILD_FLAGS := -ldflags '$(ldflags)'

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

test: govet govulncheck test-unit

# Fast test for CI/deploy - no race detector, shorter timeout
test-fast:
	@echo "--> Running tests..."
	@go test -mod=readonly -timeout 5m ./...

.PHONY: test test-unit test-race test-cover test-fast bench

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

build-orchestrator:
	@echo "--> building orchestrator"
	@mkdir -p ./bin
	@go build $(BUILD_FLAGS) -mod=readonly -o ./bin/orchestrator ./cmd/orchestrator

build-all: test-fast build build-orchestrator

# Build a specific version for upgrades
build-version:
	@if [ -z "$(V)" ]; then echo "Usage: make build-version V=v2.0.0"; exit 1; fi
	@echo "--> Building $(APPNAME)d version $(V)"
	@VERSION=$(V) go build $(BUILD_FLAGS) -mod=readonly -o ./$(APPNAME)d-$(V) ./cmd/$(APPNAME)d
	@echo "--> Binary created: ./$(APPNAME)d-$(V)"

.PHONY: all install build build-version build-orchestrator build-all

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

govulncheck:
	@echo Running govulncheck...
	@go tool golang.org/x/vuln/cmd/govulncheck@latest
	@govulncheck ./...

.PHONY: govet govulncheck