# Mirage v1.30.0 Release Notes

Opening Mirage should feel like the app was already waiting for you. Cold start now loads the screen you need in a single request — your feed, a thread from a notification, or your inbox — together with everything that used to trickle in afterward. The first paint is the final layout.

Threads no longer assemble themselves in pieces. Opening a reply shows the original post, the parent chain, and the replies underneath in one shot, so the page does not jump as more context arrives. Inbox taps prefetch as you press, so the thread is often ready the moment you land.

Rewards, invites, and the other cards above your feed arrive with that same first response. They no longer drop in a few seconds later and shove your posts down the screen. What you see when the splash clears is what you keep.

Notifications can open a cold app straight into the right thread without a second round of loading. Older app builds keep working against the previous endpoints until they update; the new path is additive where it matters and strict about not shifting the layout once you are looking at it.

Profiles now show how many users an account follows and how many users follow it. Open any profile and both numbers are right there with the rest of the account details — no extra taps, no guessing from a follow button alone.

Uploads now go through a single media endpoint. The temporary compatibility path for older upload clients has been retired. If something used to feel racy or unfinished on open, this release is the fix for that class of experience.
