# Mirage v1.29.6 Release Notes

### Push notifications that follow you between accounts

If you use more than one account on the same phone, switching between them used to leave your notifications stuck. Your device hands out a single push identity that stays the same across logins and even reinstalls, and if the app couldn't cleanly release it on logout — say you were offline or the network hiccuped — the next account was locked out of notifications entirely, with no way to recover. This release fixes that: whichever account is signed in now takes ownership of the device's push channel automatically. Log in, and notifications simply start working for that account, no matter what happened on the way out of the last one.

### More reliable notification taps on Android

We also tightened up what happens when you tap a notification. Every push now carries a clear type and a stable identifier, so tapping a reply, a mention, an award, or a "you have unread messages" summary reliably opens the right place in the app. Previously some notifications — summaries especially — could arrive on Android without enough information to route the tap, and would quietly do nothing. Now they always know where they're meant to take you.

### An honest note on the account-switch fix

Because your device's push identity isn't a secret, letting the signed-in account claim it is a deliberate trade-off. In practical terms it means the last account to sign in on a device is the one that gets that device's notifications, and the previous account stops receiving them there. This is how mainstream push systems behave and it's the right call for shared-device usage, but we'd rather name it plainly than pretend the token is locked to a single identity forever. Signing out still releases the token promptly when it can; the new behavior is simply the safety net for when it can't.

### Referrals that stick through signup

Profile-based referrals are now tracked reliably from the moment someone lands on your profile through to when they create their account, independent of whatever reward settings happen to be active at the time. Direct invite codes still take precedence, so nothing about invites changes — this just makes sure the credit for a share you earned doesn't get dropped along the way.

### No more stale maintenance screens on mobile

When a node is briefly down for maintenance, mobile browsers could hold on to that maintenance page even after the site came back, leaving you staring at a "be right back" screen on a site that was already up. We changed how those maintenance responses are served so they're never cached, kept the app shell refreshing in the background, and made the site wait until the backend is genuinely ready before reopening. The upshot: when we're back, you're back, without needing to force-refresh.

### Under the hood

This is a backend, frontend, and infrastructure release with no changes to the chain itself, so validators upgrade with a normal restart and no coordinated on-chain step. Each change ships with tests, including a rewritten push-token check that verifies account ownership transfers correctly while still preventing one account from releasing another's token.
