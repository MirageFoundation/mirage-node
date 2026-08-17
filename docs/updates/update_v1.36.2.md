# Mirage v1.36.2 Release Notes

### Photos and videos post from the app again

For about twelve hours on 17 August, every photo and video posted from the Mirage
app failed. Not slowly, not sometimes — every single one, on every phone, while the
same uploads from the website worked perfectly. If you tried to share a picture
during that window and the app just spun and gave up, that was us, and we are sorry.
Uploads are working again, and this release is the fix plus the changes that stop the
same class of mistake from getting this far next time.

### What went wrong

The previous release tightened how uploads are size-checked. A photo is allowed 15
megabytes and a video a great deal more, and to enforce that properly the server has
to know which one is arriving *before* it starts accepting the file rather than after.
Making that possible meant moving one small piece of information — whether this is a
photo or a video — to a part of the request the server can read immediately. The
website was updated to send it the new way. The app, which is a separate program
already installed on your phone and not something we can change from our side, was
still sending it the old way. The server no longer recognised it, and turned every
app upload away.

### Why nobody noticed for half a day

The uncomfortable part is not the mistake, it is how long it stayed invisible. Because
the rejection happened before the file was accepted, the connection closed early and
the app reported it as a network problem rather than as a refusal with a reason. On
our side, that particular refusal was the one path in the upload code that wrote
nothing to the log. So the app blamed the network, the server said nothing at all, and
the only visible symptom was uploads quietly not working. Both halves of that are now
fixed: every refusal is logged with its reason, and the compatibility path records
each time it is used so we can tell exactly when it is safe to remove.

### Both ways of asking now work

The server accepts the new form of the request and the old one, so the app on your
phone right now works without an update, and the app update we are preparing will use
the newer form. The size limits are unchanged and still enforced in both cases — an
oversized photo is still refused, and refused cleanly, whichever way the request
arrives. The security work from the previous release stands; it just no longer assumes
that every piece of software talking to us was updated on the same day we were.

### The test that should have caught it

The previous release changed what the app is required to send and every test we had
was updated to send the new form, so the whole suite passed while the actual shipped
app was being rejected. That is the failure worth naming: a test suite that only ever
speaks the newest dialect cannot tell you that you broke the dialect your users are
still speaking. The upload tests now include the exact request the shipped app makes
and require it to succeed, and we verified the new test genuinely catches the problem
by putting the broken version back and watching it fail. The security note for the
original change has been amended in public with what it cost, rather than quietly
marked as fixed.

### Nothing changed on the chain

As with the previous release, this touches no chain code, adds no rules and needs no
coordinated upgrade. It is a fix to the software that sits in front of the chain, so
there is no halt, no downtime and no version of the network to agree on.
