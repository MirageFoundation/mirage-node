# Mirage v1.33.0 Release Notes

### Claiming rewards is yours alone

Claiming pending rewards now requires a signature from the account that owns them. That stops a stranger from locking in your payout multiplier early — rewards scale with how many quests you have finished, so the moment you claim matters. Installed mobile builds keep working without a signature for a short grace period while the app update ships; after that cutoff, unsigned claims are refused.

### Moderation actions prove who called them

Reading the report queue, clearing a report, and suspending or unsuspending someone from rewards all require a signed proof from an admin key. Naming an admin's public address is no longer enough. The web UI already sends those signatures; the mobile app has no moderation screens, so nothing changes there.

### Invite codes stay off

Open registration remains the default. The invite-code endpoints now return not found while that feature is disabled, so unused codes cannot be listed or validated on a node that is not using them. If a node ever turns invites back on, listing codes will require a signature and validation will no longer reveal who issued a code.

### Smaller hardening

Upload size limits are enforced in the application before a body is read into memory. Client IP hashing refuses to start without a stable salt, so analytics and gating keys stay consistent across workers. Debug and quest-roll locality checks no longer trust a client-supplied forwarded-for header.
