# Network Site Identity — Implementation Plan

Target version: **v1.39.0** (branch `dev`)

How `/network` decides which nodes exist, what address each one is at, and how
much of that is proved rather than claimed.

---

## 1. Status

Two things are wrong with the current implementation, and one of them is a
security defect.

**Nothing here has shipped.** The signed-identity work exists only in the working
tree and in the local Docker container. No release carries it, no fleet node
serves `/api/node_identity`, and no node verifies anything. There is therefore no
deployed vulnerability, no compatibility burden, and no need to negotiate
formats with an older build. The format can simply be defined correctly once.

The local container currently runs the flawed build and must be resynced before
any of the checks below mean anything.

---

## 2. The two defects

### 2.1 The proof is forgeable by relay (security)

`build_local_identity` signs an origin that the **caller supplies**:

```146:156:web/backend/node_identity.py
    origin = normalize_origin(origin_raw)
    if origin is None:
        raise ValueError("origin must be scheme://host[:port]")
    nonce = (nonce_raw or "").strip()
    if not _NONCE_RE.fullmatch(nonce):
        raise ValueError("nonce must be 32 lowercase hex characters")

    rt = require_runtime()
    site = local_site()
    payload = _canonical_payload(rt.chain_id, rt.validator_operator_address, origin, site, nonce)
```

and `verify_identity` compares that origin only against what the verifier
expected, never against anything the signer asserts about itself. The `site`
field is signed but never compared to the origin.

The attack needs no key:

1. Verifier challenges `https://evil.com` with nonce `N`.
2. `evil.com` forwards the identical request to
   `https://mirage.talk/api/node_identity?origin=https://evil.com&nonce=N`.
3. val1 signs *"I am val1, at origin `https://evil.com`"* — it signs whatever
   origin it is handed.
4. `evil.com` returns that document unmodified.
5. Verification passes on every check, and `evil.com` is listed as **confirmed
   val1**.

The root cause is general: **a signature only proves something if the signed
statement is about the signer.** Letting the caller choose the subject makes the
response a bearer token that anyone can present.

### 2.2 Listing is gated on proof (completeness)

`_discover_active_sites` only emits a row when a candidate address exists and,
for peer-discovered addresses, only when it verifies. A validator that published
no address and cannot be proved is absent entirely.

That is backwards. Proof is an attribute of an address, not the price of
appearing. The page must show the whole active set unconditionally and describe
how much is known about each entry.

---

## 3. Threat model: what each channel actually proves

| Channel | Forgeable? | Proves | Does not prove |
|---|---|---|---|
| On-chain moniker | No | Validator V claims address A | That A is reachable or serves V |
| P2P `remote_ip` | No | A real node is at IP | Which validator it is |
| CometBFT node ID | No (from our own `net_info`) | Which peer we are connected to | Which validator it is |
| Self-referential signature | No, once fixed | Holder of V's key controls what is served at A | Anything if V's key is stolen |
| Caller-supplied signature | **Yes — relayable** | Nothing | — |
| TLS certificate | No | Control of the DNS name at issuance | Which validator |
| DNS A record | Yes, by whoever runs DNS | Name points at an IP | Ownership |

Two facts constrain the design:

**There is no on-chain link from a CometBFT node ID to a validator operator
address.** Peering is open, so being a peer proves only that a node exists at an
address.

**Our own domains do not resolve to our own nodes.** Verified:

```
mirage.talk  -> 152.233.22.98     (Bunny edge)
mirage.vote  -> 185.152.66.247    (Bunny edge)
val1 peer IP -> 159.203.114.27
```

So "the domain must resolve to the peer IP" cannot be a requirement — it would
reject production. It is corroborating evidence for a self-hosted node only.
This is the same reason `setup_letsencrypt.py` needs `--skip-ip-check`.

---

## 4. The redesigned proof

### 4.1 Rule

