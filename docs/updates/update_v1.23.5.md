# Mirage v1.23.5 Release Notes

### Fresh Feed, Every Time

Your feed now remembers what you've already seen. Scroll past a post a couple times, stare at it for three seconds, or tap into it — Mirage tracks all of that and pushes fresh content to the top on your next visit. This works across page refreshes and persists server-side, so switching devices won't reset your feed.

The system is lightweight by design. Your client quietly reports seen posts to the server every few seconds, and the server keeps a rolling window of your last 1,000 viewed posts. When you load the feed, anything you've already seen gets filtered out. If you've genuinely seen everything, the feed doesn't go blank — it resurfaces the posts you've viewed the least, so there's always something to scroll through.

### Your Own Posts Stay Out of the Way

Nobody wants to see their own post dominating the top of their feed hours after publishing. Your own posts now get the same treatment as everyone else's after one hour. During that first hour they're still pinned so you can watch engagement roll in, but after that they compete on the same terms as everything else.

### Smoother Mobile Voting

Tapping the upvote or downvote button on mobile no longer causes the feed to jump. Previously, the browser would scroll to keep the focused button in view after the vote animation — a subtle but annoying glitch on phones. That's gone now.

### Onyx Theme

A new dark theme called Onyx is available alongside Blue Moon and Old Reddit. It's a refined take on the Blue Moon aesthetic with its own styling and feed layout.
