/**
 * Visible community sign and path.
 *
 * Every valid slug is a community. The sign is `[slug]` so it can sit in
 * a sentence and auto-link. The route stays `/c/:slug`.
 * Do not render `#slug`.
 */

export function communitySlug(value) {
    return String(value || '').trim();
}

export function communityLabel(value) {
    const slug = communitySlug(value);
    return slug ? `[${slug}]` : '';
}

export function communityPath(value) {
    const slug = communitySlug(value);
    if (!slug) return '/communities';
    return `/c/${encodeURIComponent(slug.toLowerCase())}`;
}

/** Strip a typed `[slug]`, leftover `c/`, or leftover `#` so search matches the slug. */
export function stripCommunityPrefix(value) {
    return String(value || '')
        .trim()
        .replace(/^(c\/|#)+/i, '')
        .replace(/^\[/, '')
        .replace(/\]$/, '');
}

/** Lowercase slug: letters, digits, single internal hyphens. Matches chain ValidateCommunitySlug. */
export function sanitizeCommunitySlug(value, maxLen = 50) {
    return stripCommunityPrefix(value)
        .toLowerCase()
        .replace(/[^a-z0-9-]/g, '')
        .replace(/--+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, maxLen);
}

export function isValidCommunitySlug(value, minLen = 2, maxLen = 50) {
    const slug = String(value || '');
    if (slug.length < minLen || slug.length > maxLen) return false;
    if (slug !== slug.trim()) return false;
    if (!/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(slug)) return false;
    if (slug.includes('--')) return false;
    return true;
}

const RESERVED_COMMUNITY_SLUGS = new Set(['all', 'home', 'following']);

/**
 * `[slug]` in running text (and leftover `c/slug`). Skips markdown `[text](url)`
 * and `[text][ref]`. Used by post markdown and plain community descriptions.
 */
const COMMUNITY_MENTION_RE = /(?<![![])\[([a-z0-9]+(?:-[a-z0-9]+)*)\](?![(:\]])|(?<![a-zA-Z0-9/])c\/([a-z0-9]+(?:-[a-z0-9]+)*)(?![a-zA-Z0-9-])/g;

export function splitCommunityMentions(text) {
    const value = String(text ?? '');
    const regex = new RegExp(COMMUNITY_MENTION_RE.source, COMMUNITY_MENTION_RE.flags);
    const parts = [];
    let lastIndex = 0;
    let match;
    while ((match = regex.exec(value)) !== null) {
        if (match.index > lastIndex) {
            parts.push({ type: 'text', value: value.slice(lastIndex, match.index) });
        }
        const slug = String(match[1] || match[2] || '').toLowerCase();
        if (!slug || RESERVED_COMMUNITY_SLUGS.has(slug)) {
            const literal = match[0];
            const prev = parts[parts.length - 1];
            if (prev && prev.type === 'text') prev.value += literal;
            else parts.push({ type: 'text', value: literal });
        } else {
            parts.push({ type: 'community', slug });
        }
        lastIndex = match.index + match[0].length;
    }
    if (lastIndex === 0) return [{ type: 'text', value }];
    if (lastIndex < value.length) {
        const rest = value.slice(lastIndex);
        const prev = parts[parts.length - 1];
        if (prev && prev.type === 'text') prev.value += rest;
        else parts.push({ type: 'text', value: rest });
    }
    return parts;
}

export function communityFromPathname(pathname) {
    try {
        const match = String(pathname || '').match(/^\/c\/([^/]+)/);
        if (!match?.[1]) return '';
        const slug = decodeURIComponent(match[1]).trim().toLowerCase();
        if (!slug || RESERVED_COMMUNITY_SLUGS.has(slug)) return '';
        return slug;
    } catch (_) {
        return '';
    }
}

export function createPostPathForContext(hasPublicKey, community) {
    const slug = String(community || '').trim();
    if (!hasPublicKey || !slug || RESERVED_COMMUNITY_SLUGS.has(slug.toLowerCase())) {
        return '/create_post';
    }
    return `/create_post?community=${encodeURIComponent(slug)}`;
}

/** Curator slugs first (including ones not joined), then other joined slugs. No duplicates. */
export function splitJoinedCommunitiesForComposer(joined, curated) {
    const curatedOut = [];
    const curatedSet = new Set();
    for (const raw of curated || []) {
        const slug = String(raw || '').trim().toLowerCase();
        if (!slug || RESERVED_COMMUNITY_SLUGS.has(slug) || curatedSet.has(slug)) continue;
        curatedSet.add(slug);
        curatedOut.push(slug);
    }
    const joinedOut = [];
    const joinedSeen = new Set();
    for (const raw of joined || []) {
        const slug = String(raw || '').trim().toLowerCase();
        if (!slug || RESERVED_COMMUNITY_SLUGS.has(slug) || joinedSeen.has(slug) || curatedSet.has(slug)) continue;
        joinedSeen.add(slug);
        joinedOut.push(slug);
    }
    return { curated: curatedOut, joined: joinedOut };
}
