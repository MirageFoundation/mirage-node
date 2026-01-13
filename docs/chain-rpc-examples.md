# Mirage Chain RPC Examples (Public)

This document shows how to query a Mirage node via CometBFT RPC and the Cosmos REST API.

### Public Endpoints

For public access via HTTPS (recommended):

```bash
# Primary endpoints (mirage.talk)
RPC_URL="https://mirage.talk/chain/rpc"
REST_URL="https://mirage.talk/chain/rest"
WS_URL="wss://mirage.talk/chain/rpc/websocket"

# Fallback endpoints (mirage.vote)
RPC_URL="https://mirage.vote/chain/rpc"
REST_URL="https://mirage.vote/chain/rest"
```

### Direct Port Access (internal/local only)

For local or internal node access:

```bash
NODE_HOST="<YOUR_NODE_HOST_OR_IP>"

RPC_HTTP="http://${NODE_HOST}:26657"
RPC_WS="ws://${NODE_HOST}:26657/websocket"
REST_HTTP="http://${NODE_HOST}:1317"
```

> **Deprecation Notice**: The legacy paths `/rpc` and `/lcd` are deprecated and will be removed after **2026-02-20**. Use `/chain/rpc` and `/chain/rest` instead.

### CometBFT RPC (port 26657)

#### Node status

```bash
curl "${RPC_HTTP}/status" | jq
```

#### Latest block and block results

```bash
curl "${RPC_HTTP}/block" | jq
curl "${RPC_HTTP}/block_results?height=12345" | jq
```

#### Transaction by hash

```bash
curl "${RPC_HTTP}/tx?hash=0xABC123DEF456..." | jq
```

#### Search transactions

```bash
curl "${RPC_HTTP}/tx_search?query=\"tx.height=12345\"" | jq
curl "${RPC_HTTP}/tx_search?query=\"message.action='/mirage.core.v1.MsgPost'\"" | jq
```

#### Validators

```bash
curl "${RPC_HTTP}/validators" | jq
```

### Cosmos REST API (port 1317)

#### Core params

```bash
curl "${REST_HTTP}/mirage/core/v1/params" | jq
```

#### Account balance

```bash
curl "${REST_HTTP}/cosmos/bank/v1beta1/balances/mirage1abc123..." | jq
```

### Watch new transactions (WebSocket)

Requires `websocat`.

```bash
(echo '{"jsonrpc":"2.0","method":"subscribe","id":1,"params":{"query":"tm.event='"'"'Tx'"'"'"}}'; cat) | \
  websocat "${RPC_WS}" | jq -c 'select(.result.events) | {height: .result.events["tx.height"][0], hash: .result.events["tx.hash"][0], action: .result.events["message.action"][0]}'
```

### Notes

- Addresses use Bech32 prefix `mirage1`
- Validator operator addresses use `miragevaloper1`
- Amounts are in `umirage` (1 MIRAGE = 1,000,000 umirage)


