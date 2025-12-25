import Storage from './Storage';

export const DEFAULT_COLLAPSE_THRESHOLD = -4;

export const getCollapseThreshold = () => {
    try {
        const raw = Storage.load('comment_auto_collapse_threshold', DEFAULT_COLLAPSE_THRESHOLD);
        const n = Number(raw);
        return Number.isFinite(n) ? n : DEFAULT_COLLAPSE_THRESHOLD;
    } catch (_) {
        return DEFAULT_COLLAPSE_THRESHOLD;
    }
};

export const shouldAutoCollapse = (comment, threshold = DEFAULT_COLLAPSE_THRESHOLD) => {
    if (!comment) return false;
    const level = Number(comment.level) || 0;
    if (level <= 0) return false;
    const v = Number(comment.points);
    if (!Number.isFinite(v)) return false;
    return v <= threshold;
};


