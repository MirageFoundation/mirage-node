# Mirage v1.29.0 Release Notes

### One front door for everything

v1.29.0 consolidates how media and traffic reach Mirage. Instead of stitching together separate services for uploads, content delivery, and abuse protection, the flagship nodes now sit behind a single edge that handles all of it at once. Image and video delivery is cached close to you around the world, malicious traffic gets soaked up at the edge before it ever reaches a node, and every node still moves independently, so if one ever has a bad day the others keep right on serving.

### Illegal content dies at the door

This is the part that matters most. Every upload to the public nodes is scanned for known child sexual abuse material in transit, right at the image and video host, before it is ever stored or served. A match is refused on the spot — and here is the important bit — it is reported automatically by the edge provider straight to the authorities. It never reaches a Mirage node, never lands on Mirage's servers, never touches the chain. So if someone tries to upload that filth here, they are not uploading to Mirage. They are uploading directly to law enforcement — effectively straight to the FBI's inbox — with their connection details attached. We made the bypass impossible, too: any node that is not sitting behind a scanning edge does not accept public uploads at all, full stop. There is no quiet side door for unscanned content. Scanning is strongest on still images and does not deeply inspect every frame of a long video, which is exactly why the door stays fail-closed rather than relying on the scan alone.

### Longer videos — yes, you asked for it

You asked. Loudly. Repeatedly. We listened. Video is now up to roughly thirty minutes per post, with the file-size ceiling lifted to match and the entire upload path widened end to end so big clips actually make it through instead of dying halfway. Short clips behave exactly as before — this just tears down the wall that long-form posts kept slamming into.

### Browse first, sign up when you're ready

You no longer need an account just to look around. Feeds, posts, profiles, and search are open to everyone now — read the whole thing, see what Mirage actually is, and you only get asked to create an account the moment you want to do something: post, vote, follow, or reply. The prompt is a clean signup modal that appears exactly when you act, not a wall thrown up the second you arrive. And the look is yours from the very first second — logged in or not, you can switch themes and adjust the appearance from any screen.

### Save what you love

Images and videos can now be downloaded straight from a post's menu. The download lives in the post's "…" menu instead of cluttering the media itself, resolves the real high-quality file behind it, and works the same way across every theme.

### A quieter mirage.talk, or the raw feed on mirage.vote

mirage.talk now runs the AntiSpamBot agent switched on by default for everyone. It works quietly in the background to keep the obvious junk out of your feed with nothing to opt into and nothing to configure — and like any agent, you stay in control and can turn it off in your settings whenever you want. Prefer the completely unfiltered, raw experience with no spam agent standing between you and the feed? That is exactly what our sister node mirage.vote is for. Same network, same chain, your choice of front door.

### Referral bonuses are switched off

We have turned off the referral payout program across the entire fleet. The old recruit-and-welcome bonuses that paid out for bringing in new accounts are no longer assigned or paid on any node, and the Referrals copy has been softened to match. We would rather grow on the strength of the product than on a bounty that mostly attracts reward-hunters, and removing it keeps the incentives clean. You can still share invites — there just is not a token payout riding on them anymore.

### The plumbing that makes it trustworthy

Putting a network in front of the nodes only helps if the nodes themselves are locked down behind it. Each edge-fronted node now learns your real address from its edge rather than seeing every visitor as the network itself, which keeps rate limiting and abuse handling honest. Live API and chain responses are marked never-cache, so what you read is always current. The origin servers accept secure traffic only from the edge — which is precisely what makes the upload scanning impossible to dodge by knocking on a node directly — while certificate renewal keeps flowing through a dedicated origin name so the lockdown never interrupts a secure connection.
