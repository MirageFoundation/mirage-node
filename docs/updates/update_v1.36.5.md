# Mirage v1.36.5 Release Notes

### A new validator starts on fully updated Ubuntu

The one-command validator installer now updates Ubuntu’s package lists and applies the complete available operating-system upgrade before it installs Mirage. A fresh node no longer starts with whatever package versions happened to be baked into the provider’s Ubuntu image.

### Reboots are explicit and resumable

Kernel and core-system updates can require a reboot. When that happens, the installer finishes hardening the host, stops before starting Mirage, and asks the operator to reboot and run the same command again. The second run resumes from the recorded installation state rather than repeating or bypassing completed work.

### Updates stay noninteractive

Ubuntu upgrades use deterministic package-configuration handling and automatic service restart decisions, so a pasted installer does not stall behind an unseen package prompt. Daily security updates and the node’s staggered weekly full-upgrade window remain enabled after installation.

### No chain upgrade

This release changes host preparation only. It does not change transactions, consensus state, validator keys or the application hash, so it requires no governance halt and mixed v1.36.4 and v1.36.5 validators cannot fork because of this update.
