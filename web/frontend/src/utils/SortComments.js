const totalAwards = (node) => {
    const awards = node?.awards;
    if (!Array.isArray(awards) || awards.length === 0) return 0;
    let sum = 0;
    for (const a of awards) sum += Number(a?.count) || 0;
    return sum;
};

export const sortComments = (comments, viewerAddress = null) => {
    const arr = Array.isArray(comments) ? comments.slice() : [];
    const viewer = (viewerAddress || '').toLowerCase();

    const cmp = (a, b) => {
        // Optimistic comments always first
        if (a?._optimistic && !b?._optimistic) return -1;
        if (b?._optimistic && !a?._optimistic) return 1;

        // Own comments first
        const aOwn = viewer && (a?.user_id || '').toLowerCase() === viewer;
        const bOwn = viewer && (b?.user_id || '').toLowerCase() === viewer;
        if (aOwn && !bOwn) return -1;
        if (bOwn && !aOwn) return 1;

        // More awards first
        const aAwards = totalAwards(a);
        const bAwards = totalAwards(b);
        if (aAwards !== bAwards) return bAwards - aAwards;

        // Higher votes first
        const av = Number(a?.points) || 0;
        const bv = Number(b?.points) || 0;
        if (av !== bv) return bv - av;

        // Tie-break by timestamp, older first to preserve conversational flow
        const atime = Number(a?.timestamp) || 0;
        const btime = Number(b?.timestamp) || 0;
        if (atime !== btime) return atime - btime;

        // Final stable tie-break by post_id
        const aid = String(a?.post_id || '');
        const bid = String(b?.post_id || '');
        return aid.localeCompare(bid);
    };
    arr.sort(cmp);
    return arr;
};


