# Cross-Component Security Review — 2026-08-18

**Baseline:** `dev` at `v1.37.0` (`8c4b2afb`).
**Scope:** every component, Critical and High only. The working tree since `v1.36.2` (the last register pin) is almost entirely the public installer, signed bootstrap, host updater and enrollment path; `web/backend/`, `indexer/`, `shared/` and `web/frontend/` have a zero-line diff against that tag, and `blockchain/` adds only a no-op `v1.37.0` upgrade handler. Those four components were therefore re-checked for regression of previously closed Critical/High items rather than re-audited from scratch.
**Reporting bar:** Critical and High only. Medium, Low and Informational candidates were developed and discarded during this sweep and are recorded only where they explain why an adjacent Critical/High claim was not filed. Open Medium/Low from earlier reviews stay on [`open-items.md`](../open-items.md); they are not re-derived.
**Method:** four parallel audits (installer; signed manifests and updater; recovery/enroll/stake; non-deploy regression), each required to produce a concrete exploit path, followed by independent re-verification of every surviving candidate against source.

**Prior state:** no Critical or High was open as of `v1.36.2`. The last three chain items shipped in `v1.36.0`; the four network-tag Highs shipped in `v1.36.1`. Accepted decisions in the register were excluded by instruction and are not re-reported.

---

## Summary

**0 Critical, 2 High, both fixed in `v1.37.0` the day they were filed.** Nothing from the earlier full reviews has regressed. The signed-release trust chain holds. A first draft of this document recorded both Highs as killed and was wrong; the operator then chose fix rather than accept.

| ID | Component | Finding | Status |
| :-- | :-- | :-- | :-- |
| **H-1** | Installer | `node.env` is bash-sourced as root. A tested-valid spaced moniker, `$()`, or `MIRAGE_EXTERNAL_ADDRESS` with a semicolon runs in the container after the seed and consensus key are on disk. | **Fixed in `v1.37.0`** |
| **H-2** | Recovery | `snapshot_diverged_state` returns success if the forensic directory cannot be created, and `wipe_chain_dbs` then deletes the chain DBs. | **Fixed in `v1.37.0`** |

| Area | Result |
| :--- | :--- |
| Prior Critical/High (chain, backend, indexer, frontend, network-tag) | Still closed. Fix sites hold. |
| Signed release/network manifests + `mirage-update` | No Critical/High. Expiry (network), generation monotonicity, digest pin, `rollback_safe` and upgrade-halt activation policy fail closed. Release manifests do not expire; that is Medium, not High — see killed candidates. |
| `WATCHDOG_AUTORECOVER=true` on installer nodes | Not High by itself. Destructive peer-pull still needs a working `RECOVERY_KEY`. Process-dead escalation around an upgrade halt is a real gap on hosts that already have both, and is recorded as a killed-for-High with a trigger rather than a third open item. |
| `blockchain/` / `web/backend/` / `indexer/` / `web/frontend/` since `v1.36.2` | No behavioural security delta. |

A GitHub-compromised `install.sh` is still trust-on-first-use — that is the documented installer model in `SECURITY.md`, not a finding. Everything after that first script is pinned or signed. **H-1 does not need a compromised GitHub.** It fires on the installer's own tested inputs.

---

## Prior Critical / High — still closed

Re-verified at the fix sites, not by re-running the original exploits.

| ID | Check | Result |
| :--- | :--- | :--- |
| **C-1 (bc)** authz `MsgExec` ante bypass | `x/authz` is not wired into the app. The `v1.36.0` store loader still deletes the `authz` KV store. Transitive classification in `ante_nested_msgs.go` remains, with tests that wrap relay messages in `MsgExec`. | Closed |
| **H-1 (bc)** iterator errors discarded | Not touched since `v1.36.0`. | Closed |
| **H-2 (bc)** `iavl.Store.Set` drops write errors | Not touched since `v1.36.0`. | Closed |
| **H-1 (idx)** governance attribute base64-guess | Indexer has no diff since `v1.36.2`. | Closed |
| **H-2 (idx)** admin level `== 100` only | Indexer has no diff since `v1.36.2`. | Closed |
| **C-1 (be)** blocked-topic ReDoS | `_topic_is_blocked` goes through `topic_matches_pattern`; the write path still rejects `count_wildcards(topic) > MAX_TOPIC_WILDCARDS`. | Closed |
| **H-1 (be)** unbounded `page` | `MAX_CANDIDATE_POOL = 500` still caps `limit * page`. | Closed |
| **H-2 (be)** admin stats to unauthenticated P2P monikers | Backend has no diff since `v1.36.2`. Residue (proof replay across the roster) remains the accepted risk. | Closed |
| **H-3 (be)** quest RMW | Backend has no diff since `v1.36.2`. | Closed |
| **H-3 (fe)** recovery-phrase fallback | Frontend has no diff since `v1.36.2`. | Closed |
| **H-2 (deploy, 2026-08-13)** remote `block_id.hash` reached `eval` | `init.sh` parses four keys from `bootstrap_join.py` stdout and never `eval`s them. The hash is rejected unless it is 64 hex chars, in both the Python producer and the shell consumer. | Closed |
| **NT Highs (2026-08-17)** | No further network-tag code in this delta. | Closed |

