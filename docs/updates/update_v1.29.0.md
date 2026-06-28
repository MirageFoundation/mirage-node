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

### Every image and video now carries a Mirage watermark

From this release on, every image and video uploaded to the public nodes is stamped with a Mirage watermark as it is processed. The point is provenance: when a post leaves the platform — saved, screenshotted, reposted somewhere else — it still says where it came from, so Mirage content stays attributable out in the wild. It applies uniformly to everything, photos and clips alike, with nothing to enable. The honest tradeoff is that a watermark is a visible mark on your media, not an invisible one or a cryptographic signature, so it can be cropped or edited out by anyone determined to do so — it is there to credit the source on normal sharing, not to be tamper-proof.

### A quieter mirage.talk, or the raw feed on mirage.vote

Two things are going on here, and they are easy to mix up, so let's take them one at a time.

But first, a word on what an "agent" even is, because the whole thing makes a lot more sense once that clicks. Mirage has no global moderators — nobody can delete your post for everyone or ban you from the network. Instead there are **agents**: optional helpers, usually bots, that you switch on to clean up *your own* view of the feed. One hides spam. Another softens hostile posts. Another translates foreign-language posts, or fixes a post filed under the wrong topic, or staples a fact-check note onto something dubious. The key thing is that an agent never touches the original post on the network — it only changes what *you* see, and only if you have turned it on. You browse the Agents page, pick the ones you trust, and your choices follow you from node to node. Think of them as lenses you choose to look through, not rules imposed on everyone.

With that in mind, the spam filter. mirage.talk now turns on one agent — the **AntiSpamBot** — for every account by default. All it does is quietly hide the obvious junk from your feed: the scams, the copy-paste floods, the bot noise. There is nothing to set up and nothing to configure; it is simply on. Now the honest part: on mirage.talk this one is enforced by the node, so unlike the agents you choose yourself, you cannot switch the AntiSpamBot off while you are on mirage.talk — it shows up locked. That is a deliberate choice to keep this particular front door clean for everyone. If you want it gone, you do not toggle it off; you walk through a different door.

Second, what mirage.vote is: mirage.vote is a sister node, and it ships with that spam filter left off — a completely raw, unfiltered feed straight from the network. It is not a different app or a different account system. It is the same Mirage, the same chain, just a different front door with different defaults.

And here is the part worth understanding, because it is what makes the two interchangeable: your identity does not live on mirage.talk or mirage.vote. It lives on the chain. Your handle, your followers, your posts, and your balance are all tied to your seed phrase, not to any one node. So "switching" is not a migration — there is nothing to export and nothing to rebuild. Enter the same seed phrase on mirage.vote and you simply *are* the same person there, instantly, with everything intact. One identity, any node, your choice of front door.

And mirage.talk and mirage.vote are not the only doors — they are just the two we happen to run. Because everything that matters lives on the chain, **anyone can stand up their own node**, set their own defaults, and run their own front door into the exact same network. You do not even have to run a full node to do it, and this is not theoretical: the exact frontend that powers mirage.talk lives right in the open-source repo, and you can run it on your own machine with a single command. It asks which node you want to point it at, installs itself, and opens in your browser — your account works there immediately, untouched. From there it is yours to reskin and re-rule however you like: your own look, your own choice of which agents are on, your own everything.

That is the whole point of putting identity on the chain instead of on a server. The network is not something we own and rent back to you; it is open, and the front door you walk through can be ours, a friend's, or one you spin up on your own laptop in about a minute.

### Referral bonuses are switched off

We have turned off the referral rewards across the entire fleet. Quests are still very much alive — keep earning the way you always have. The one thing we removed is the payout for bringing in new accounts, because referral bounties are simply too easy to game: anyone can spin up unlimited accounts and farm the reward endlessly, so it was always going to be gamed rather than earned. You can still share invites — there just is not a token payout riding on them anymore.