A node signs **only self-referential values**, read from its own configuration.
Nothing a caller sends is ever part of the signed statement except the nonce,
which exists solely for freshness and cannot name a subject.

### 4.2 Signed statement

```
node_identity:v1 | chain_id | operator_address | node_id | addresses[] | nonce
```

Netstring framing per field (already implemented in `_canonical_payload`), so no
field can be shifted into another. Signed with the validator account key over
`SHA-256`, as today.

| Field | Source | Why it is there |
|---|---|---|
| `chain_id` | `Runtime.chain_id` | A doc from another chain must not verify |
| `operator_address` | `Runtime.validator_operator_address` | The identity being claimed |
| `node_id` | `config/node_key.json`, read once at startup | Binds the web service to a specific consensus peer |
| `addresses[]` | `DOMAIN`, `ORIGIN_DOMAIN`, on-chain moniker | The addresses the node asserts are its own |
| `nonce` | Verifier | Freshness; proves the key is live, not a year-old capture |

`addresses[]` is sorted and deduplicated so the payload is canonical.

### 4.3 Verification

Given a document fetched by dialing URL `U`, where the peer table says the node
at that IP has node ID `P`:

1. `chain_id` matches ours.
2. `nonce` echoes the one we sent.
3. `pubkey` is 33 bytes; derived `miragevaloper` address equals
   `operator_address`; that address is **bonded**.
4. Signature verifies over the canonical payload.
5. **Binding — at least one must hold:**
   - `U ∈ addresses[]` (the node asserts this address is its own), or
   - `node_id == P` (the node is the exact peer we hold a consensus connection
     with at that IP).

Step 5 is what kills the relay. A document forwarded from val1 lists
`https://mirage.talk` and val1's node ID; neither matches `evil.com` nor the
attacker's node ID, so it is rejected.

It also covers the address-less case: EuroServer publishes no domain, so
`addresses[]` is empty, but its node ID matches the peer we are connected to at
`104.248.252.18` — so that address is proved without the operator publishing
anything at all.

### 4.4 Signing-oracle safety, restated

The remaining caller input is a 32-hex nonce. The payload is framed under a fixed
ASCII prefix and cannot begin a Cosmos `SignDoc` (field 1 requires `0x0a`; `n` is
`0x6e`, field 13 wire type 6, which does not exist). Unchanged from the current
reasoning, and now with a strictly smaller attack surface since `origin` is gone.

---

## 5. Evidence model

Every bonded validator gets a row. Each row carries zero or more addresses, each
with independent evidence flags.

| Flag | Set when |
|---|---|
| `chain_published` | the validator's moniker parses to this address |
| `peer_observed` | this IP is the remote address of a live P2P connection |
| `key_proven` | a valid self-referential signature bound to this address |
| `node_id_bound` | signed node ID equals the peer node ID at this IP |
| `tls_valid` | fetched over https with a CA-valid certificate |
| `dns_matches_peer` | hostname resolves to an IP that is `peer_observed` for the same validator |

User-facing label, computed from the flags, strongest first:

| Label | Condition |
|---|---|
| `confirmed` | `key_proven` |
| `peered` | `peer_observed` without `key_proven` |
| `published, unconfirmed` | `chain_published` only |
| `no address published` | validator has no address at all |

`dns_matches_peer` and `tls_valid` are shown as extra detail, never as gates.

**Credential boundary is unchanged.** `authenticated_node_sites()` keeps its own
rule (https + named host) for the stats fan-out. Widening what is *listed* must
never widen what is *trusted*. The existing strict-subset test stays.

---

## 6. Per-component changes

### 6.1 Indexer — `indexer/main.py`

`_sync_connected_peers` currently drops the node ID:

