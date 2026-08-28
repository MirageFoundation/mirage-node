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