`statement_timeout` is still set on both DSN paths in `web/backend/db.py`.

---

## New surface — installer, manifests, updater

The public installer is the only new attack surface since the last pin. It runs as root, takes a 12-word seed, pulls a container, and enables hourly signed updates. The seed-in-`keyring-backend test` custody model is an accepted operator risk (2026-08-17) and is not re-reported.

### Trust chain (verified)

1. `install.sh` embeds the Ed25519 public key and its fingerprint `679a39294dc9639170ca9cb4010c44cc71dd153fa2029f2e73969bff6d86c0a8`, and dies if they disagree.
2. `release_verify.py` and `harden_server.sh` are fetched from GitHub or from `MIRAGE_MANIFEST_MIRROR`, then SHA-256-checked against hashes compiled into `install.sh`. The hashes at HEAD match the files. A mirror cannot change those two helpers without also changing the installer, which is the TOFU step.
3. Network and release manifests are verified with `openssl pkeyutl -verify -rawin` over canonical JSON. Unknown fields, HTTP URLs, duplicate endpoints, `0.0.0.0` peers, a non-`mirage-1` chain id, a non-digest-pinned image, an expired network manifest, and a consensus-breaking release marked `ordinary` or `rollback_safe` are all rejected before use.
4. `docker pull` is by `@sha256:`; `RepoDigest` is compared to the manifest. Host tools are copied out of that image only after its `pubkey.pem` fingerprint matches the key the installer embedded — the image's copy is never the trust anchor.
5. `mirage-update --tick` refuses a network `generation` older than the last accepted one, and refuses a same-generation body whose canonical hash changed. The same for `release_id`. Upgrade-halt releases cannot be activated by the host tool. Rollback requires `rollback_safe=true` and `consensus_breaking=false`.

A GitHub-trusted `install.sh` pointed at an attacker-controlled `MIRAGE_MANIFEST_MIRROR` therefore still fails closed: helpers must match the embedded hashes, and manifests must verify under the embedded key. Origin choice is availability, as `SECURITY.md` states.

### Collision / double-sign

`collision_guard` paginates every bonding status, fail-closed, through `agree_json` so a single REST endpoint cannot hide an existing validator. A query failure is not treated as "not registered". Reinstall on the same host is idempotent only when the derived consensus pubkey matches the file already on disk.

`create_validator.sh` asks the chain about this operator address specifically rather than scanning a single page of `q staking validators`, and will not submit a second create-validator if the query fails for any reason other than not-found.

### Auto-recovery (`WATCHDOG_AUTORECOVER=true`)

Installer nodes now write `WATCHDOG_AUTORECOVER=true`. Destructive peer-pull still requires `RECOVERY_KEY` (`/root/.mirage/.ssh/recovery_id`); the installer does not create that key, so a fresh public install stays restart-only. `UPGRADE_HALT_RE` still strips log-pattern `CONSENSUS FAILURE!!!` lines. It does **not** cover `TRIGGER_PROCESS_DEAD`. That gap is not filed as High for installer nodes (no key); it is a landmine if `recover.sh provision` is later used to make the advertised self-heal actually work. See killed candidates.

---

## H-1 (High) — Bash-sourced `node.env`: a valid moniker is root RCE in the container

**Status: FIXED on `dev` (2026-08-18).** Operator chose fix rather than accept. Not yet a tagged release.

The entrypoint no longer bash-sources env files. `deploy/load_env_exports.py` parses `KEY=VALUE` as literals and emits `export KEY=quoted` for `eval`. `write_env_key` quotes with `shlex.quote`, so even an accidental `. node.env` will not run `$()` or a spaced name. `MIRAGE_EXTERNAL_ADDRESS` and the ipify responses must look like addresses before they are written. `recover.sh` uses the same loader.

Regression: `install.env_write.answers_reach_their_own_files` (quoted write + source and loader must leave a `$(touch …)` payload unexecuted), `install.external_address.rejects_injection`.

**Privilege required:** the operator, or anything that can set `MIRAGE_MONIKER` / `MIRAGE_EXTERNAL_ADDRESS` for an unattended install. **Cost:** one accepted prompt. **Effect:** arbitrary commands as root in the `mirage` container, with `/root/.mirage` mounted, after `identity()` has imported the seed and consensus key.

