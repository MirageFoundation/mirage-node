# Mirage v1.36.8 Release Notes

### Setting up a node no longer fails for being slow

The installer used to give a new server two minutes to bring the node up, and then declare the install broken. Two minutes is plenty for a restart, which is what the number was quietly based on: the validators carrying Mirage today come back in about thirty-five seconds. A brand-new server has more to do. It builds its databases from nothing, applies every migration to them, fetches and verifies the network's genesis, and begins syncing the chain — and on a modest cloud plan that work can outlast the deadline. The node was healthy and making progress; the installer simply stopped watching and called it a failure.

### Patient about slow, immediate about broken

Raising a deadline is the lazy fix, because a longer wait also means longer before you learn something is genuinely wrong. So the wait now distinguishes the two. It allows fifteen minutes for a first boot, prints what the node is doing every thirty seconds so you can see it moving, and if the container actually dies or starts crash-looping it stops right then and shows you the node's own last twenty lines of output instead of counting down in silence. Resuming a half-finished install also no longer restarts a node that is already up and syncing, which used to throw away sync progress for nothing.

### The same mistake, somewhere it mattered more

That two-minute deadline appeared in a second place: the updater, which uses it to decide whether a newly activated release is healthy, and rolls the release back when it expires. The releases most likely to take a long time to start are exactly the ones that carry a database migration — so the update most in need of finishing was the one most likely to be undone and reported as a failure. That wait now has the same generous budget and the same fast reaction to a real crash, so a rollback happens because a release is broken, never because it was slow.

### Recovery phrases survive being pasted

Extra spaces between words were always tolerated, but several things that merely look like spaces were not. A no-break space, the kind a password manager or a web page will hand you, made all twelve words register as one. Terminal paste markers attached invisible characters to the first and last word, a phrase copied from Windows picked up a stray carriage return, and capitalised words were rejected outright. All of these now normalise to the same twelve words, and the prompt says plainly that the phrase goes on one line with a space between each word — worth stating, since the phrase stays hidden while you paste it. What has not changed is the checking: eleven words or thirteen are still refused, and every word is still verified against the standard wordlist with its checksum.

### An error message that was not an error

Installs on servers without IPv6 printed a connection failure for an IPv6 address lookup. The address is optional and the failure was already harmless, but it appeared in the middle of an otherwise clean install and looked like the thing that went wrong. The check now runs only where the machine actually has a global IPv6 address, and a machine that has one but cannot reach the lookup still gets a real warning rather than silence.

### Enrollment waits for its own transaction

Registering as a validator broadcasts a transaction that stays valid for two minutes, then waited only sixty seconds for it to appear. At roughly three and a half seconds per block, a transaction that landed a little late made enrollment report failure for a validator that registered moments afterwards. The wait now outlasts the window the transaction itself allows.

### No chain upgrade

This release changes host preparation, the installer and the updater only. Transactions, consensus state, validator keys and the application hash are untouched, so no governance halt is required and nodes running v1.36.7 and v1.36.8 cannot fork because of this update.
