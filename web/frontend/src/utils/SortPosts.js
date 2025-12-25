export const DEFAULT_ALGO_PARAMS = {
    voteWeight: 1.0,
    commentWeight: 1.1,
    maxBonus: 1.5,
    freshnessWindow: 1,
    halfLifeHours: 18,
    exponent: 2
};

export const calculateHotScore = (post, params = null) => {
    const algoParams = params || DEFAULT_ALGO_PARAMS;
    const now = Math.floor(Date.now() / 1000);
    const timestamp = post.timestamp || 0;
    const ageHours = Math.max(0, (now - timestamp) / 3600);

    const points = Math.max(0, Number(post.points) || 0);
    const comments = Math.max(0, Number(post.comments) || 0);

    const voteScore = Math.log(points * algoParams.voteWeight + 1);
    const commentScore = Math.log(comments * algoParams.commentWeight + 1);

    const newPostBonus =
        ageHours < algoParams.freshnessWindow
            ? algoParams.maxBonus * Math.pow(1 - ageHours / algoParams.freshnessWindow, algoParams.exponent)
            : 0;

    const engagementScore = voteScore + commentScore;
    const timeDecayFactor = Math.exp(-ageHours / algoParams.halfLifeHours);

    const hotScore = engagementScore * timeDecayFactor + newPostBonus;

    return hotScore;
};

// Returns a new array; does not mutate the input
export const sortPosts = (posts, sortBy) => {
    const arr = Array.isArray(posts) ? posts.slice() : [];
    const algoParams = DEFAULT_ALGO_PARAMS;

    const calculateHotScoreForPost = (post) => {
        return calculateHotScore(post, algoParams);
    };

    const cmp = (a, b) => {
        switch (sortBy) {
            case 'magic':
            case 'hot': {
                // Sort by hot score (combines engagement and recency)
                const scoreA = calculateHotScoreForPost(a);
                const scoreB = calculateHotScoreForPost(b);
                if (scoreA !== scoreB) return scoreB - scoreA;

                // Tie-break by timestamp (newer first)
                if (a.timestamp !== b.timestamp) return b.timestamp - a.timestamp;

                // Final tie-break by post_id for stability
                const aid = String(a.post_id || ''), bid = String(b.post_id || '');
                return aid.localeCompare(bid);
            }
            case 'newest':
            case 'time':
                return (b.timestamp || 0) - (a.timestamp || 0);
            case 'points':
                return (b.points || 0) - (a.points || 0);
            default:
                return 0;
        }
    };
    arr.sort(cmp);
    return arr;
};
