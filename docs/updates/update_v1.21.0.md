# Mirage v1.21.0 Release Notes

### Governance Authority Protection

A new security layer now screens every transaction entering the mempool for governance authority spoofing. On Cosmos chains, governance proposals execute with the governance module's own address as the message authority. Before v1.21.0, nothing stopped someone from broadcasting a regular transaction that claimed to be from that same address. The chain would reject it during execution, but the transaction still consumed validator resources getting that far.

The new GovAuthorityDecorator catches these spoofed transactions at the ante handler stage, before signature verification or gas deduction even runs. Any broadcast transaction — whether it arrives through the standard SDK path or through the relay envelope — that sets its authority field to the governance module address is immediately rejected. Legitimate governance proposals continue to work exactly as before because they flow through the governance module's own EndBlocker, not through the public mempool.

### Mandatory Nonce Finalization

The temporary legacy nonce compatibility introduced in v1.19.0 and made mandatory in v1.20.0 is now fully cleaned up at the code level. All conditional branches that checked for the legacy zero-nonce path have been removed from the binary. The canonical encoding functions now unconditionally include the envelope nonce field, and the signature verification path no longer contains any fallback logic.

From a user perspective nothing changes — envelope nonce has been mandatory since v1.20.0 and all clients were already updated. This release simply strips the dead code paths so the codebase is cleaner and there is zero ambiguity about what the chain accepts.

### Relay Ante Chain Refactor

The relay transaction processing pipeline has been refactored from a manually chained sequence of handler calls to the standard `sdk.ChainAnteDecorators()` pattern used by the rest of the Cosmos SDK. This brings the relay path in line with the standard transaction path, making it easier to add or reorder decorators in the future without risking subtle execution order bugs. The governance authority check is wired into both paths through this unified decorator chain.

### Upgrade Instructions

The upgrade name is `v1.21.0` and the binary must be built from the `v1.21.0` tag. No data migration is required and no operator action is needed beyond the standard binary swap. All existing clients continue to work without changes.
