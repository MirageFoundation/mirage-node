export const sortComments = (comments, viewerAddress = null) => {
    const arr = Array.isArray(comments) ? comments.slice() : [];
    const viewer = (viewerAddress || '').toLowerCase();
    const now = Math.floor(Date.now() / 1000);

    const cmp = (a, b) => {
        // Optimistic comments always first
        if (a?._optimistic && !b?._optimistic) return -1;
        if (b?._optimistic && !a?._optimistic) return 1;

        // User's own very recent comments (< 60s) go first
        const aIsViewerRecent = viewer && (a?.user_id || '').toLowerCase() === viewer && (now - (a?.timestamp || 0)) < 60;
        const bIsViewerRecent = viewer && (b?.user_id || '').toLowerCase() === viewer && (now - (b?.timestamp || 0)) < 60;
        if (aIsViewerRecent && !bIsViewerRecent) return -1;
        if (bIsViewerRecent && !aIsViewerRecent) return 1;

        const av = Number(a?.points) || 0;
        const bv = Number(b?.points) || 0;
        if (av !== bv) return bv - av; // higher points first

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