`write_env_key` writes a raw `KEY=value` line with no quoting (`deploy/install.sh:737`). The entrypoint then bash-sources every env file:

```46:51:deploy/entrypoint.sh
load_env_files() {
  for envfile in "${ENV_DIR}/backend.env" "${ENV_DIR}/node.env" "${ENV_DIR}/indexer.env" "${ENV_DIR}/frontend.env" "${ENV_DIR}/secrets.env"; do
    if [ -f "$envfile" ]; then
      set -a
      . "$envfile"
```

Moniker validation is `^[[:print:]]{1,70}$` (`deploy/install.sh:627`). Spaces, `$()`, backticks, `;` and `|` all pass. The installer test suite treats that as intended: `MIRAGE_MONIKER="  spaced name  "` is a passing case, and `write_env_key MONIKER "chosen name"` is the golden write.

Verified by executing a `set -euo pipefail; set -a; . node.env` of installer-shaped files:

| `node.env` line | What bash did |
| :--- | :--- |
| `MONIKER=Cool Node` | `Node: command not found`, exit 127. With `set -e` the entrypoint dies. |
| `MONIKER=legit$(echo PWNED)` | Command substitution ran; `MONIKER` became `legitPWNED`. |
| `EXTERNAL_ADDRESS=tcp://9.9.9.9:26656; echo PWNED` | `PWNED` printed; the assignment kept only the address. |

`MIRAGE_EXTERNAL_ADDRESS` has **zero** validation (`deploy/install.sh:572-573`) and is written to the same file.

The default moniker (chain username, `^[A-Za-z0-9-]+$`) is safe. Docker `--env-file` does not expand the value — the break is only the sourced copy. `create_validator.sh` passes the moniker through `jq --arg`, which is also safe. Domain is a hostname regex and is safe.

**Why High not Critical.** It is not unprivileged remote: the operator already has root and just typed the seed. It is High because the *documented, tested* multi-word name is enough to abort the node after keys land, and a `$()` or semicolon is identity theft without any second bug. Rated the same class as the 2026-08-13 remote-`eval` finding, against operator-shaped input rather than a remote RPC.

---

## H-2 (High) — Forensic snapshot can fail open, then wipe

**Status: FIXED on `dev` (2026-08-18).** Operator chose fix rather than accept. Not yet a tagged release.

`mkdir` failure and per-dir `mv`/`cp` failure now `die`, so `wipe_chain_dbs` never reaches `rm`. Regression: `recover.forensic.snapshot_failure_aborts_wipe`.

**Privilege required:** a recovery that reaches `wipe_chain_dbs` (watchdog with key, or an operator `--auto`). **Effect:** the diverged chain DBs are destroyed and the forensic copy is missing or incomplete, which is exactly the loss `AGENTS.md` forbids.

```430:430:scripts/recover.sh
  mkdir -p "$cap" || { log "WARNING: could not create forensic dir $cap; skipping snapshot"; return 0; }
```

```441:442:scripts/recover.sh
      log "WARNING: failed to preserve $d into forensic capture"
    fi
```

`wipe_chain_dbs` always calls `snapshot_diverged_state` then `rm -rf` the seven DB directories. If `mkdir` fails (disk full, permissions, mount), the function returns **success** and wipe deletes the live DBs in place. If `mkdir` succeeds but `mv`/`cp` of a dir fails, that dir is warn-only and still deleted. `dirs_captured=0` is recorded in `MANIFEST.txt` and is not a hard stop.

`dirs_captured=0` used to be recorded in `MANIFEST.txt` and was not a hard stop. That is the defect the `die` closes.

---

## Candidates chased and killed

A clean Critical/High result is only meaningful if the attempts are visible.

