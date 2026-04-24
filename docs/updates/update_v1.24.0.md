# Mirage v1.24.0 Release Notes

### Never-Halt Invariant

The chain's per-block logic no longer treats internal write or read failures as a reason to halt. Previously a corrupted parameter row, a transient store error, or a single failed coin movement inside BeginBlock or EndBlock could panic the node and stall block production across the network. In v1.24.0 those paths log the failure loudly and continue; affected state simply does not advance for that block and is retried on the next one. The policy is explicit: stopping the chain is worse than running a block on default parameters or losing one tick of a calm counter.

### Validator-Isolated Minting

Minting is now computed per validator. If a validator has an operator address that does not parse, their share of the interval's mint is skipped and never created, instead of crashing the whole mint. If the per-validator transfer fails after minting, the same amount is burned from the core module account so total supply stays neutral. If that burn also fails, the residue is tracked as stuck-in-module and surfaced in the logs, and the rest of the validator payouts still complete. No single bad validator can stall issuance for everyone else.

### Award Cost Cap

Award configurations now have a hard upper bound of 1,000,000 MIRAGE per award. Governance proposals that try to set AwardConfig.Cost above this bound will fail validation at submission time. Default award configs are in the thousands of MIRAGE and are unaffected. If any chain state somehow stored a value above the cap, the node will log the mismatch and fall back to the default award table rather than halting.

### Cancel-Unbonding Restricted To Self

The ante handler that already restricted delegation, undelegation, and redelegation to self-validators now applies the same rule to MsgCancelUnbondingDelegation. A delegator can cancel an unbonding that belongs to their own validator, but cannot cancel one that belongs to someone else. This closes a small gap in the staking-access policy that the other staking messages already enforced.

### Upgrade Notes

The upgrade name is v1.24.0. There is no on-chain state migration, no new store key, and no deploy-side migration. All changes are code-level. The release must be coordinated because the cancel-unbonding rule and the award-cost bound change transaction acceptance, and the never-halt paths change state after runtime failures.
