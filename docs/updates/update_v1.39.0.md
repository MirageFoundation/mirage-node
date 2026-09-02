# Mirage v1.39.0 Release Notes

### Communities, not topics

The places you post are communities now. Open one at `/c/` plus its name, browse the directory at `/communities`, and join the ones you actually want in your home feed. Every valid community name is open for conversation immediately—there is no registration, founder, owner, or claim.

### Curation you choose

Paid subscribers and admins can start competing curator teams for any community. Teams publish a description (including how they moderate), invite other eligible curators who must accept, and earn the default position by attracting the most paid users who explicitly select them. Free accounts cannot lead teams; subscribers can join up to ten, and admins up to one thousand. A community with no team remains uncurated and is shown raw. Curators can hide a post or user in their own lens, lock a thread, or limit that lens to subscriber posts, but they never own the community or rewrite anyone else's words. Raw view remains available wherever node policy permits it.

### Joining keeps the view you joined for

Whichever view you are reading when you hit Join is the one you keep. Pick a team and you are recorded against that team; read the uncensored feed and you stay uncensored; take the community's default and you are locked to the team that default names at that moment. Nothing about your feed reshuffles later because a rival team pulled ahead. This is deliberate: previously everyone who joined without touching the picker sat in a shared pool that followed whichever team led the count, so a handful of paid accounts could take the top spot and inherit an entire community's moderation in one move. Being counted where you actually chose to be closes that. The trade is that you no longer drift toward the community's current favourite on your own—if the team you joined under goes quiet, switching is a deliberate click in the lens picker, exactly as it always was. Joining a community that has no team yet leaves you uncensored, because there is nothing there to pin.

### Locking a thread is a cut-off, not a delete

When a curator locks a thread, that lens stops showing anything written from that moment on. It is a line drawn in time rather than a switch on the whole conversation, so the replies already there stay exactly where they were. Unlocking reopens the thread for new replies; it does not publish the ones written while it was shut, and a curator who locks the same thread again a week later draws a second line without disturbing the first. Locking twice by accident changes nothing. A team can draw up to a hundred of those lines on any one thread, after which the chain stops accepting new locks on it—each line has to be remembered forever to keep working, and forgetting the oldest one would quietly republish what it hid.

Be clear about what a lock is not. It is not a write gate: nothing stops you from replying to a locked thread, your reply is accepted by the network like any other, and it is still there in the uncensored view for anyone who wants to read it. What a lock does is tell one curator team's lens to stop carrying new arrivals, which is a decision about that team's feed and not about your words. The client will tell you a thread is locked before you spend the effort, and switching to raw shows you everything that team's readers are not seeing.

### Deleting a post now sticks

If you deleted one of your own posts and later edited it, it came back. The delete worked, the post vanished from every feed, and then the edit quietly put it back on the shelves as though nothing had happened — with the standing it had earned still written off, so the ranking maths disagreed with itself from then on. That is fixed: a delete is final, and an edit naming a removed post is ignored rather than treated as permission to republish it. This upgrade also goes back through the archive and re-removes anything that came back this way, using the network's own record of what was deleted. One honest limit: posts made before this version's new post format do not carry that record, so a handful of very old revivals cannot be told apart from ordinary posts and stay where they are. Nothing new can slip through.

### Tags that reflect where you actually are

Content tags used to depend entirely on whoever hit publish, which works right up until someone forgets. Now a curator team leader can tag a whole community at once, so an adult community reads as adult without asking every poster to remember, and any curator on the team can correct the tag on a single post that came in mislabeled. Nothing new gets invented here: curators pick from the same short list you already filter on, and a post still carries one tag.

Being tagged is not being hidden. A tag only tells your content settings what the post is, and your settings decide the rest, exactly as before. A curator's correction reaches the people reading through that curator's lens, while the community tag travels with the community everywhere, uncensored view included, because describing content honestly is a different thing from removing it. When two of them disagree, the specific beats the general: a curator's call on one post wins over the community tag, and the community tag wins over what the author typed.

### A creator pool instead of quests

Half of every new subscription payment is burned. The other half funds a pool for authors who received an upvote or a direct reply from a paying subscriber during the payout period. The split is equal among those subscribers, then among the actions they took, so one frantic account cannot vacuum the pool. Authors have thirty days after a period settles to claim what they earned. Unused remainder is burned. There is no quest board, no invite bonus, and no referral payout in this version. Campaign `ref=` links still tell you where a visitor came from; they just do not mint tokens.

How often that pool pays out is its own governance setting, and it is genuinely its own setting. It starts at once a day and can be shortened to as little as five minutes without shortening anybody's subscription, because a subscription's creator share is no longer chopped into one entry per payout period when you buy it — it flows into each period as that period actually happens. Paying out more often therefore costs nothing at purchase time, and it costs nothing afterwards either: changing the interval keeps the pool, keeps what people have already earned, and keeps every claim window open for the full thirty days it promised. The one thing to know is that payout periods are numbered, and a change starts a fresh stretch of numbering rather than renumbering what already settled, so the period a payout belongs to stays unambiguous.

### Subscriptions that are simpler to use

Subscribers no longer keep a relay reserve. Signed subscriber actions pay no fee and no proof of work, up to two hundred and fifty messages each UTC day. Appointed admins get the same instant path without buying a subscription, with a higher daily cap. You can buy one to twelve months at a time, and auto-renewal tries a week before expiry so you do not lose leftover paid time. Existing paid time is kept through the upgrade. The old agent tier is gone: those accounts become ordinary subscribers.

### Your name is your name

Free accounts no longer get "Anon-" glued onto their username. Subscribers already stand out with a color; the prefix was extra labeling that made new accounts look like they were not quite real. You pick a name, you get that name.

If you already have an Anon- name, it stays. This upgrade does not rename anyone. Open the username screen and change it if you want the prefix gone. The other side of this is honest too: a clean name is no longer something you pay for. The first person to claim a short or obvious handle keeps it, paid or not.

### What this upgrade asks of you

This is a chain upgrade. Nodes halt on the governance plan, install v1.39.0, and resume. Old topic, agent, quest, and invite APIs answer `gone`. A post client that does not send protocol version 1 is told to upgrade. Free users still post with fees and proof of work. Paid users who hit the daily cap wait until the next UTC day; there is no extra quota for sale.
