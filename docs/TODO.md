1. Language Consistency: Go Everywhere
Current: Go (chain, orchestrator) + Python (indexer, backend) + JavaScript (frontend)
The problem: The canonical serialization must be byte-identical across Go, Python, and JavaScript. This is a maintenance nightmare and a source of subtle bugs. Three separate implementations of uvarint, encStr, encBytes, field ordering...
What I'd do instead:
Write indexer in Go (consume protobuf natively, no datatypes.py mirroring)
Write backend in Go (single binary, shared types with chain)
Keep JS on frontend (unavoidable)
This reduces the cross-language surface area from 3 languages to 2.



2. Use Protobuf Code Generation, Not Dynamic Message Building
Current: datatypes.py manually builds protobuf descriptors at runtime:
msg = file_proto.message_type.add()msg.name = "MsgPost"add_f(msg, "authority", 1, TYPE_STRING)add_f(msg, "envelope_pubkey", 2, TYPE_BYTES)# ... 50+ fields across 20+ message types
The problem: Every time you add a field in Go, you must manually mirror it in Python. Field numbers are duplicated. There's no compile-time verification.
What I'd do instead: Use buf generate with Python output. The .proto files are the single source of truth; generated code ensures consistency. Yes, this adds a build step, but it eliminates an entire class of bugs.



3. Rethink the "Chain Accepts, Indexer Enforces" Pattern
Current: MsgDelete is accepted from anyone on-chain; the indexer checks ownership.
// SECURITY MODEL (enforced by indexer, NOT here):// The blockchain accepts Delete messages from anyone - they just pay gas.
The problem: This is conceptually confusing and creates a weird trust model. Users might think their delete "worked" when the chain accepted it, but it's actually a no-op because the indexer ignores it.
What I'd do instead: Either:
Store post ownership on-chain (it's just a mapping, not that expensive)
Return an error from the chain if ownership doesn't match
OR make this explicitly a "soft delete request" that gets queued for indexer processing
The current hybrid approach saves some gas but creates unclear semantics.





6. Event Sourcing for the Indexer
Current: The indexer processes blocks and directly mutates PostgreSQL.
What I'd do instead: Store raw block events first (event sourcing), then derive views. Benefits:
Can rebuild any view without re-syncing from chain
Easier debugging (replay specific events)
Cleaner separation between "what happened" and "current state"




-------



**TODO - Future Release**: Remove legacy routes for:
- `/view_post` (replaced by `/p/`)
- `/profile?address=` (replaced by `/u/`)
- Legacy query params in ViewPostView: `?post_id=`, `?root=`
- Legacy query params in ProfileView: `?address=`
Search for "DEPRECATED" comments in code to find all removal points.

TODO - REMOVE AFTER MARCH:
- the legacy handling of embedding the image/media of a post if the first line is a link. now we have the media field so we don't need that anymore

----------


generally optimize website. Find any bottlenecks. Use firefox profiler.

----------

we need to add the relaying node into the blockchain history. this way we can prevent botting in the future. like a rogue node - e.g. if a node is known to facilite spammers, then a separate script can create a moderator that excludes these posts.

----------

add blocking keywords (in topics or posts)
~~add blocking topics~~ — Done in v1.13.0

----------

full security audit for every module

----------

add all the quotes! from obsidian

