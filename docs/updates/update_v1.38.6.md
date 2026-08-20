# Mirage v1.38.6 Release Notes

### Posts that would not open

Some people clicked a post and got nothing — a blank page, no error, no explanation. The cause was a deploy, and it is worth explaining because it could happen after any of them. Every release renames the small files the site loads on demand, one per screen. A browser tab that had the site open from before the release was still holding the old names, so the moment it asked for the page it needed, that file was no longer there under the name it knew. Instead of saying so, the server handed back the site's homepage, and the browser refused it: it had asked for a program and been given a document. The page stopped there.

Two things now prevent that. A file that genuinely is not there returns an honest "not found" rather than a page pretending to be one, and the site treats that as the signal it is: it reloads itself once, quietly, and lands on the current version. This already worked for people on Chrome, which is why it went unnoticed for so long — the recovery matched the wording Chrome uses when a file fails to load, and Firefox and Safari word it differently, so on those browsers nothing happened and the page simply stayed blank. It no longer reads the wording at all. Any failure to load a screen is taken as a sign the tab is out of date, which is the only thing it realistically means.

Worth being straight about the limit: this protects the next release, not the last one. The fix has to already be running in your browser to do anything, so if a post refused to open for you earlier, one refresh clears it.

### The earnings on your site now match your node

The last release fixed the earnings panel on the node dashboard — the one you see in the terminal. The website had its own copy of the same mistake, and that one was still there. It measured what a node earned by watching its balance go up and down, so every transfer somebody sent you counted as income, everything you sent counted as a loss, and any payout that arrived and moved on between two readings vanished entirely. The website now reads the same event-by-event record the dashboard does: rewards the chain actually paid this node, and fees this node actually paid. The panel also says "Spent" where it used to say "Burned", because fees are spent, not destroyed, and the old label described something the number never measured.

### One command to rejoin after an outage

When a node goes offline long enough, the chain stops counting it and takes a small slice of its stake — the mechanism that keeps unreliable validators from holding up everyone else. Getting back in afterwards is the operator's job; the chain will not do it for you, and until it is done the node runs without signing or earning. That step now has a name: `mirage-unjail`. It checks the things worth checking before it does anything — whether you are actually jailed, whether the waiting period is over, whether the node has finished catching up — and tells you which one is in the way instead of failing at the chain. It refuses outright while a node is still syncing, because rejoining before you can sign just gets you removed again on the next round.

There is one case it cannot help with, and it says so plainly rather than trying: a validator penalised for signing two different versions of the same block is removed permanently, and no command brings it back.

Underneath, the tool that does the work had a flaw worth mentioning. It read the jailing details from a chain-wide list and guessed which entry belonged to you, picking whichever had been jailed most recently. With a single validator jailed that guess happens to be right. With several jailed at once — which is exactly what a network-wide outage produces — it could read somebody else's waiting period and tell you to wait when you were free to go. It now looks up your own record directly.

### What this means for your node

This is an ordinary release with no governance vote and no scheduled halt, so install it whenever suits you with `mirage-update`. Nothing here changes how blocks are processed, so old and new nodes agree on everything and there is no risk of a split while the network updates at its own pace. If you run a public node, the deploy fix matters to your visitors and the earnings fix to anything reading your site's numbers; if you have ever been jailed, `mirage-unjail` is waiting the next time it happens.
