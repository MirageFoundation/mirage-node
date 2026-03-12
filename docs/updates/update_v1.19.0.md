# Mirage v1.19.0 Release Notes

### Legacy Compatibility Window

This release restores posting and voting for older desktop and mobile clients that were stranded after the last security upgrade. If you are still on an older app build, v1.19.0 lets you keep using Mirage while you update.

At the same time, newer clients keep full replay protection with the envelope nonce already in use since v1.18.0. The temporary compatibility window accepts legacy messages without that nonce, which means replay protection is not enforced for those older clients. That tradeoff is intentional and short lived, and we want everyone on the safer path as soon as possible.

We are treating this as a bridge release. Once the mobile update is out and adoption is complete, the legacy path will be removed and the network will return to strict replay protection for all relay messages.

The upgrade name is v1.19.0 and the binary must be built from the v1.19.0 tag. No data migration is required, and existing clients that already include the nonce continue to work without changes. Legacy clients will be compatible again after the upgrade, but they should be updated promptly to regain full protection.