```1477:1490:indexer/main.py
    def _sync_connected_peers(self):
        """Fetch connected peers from RPC and store in chain_stats."""
        info = self.chain.get_net_info()
        peers_data = ((info or {}).get("result") or {}).get("peers") or []
        peers: list[dict] = []
        seen_ips: set[str] = set()
        for peer in peers_data:
            ip = str(peer.get("remote_ip", "") or "").strip()
            if not ip or ip in seen_ips:
                continue
            node_info = peer.get("node_info") or {}
            peers.append({"ip": ip, "moniker": str(node_info.get("moniker", "") or "").strip()})
            seen_ips.add(ip)
        self.db.set_chain_stat("connected_peers", peers, int(time.time()))
```

Add `node_id` from `node_info["id"]`.

**No schema approval needed.** `chain_stats.value` is `JSONB`
(`indexer/database.py:730`), so this adds a key to an existing document, not a
column.

### 6.2 Backend — `web/backend/chain.py`

`get_connected_peers()` must carry `node_id` through. Keep failing hard on a
missing or malformed row.

### 6.3 Backend — `web/backend/node.py`

Add `validator_node_id` to `Runtime`, derived once at startup from
`config/node_key.json`: CometBFT node ID is the lowercase hex of the first 20
bytes of `SHA-256(p2p_pubkey_bytes)`. Reading a local node file once at startup
matches the existing rule; do not re-read at runtime.

### 6.4 Backend — `web/backend/node_identity.py`

- Drop `origin` from the payload and from the endpoint's inputs entirely.
- Add `node_id` and `addresses[]`.
- `local_addresses()` replaces `local_site()`: `https://{DOMAIN}`,
  `https://{ORIGIN_DOMAIN}`, and the on-chain moniker when it parses, each
  normalised through `normalize_origin`, sorted and deduplicated.
- `verify_identity(doc, *, expect_nonce, expect_chain_id, dialed_url, peer_node_id)`
  returns the operator address plus which binding satisfied step 5, or `None`.
- Keep `normalize_origin` — it is still needed to canonicalise addresses.

### 6.5 Backend — `web/backend/fleet.py`

Restructure around validators rather than URLs.

- `NodeSite` becomes `NodeAddress(url, flags)`.
- New `NetworkNode(operator_address, moniker, addresses[])` — one per bonded
  validator, emitted whether or not it has any address.
- `_discover_network()` builds candidates from monikers and peer IPs, probes
  them concurrently, and attaches flags. It never drops a validator.
- Self-entry stays resolved locally, no loopback probe.
- Cache TTLs unchanged: 6 h on a fully proved result, 5 min otherwise.
- `active_node_sites()` and `authenticated_node_sites()` keep their exact current
  meaning for the stats fan-out.

### 6.6 Backend — `web/backend/routes/public.py`

- `/api/node_identity` takes only `nonce`. Returns the new document.
- `/api/get_peers` returns one entry per validator:

```json
{"peers": [{
  "operator_address": "miragevaloper1...",
  "moniker": "EuroServer",
  "site": "http://104.248.252.18",
  "status": "confirmed",
  "addresses": [{"url": "http://104.248.252.18",
                 "flags": ["peer_observed", "key_proven", "node_id_bound"]}]
}]}
```

Keep `moniker` populated with the site URL for one release so a stale cached
bundle keeps rendering.

### 6.7 Frontend — `useNetwork.js`, `NetworkView.js`

Render every row. Address as a link when one exists; otherwise the validator's
name as plain text with `no address published`. Status label beside it, with the
flag detail in the `title` attribute. Replace the current
`verified === false` check with the `status` field.

---

## 7. Phases

Each phase is independently shippable and independently verifiable.

### Phase 0 — Remove the forgeable proof
Delete `origin` from the signed payload and the endpoint. Until Phase 1 lands,
`key_proven` is satisfied by `U ∈ addresses[]` only.
**Verify:** a relay harness that forwards a challenge to a second node must fail
verification. Add it to `scripts/check_node_identity.py`.

### Phase 1 — Node ID binding
Indexer carries `node_id`; backend threads it through; verification accepts the
node-ID binding.
**Verify:** EuroServer's address is `key_proven` with an empty `addresses[]`. A
document relayed from a different node fails on node-ID mismatch.