| Candidate | Why it died |
| :--- | :--- |
| Compromised GHCR image at a signed digest | The digest *is* the image. Substitution requires a SHA-256 collision or the signing key, which is the TCB. |
| Mirror serves a backdoored `release_verify.py` | Hash pin in `install.sh`. Changing the pin requires changing the installer (TOFU). |
| Image replaces the host verifier with a lying copy | Refused unless `pubkey.pem` in the image matches the installer-embedded key. A lying verifier that still ships the real key cannot verify a forged manifest. |
| Replaying an old signed network manifest to pin dead/malicious peers | Expiry is enforced at verify time; the updater refuses `generation < last_gen` and a same-generation body change. First install has no last-gen, but genesis is independently hash-pinned in `bootstrap_join.py`, so an old peer list cannot join a different chain. |
| `eval` of remote state-sync values (the 2026-08-13 H-2 shape) | `init.sh` reads `KEY=VALUE` lines, accepts four keys, hex-checks the hash. `bootstrap_join.py` also rejects a non-64-hex `block_id.hash`. |
| Unsigned `STATESYNC_*` values with metacharacters | Producer and consumer both constrain the hash; height is digits; enable must be `true`. RPC server list comes from the signed `BOOTSTRAP_RPC` set. |
| `agree_json` split on comma inside a signed URL | Requires a signed URL containing a comma. Signing key is TCB. Two endpoints must also agree. |
| urllib follows HTTPS redirects to attacker/metadata | Redirect target is not in the signed list; the two signed endpoints would have to both redirect to the same attacker body. Needs control of the signed API hosts or the key. |
| Forged profile during preflight | Username is compared across at least two signed API hosts; balance and validator-set pages compare the whole document. One lying node cannot pass. |
| Skip the double-sign check by failing pagination | 1000-page ceiling dies rather than passing; query errors die rather than reporting unregistered. |
| Enroll while catching up / slash via double-sign | Timer no-ops on `waiting_for_rpc` / `syncing`. Collision guard has already refused a key that is live elsewhere. |
| Auto-recovery wipes on upgrade halt (installer default) | **Fixed on `dev` 2026-08-18.** Process-dead with upgrade-halt in recent logs alerts and refuses restart/wipe. `recover.sh` peer-pull dies unless a peer is strictly ahead of a known local height. |
| Auto-recovery wipes without a forensic snapshot | Filed as **H-2**. The `mkdir`/`mv` fail-open is the finding; the "always snapshot" comment is what it violates. **Fixed on `dev` 2026-08-18.** |
| Path traversal on `/.well-known/mirage/` | Caddy handle is prefix-matched; `file_server` root is `/root/.mirage/well-known`. Path normalisation would miss the handle before it could leave that directory. Directory listing is off. |
| Well-known serving `install.sh` as a backdoor | A node serves the copy from its verified image. Fetching it is TOFU of that origin; GitHub `install.sh` plus `MIRAGE_MANIFEST_MIRROR` still hash-pins helpers and signature-checks manifests. |
| Moniker / domain / uploads as a *remote* injection | Domain is a hostname regex. Uploads is a boolean. Username default is `[A-Za-z0-9-]+`. A remote party cannot set `MONIKER` without already being the operator or controlling their environment. The *local* sourcing bug is H-1, not this. |
| Unvalidated `api.ipify.org` body written to `EXTERNAL_ADDRESS` | Same sink as H-1. Exploitation needs compromising ipify or a CA, so it is not a separate High; fixing H-1's write/source contract kills it. |
| Release manifests never expire; git history still has valid sigs for `v1.36.4`–`v1.36.8` | **Accepted as risk 2026-08-18.** True TUF-style gap, Medium not High. Existing nodes refuse `release_id < last_release_id`. |
| `enable_validator_mode` overwrites `priv_validator_state.json` to head+5 on every container start | **Fixed on `dev` 2026-08-18.** Never lowers an existing watermark; skips the write while `catching_up`. Weekly restart also skips `catching_up`. |
| Host tools from a staged image run before the operator activates the container | **Fixed on `dev` 2026-08-18.** `--tick` pulls and stages only; host tools install from the staged image after a healthy activation. |
| `mirage-update` marks a failed activation as `active` | **Accepted as risk 2026-08-18.** State-machine bug, availability only. The previous image is left running if rollback is attempted and works; if not, the node is already down. No fund movement. |
| `stake.py` drains below the liquid floor | Reads `min_liquid_umirage` from the on-disk signed network manifest; refuses to go below it. Not in the unattended installer path. |
| New ports published | `mirage-launch` publishes 80, 443, 26656, 26657 only. 1317/9090 stay inside the container (the 2026-08-13 H-3 class). |
| v1.37.0 chain handler changes AppHash | Handler runs `RunMigrations` and returns. Comment and release notes state mixed `v1.36.8`/`v1.37.0` binaries are identical on a given block. |

---

## What remains open (not Critical/High)

Every leftover from this pass was asked and answered on 2026-08-18. H-1, H-2, host-tools-on-activate, upgrade-halt wipe, watermark, NT-5 and the UTF-8 memo halt are **fixed in `v1.37.0`**. Release-manifest expiry and the failed-activation `active` mark are **accepted as risk**. The 2026-08-17 network-tag tail is accepted except NT-4 (retention), which stays deferred until growth is observed.

---

## Maintaining

H-1 and H-2 stay visible in the register until a tagged retest records them closed. The upgrade-halt landmine is closed on `dev`; do not re-open it as High unless a later change routes process-dead to peer-pull again without consulting `UPGRADE_HALT_RE`.
