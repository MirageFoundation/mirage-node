# Mirage v1.29.0 Release Notes

### One front door for everything

v1.29.0 consolidates how media and traffic reach Mirage. Instead of stitching together separate services for uploads, content delivery, and abuse protection, the flagship nodes now sit behind a single edge vendor that handles all of it at once. The practical payoff is a faster, more resilient front door: image and video delivery is cached close to you around the world, and the heavy lifting of soaking up malicious traffic happens at the edge before it ever reaches a node. Each node moves independently, so if one ever has a bad day the others keep serving.

### Safety scanning that fails closed

The most important change is invisible when everything is working as it should. Uploads to the public nodes now pass through edge safety scanning that checks for known child sexual abuse material in transit and refuses anything that matches, reporting it automatically. We pair that with a strict rule on the rest of the fleet: any node that is not behind a scanning edge simply does not accept public uploads at all. There is no quiet fallback that would let unscanned content slip in through a side door. If the scanning layer is not present, the upload door is closed, full stop.

### Longer videos

Creators kept bumping into a short ceiling on video, so we raised it substantially. You can now post videos up to roughly thirty minutes, with the file-size limit lifted to match, and the upload path was widened end to end so larger clips actually make it through rather than failing partway. Shorter clips behave exactly as before; this only removes a wall that longer-form posts kept hitting.

### A quieter community on mirage.talk

mirage.talk now ships with an anti-spam agent switched on by default for everyone. It works in the background to keep the obvious junk out of feeds without you having to opt in or configure anything. It is enabled only on mirage.talk, and like any agent you remain in control: if you would rather run without it, you can turn it off in your settings.

### The plumbing that makes it trustworthy

Putting a network in front of the nodes only helps if the nodes themselves are locked down behind it, so this release tightens the seams. Each edge-fronted node now learns the real visitor address from its edge rather than seeing every request as coming from the network itself, which keeps rate limiting and abuse handling honest. Live API and chain responses are marked so the edge never caches them, so what you read is always current. And the origin servers are firewalled to accept secure traffic only from the edge, which is what makes the upload scanning impossible to bypass by knocking on a node directly. Certificate renewal continues to work through a dedicated origin name so this lockdown never interrupts secure connections.

### Honest about the limits

This is a real reduction in risk, not a guarantee, and it is worth being clear about the edges of it. The in-transit scanning is strongest on images; it does not deeply inspect every frame of a video, so longer video in particular still carries residual risk that we manage with the fail-closed gate and reporting rather than pretend away. Leaning on a single edge vendor also means the public experience now depends on that vendor being up; we accept that tradeoff deliberately because consolidating uploads, delivery, and protection in one place is what makes the safety guarantees enforceable in the first place, and the underlying chain keeps running regardless. Finally, these protections apply to the nodes that run behind the edge — the safety of content on any given node is only as strong as the front door it chose to put up.
