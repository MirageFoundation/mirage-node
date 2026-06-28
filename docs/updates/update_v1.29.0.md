# Mirage v1.29.0 Release Notes

### One front door for everything

v1.29.0 consolidates how media and traffic reach Mirage. Instead of stitching together separate services for uploads, content delivery, and abuse protection, the flagship nodes now sit behind a single edge that handles all of it at once. Image and video delivery is cached close to you around the world, malicious traffic gets soaked up at the edge before it ever reaches a node, and every node still moves independently, so if one ever has a bad day the others keep right on serving.

### Illegal content dies at the door

This is the part that matters most. Every upload to the public nodes is scanned for known child sexual abuse material in transit, right at the image and video host, before it is ever stored or served. A match is refused on the spot — and here is the important bit — it is reported automatically by the edge provider straight to the authorities. It never reaches a Mirage node, never lands on Mirage's servers, never touches the chain. So if someone tries to upload that filth here, they are not uploading to Mirage. They are uploading directly to law enforcement — effectively straight to the FBI's inbox — with their connection details attached. Scanning is strongest on still images and does not deeply inspect every frame of a long video, which is exactly why the door stays fail-closed rather than relying on the scan alone.

### Longer videos — yes, you asked for it

You asked. Loudly. Repeatedly. We listened. Video is now up to roughly 30 minutes per post, with the file-size ceiling lifted to match and the entire upload path widened end to end so big clips actually make it through instead of dying halfway. Short clips behave exactly as before — this just tears down the wall that long-form posts kept slamming into. Just note that large uploads can take a while for transcoding to complete. While we are here: every video now shows a clean preview frame with a play button the instant you post it, instead of a blank tile sitting there until processing catches up.

### Your post shows up instantly

No more staring at "verifying post" for 5-6 seconds wondering if it worked. The moment your post hits the network, it appears in your feed — instantly. We stopped waiting around for the chain to confirm and re-index before showing it to you; the network has it, so you see it, right now. This is live on the web today, and it is coming to mobile the moment our next app update drops.

### Browse first, sign up when you're ready

You no longer need an account just to look around. Feeds, posts, profiles, and search are open to everyone now — read the whole thing, see what Mirage actually is, and you only get asked to create an account the moment you want to do something: post, vote, follow, or reply. The prompt is a clean signup modal that appears exactly when you act, not a wall thrown up the second you arrive. And the look is yours from the very first second — logged in or not, you can switch themes and adjust the appearance from any screen. If you want the full picture before diving in, the FAQ now sits right at the top of the sidebar and has been expanded to spell out how the safety scanning and the moderation agents actually work.

### Save what you love

Images and videos can now be downloaded straight from a post's menu. The download lives in the post's "…" menu instead of cluttering the media itself, resolves the real high-quality file behind it, and works the same way across every theme.

### A quieter mirage.talk, or the raw feed on mirage.vote

mirage.talk now runs the AntiSpamBot agent switched on by default for everyone. It works quietly in the background to keep the obvious junk out of your feed with nothing to opt into and nothing to configure — and like any agent, you stay in control and can turn it off in your settings whenever you want. Prefer the completely unfiltered, raw experience with no spam agent standing between you and the feed? That is exactly what our sister node mirage.vote is for. Same network, same chain, your choice of front door — and this is what seamless identity really means. Don't like the node you are on? Just switch. Your account, your handle, your followers, your posts, and your balance all live on the chain, not on any single node, so they come with you the moment you walk through a different door. No new sign-up, no migration, no starting over — one identity, every node.

### Referral bonuses are switched off

We have turned off the referral rewards across the entire fleet. Quests are still very much alive — keep earning the way you always have. The one thing we removed is the payout for bringing in new accounts, because referral bounties are simply too easy to game: anyone can spin up unlimited accounts and farm the reward endlessly, so it was always going to be gamed rather than earned. You can still share invites — there just is not a token payout riding on them anymore.
