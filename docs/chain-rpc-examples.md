# Mirage Chain RPC Examples (Public)

This document shows how to query a Mirage node via CometBFT RPC and the Cosmos REST API. It is written to be reusable for any node and does not hard-code IPs.

### Variables used below

```bash
NODE_HOST="<YOUR_NODE_HOST_OR_DOMAIN>"

RPC_HTTP="http://${NODE_HOST}:26657"
RPC_WS="ws://${NODE_HOST}:26657/websocket"
REST_HTTP="http://${NODE_HOST}:1317"
```

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