### Phase 2 — Completeness
One row per bonded validator, always.
**Verify:** with every probe stubbed to fail, the row count still equals the
bonded validator count.

### Phase 3 — Evidence in the API and UI
Flags, status labels, rendering.
**Verify:** the four labels render for hand-built fixtures.

### Phase 4 — TLS and DNS corroboration
Record `tls_valid` and `dns_matches_peer` as detail only.
**Verify:** `mirage.talk` shows `tls_valid` and **not** `dns_matches_peer`
(it is behind Bunny), and is still `confirmed`. This is the regression guard
against anyone later promoting DNS agreement to a requirement.

### Phase 5 — Tests, docs, release
Release notes at `docs/updates/update_v1.39.0.md`, marketing tone, honest about
the fact that a stolen validator key defeats every check here.

---

## 8. Test plan

**`scripts/check_node_identity.py`** — extend the existing standalone harness:
relay rejection, node-ID binding accept and reject, empty `addresses[]` accepted
via node ID, address binding accepted without node ID, stale nonce, wrong chain,
tampered fields, foreign key claiming another operator.

**`tests/cases/test_backend_security.py`** (`fleet_url` category) — extend
`_check_active_node_sites`: every bonded validator appears with all probes
failing; a validator with no address still produces a row; a peer that proves a
bonded validator is listed; a peer proving nothing is listed as `peered` and not
`confirmed`; one entry per validator; fan-out stays a strict subset.

**`tests/cases/test_backend_hardening.py`** — the existing fan-out probe already
asserts the strict-subset property; update its stubs for the new signature.

**`tests/cases/test_backend_authz.py`** — `/api/node_identity` stays `PUBLIC`.

Run:

```bash
conda activate mirage-node && python scripts/check_node_identity.py
docker exec mirage bash -lc 'cd /opt/mirage && set -a; for f in /root/.mirage/env/*.env; do . "$f"; done; set +a; PYTHONPATH=/opt/mirage python3 tests/test_backend.py --category fleet_url'
docker exec mirage bash -lc 'cd /opt/mirage && set -a; for f in /root/.mirage/env/*.env; do . "$f"; done; set +a; PYTHONPATH=/opt/mirage python3 tests/test_backend.py --category backend_hardening'
docker exec mirage bash -lc 'cd /opt/mirage && set -a; for f in /root/.mirage/env/*.env; do . "$f"; done; set +a; PYTHONPATH=/opt/mirage python3 tests/test_backend.py --category route_authz'
```

Note: `backend_hardening` and `error_registry` currently carry failures from the
in-flight topics→communities refactor (`_blocked_topics_sql`, two agent error
strings). Those are pre-existing and unrelated.

This is not a blockchain upgrade — no consensus or state-transition change — so
`scripts/test_upgrade.sh` does not apply.

---

## 9. Rollout

No format negotiation is required, because nothing shipped. Resync the local
container before testing.

During the fleet rollout, a node that has not yet updated serves no
`/api/node_identity`, so its address shows `published, unconfirmed`. Nothing
disappears from the page at any point. EuroServer appears immediately at Phase 2
as `peered`, and upgrades to `confirmed` once it takes the release.

---

## 10. Open decisions

1. **Inactive validators.** Bonded only, or also show jailed/unbonding
   (`Frankfurt-Node`, `Amsterdam-Node`) in a separate group? Recommendation:
   bonded is the network; add a muted "inactive" group only if you want the
   history visible.
2. **Publishing peer IPs.** Peer discovery makes a validator's IP public even
   when its operator deliberately published only a nickname. That is the
   intended behaviour here, but it is a real disclosure and worth an explicit
   yes.
3. **Address aliases.** Whether to add a `SITE_ALIASES` env for a node reachable
   at several names. Not needed today; `DOMAIN` plus `ORIGIN_DOMAIN` covers the
   fleet.
