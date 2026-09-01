"""Blocked-community glob matching, ported from the chain.

The backend used to reimplement the chain's community glob as a regular expression,
converting each ``*`` into ``.*`` and calling ``re.fullmatch``. That construction
backtracks exponentially, roughly doubling per added pattern character: the maximum
chain-legal pattern costs about 47 seconds of CPU **per row**, against a gunicorn
worker timeout of 120 seconds. The regression test uses a cheaper 17-segment pattern
that still costs 22 seconds, because the cost depends on the community as much as the
pattern — a full-length community whose last character cannot match forces the engine to
exhaust every split, while against a shorter one it rejects on a literal count and
returns instantly.

The chain's own matcher never had that behaviour — it is a linear greedy walk — so
this was a backend defect rather than a protocol one, and the fix is to stop
reimplementing and start porting.

``community_matches_pattern`` below is a port of the linear greedy walk the chain
used while it still evaluated block patterns itself. Since v1.39 the chain only
stores the pattern and every match happens off-chain, so this function and the
indexer's copy are jointly authoritative for what a viewer sees; a divergence
between them shows up as a block that works on one surface and not another.
Greedy leftmost segment matching is correct
for ``*``-only globs — taking the earliest match for a segment never prevents a
later one — which is why the linear form needs no backtracking to stay exact.
"""

from __future__ import annotations

# Maximum wildcards allowed in a newly submitted pattern. The linear matcher
# below is not the reason this exists — it handles any number of wildcards in
# linear time. It bounds two things that are not linear: PostgreSQL's LIKE, which
# backtracks like the regex did, and the size of the input space generally.
#
# Patterns already on chain may exceed it: the chain accepts up to 34 wildcards
# and is not changed by this release. Such patterns still match correctly here;
# they are only excluded from the SQL pre-filter. See _blocked_communities_sql.
MAX_COMMUNITY_WILDCARDS = 4


def count_wildcards(pattern: str) -> int:
    return (pattern or "").count("*")


def community_matches_pattern(community: str, pattern: str) -> bool:
    """Return True if ``community`` matches ``pattern``, where ``*`` matches any run.

    Linear in the length of the community, with no backtracking and no regular
    expression.
    """
    if "*" not in pattern:
        return community == pattern

    parts = pattern.split("*")
    pos = 0
    for i, part in enumerate(parts):
        if not part:
            continue
        idx = community.find(part, pos)
        if idx < 0:
            return False
        # An unanchored pattern may match anywhere; an anchored one may not.
        if i == 0 and idx != 0:
            return False
        pos = idx + len(part)

    # A pattern not ending in * must match through the end of the community.
    if parts and parts[-1]:
        return community.endswith(parts[-1])
    return True
