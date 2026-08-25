# Mirage v1.38.11 Release Notes

### The padlock that wasn't there

Some of you told us your phone was calling Mirage unsafe, and your phone was right. If you typed the address by hand, or tapped a link someone had pasted as plain text, your browser reached us over an unencrypted connection and we answered anyway. The secure version of the site had been working the whole time and had a valid certificate — we simply never insisted on it. Anyone who arrived the secure way, which is almost everyone almost always, was fine. Anyone who arrived the other way got a working page and a warning telling them not to trust it.

### Why the wallet refused to open

The warning was the polite version of the problem. Browsers reserve their strongest tools for connections they trust, and the machinery that encrypts your recovery phrase and lets you sign in with a passkey is on that list. Over an unencrypted connection it isn't merely discouraged, it is absent. So the handful of people who landed on the insecure address were not looking at a cosmetic scare: they could not create an account or unlock an existing one, and the page had no way to explain why. That is the "I tried to get on the site and it wouldn't load" some of you reported.

### Two locks, and they do different jobs

The fix is in two places because one alone would not be enough. Our network edge now turns away unencrypted requests and sends them straight to the secure address, which is what protects somebody visiting for the first time. The site itself now also tells your browser to remember, for a year, that Mirage is only ever to be reached securely — so from your second visit onward your browser refuses to try the insecure route at all, and never sends that first request. Together they close the door from both sides.

### What we still can't promise

We would rather say this plainly than let you assume more than we have delivered. The very first time a new visitor types the address without the secure prefix, their browser still makes one unencrypted attempt before being redirected, and that attempt reveals that someone at that connection is going to Mirage. Nothing we control can prevent it. The complete fix is to be added to the list of sites that browsers ship knowing are secure-only, which removes even that first attempt — but that list is a commitment measured in months and is not something to opt into in a hurry. We have not done it. Some newer web addresses get this treatment automatically because of their ending; ours do not.

### A missing header that could not stay missing

The uncomfortable detail is that a security review this month looked straight at this and recorded it as handled, on the reasonable-sounding assumption that our web server added the protection by itself. It never has. That is a category of mistake that documentation cannot fix, so instead the protection is now checked automatically on every change, alongside the other defences guarding the page your keys live on. If someone deletes it, the build fails and says so. We confirmed the check fails before trusting it.

### What this means for your node

This is an ordinary release with no governance vote and no scheduled halt — install it whenever suits you. Nothing here touches how blocks are produced or validated, so old and new nodes agree completely and there is no risk of the network splitting over it. Nodes reachable by a domain name gain the new protection as soon as they restart. Nodes reached only by a bare address are deliberately untouched, since a certificate cannot be issued for them and promising security we cannot deliver would break those nodes rather than protect them. A single `mirage-update` is all it takes.
