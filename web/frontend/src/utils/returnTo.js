/**
 * Same-origin return paths for /login and /subscription.
 * Query param name is `next`. Reject anything that is not a root-relative
 * path so this cannot become an open redirect.
 */

export const RETURN_QUERY = 'next';

const BLOCKED_RETURN_PREFIXES = [
    '/login',
    '/signup',
    '/sign_out',
    '/welcome',
];

export function safeReturnTo(value) {
    const raw = String(value || '').trim();
    if (!raw) return null;
    if (!raw.startsWith('/')) return null;
    if (raw.startsWith('//')) return null;
    if (raw.includes('\\') || raw.includes('://')) return null;
    let url;
    try {
        url = new URL(raw, 'http://local.invalid');
    } catch {
        return null;
    }
    if (url.origin !== 'http://local.invalid') return null;
    const path = `${url.pathname}${url.search}`;
    if (!path.startsWith('/') || path.startsWith('//')) return null;
    if (BLOCKED_RETURN_PREFIXES.some((prefix) => (
        url.pathname === prefix || url.pathname.startsWith(`${prefix}/`)
    ))) {
        return null;
    }
    return path;
}

export function readReturnTo(search) {
    const params = new URLSearchParams(
        typeof search === 'string' ? search : String(search || ''),
    );
    return safeReturnTo(params.get(RETURN_QUERY));
}

export function returnToFromLocation(location) {
    const pathname = String(location?.pathname || '');
    if (!pathname) return null;
    const params = new URLSearchParams(location?.search || '');
    params.delete(RETURN_QUERY);
    const query = params.toString();
    return safeReturnTo(`${pathname}${query ? `?${query}` : ''}`);
}

export function withReturnTo(href, returnPath) {
    const target = String(href || '').trim() || '/';
    const safe = safeReturnTo(returnPath);
    if (!safe) return target;
    let url;
    try {
        url = new URL(target, 'http://local.invalid');
    } catch {
        return target;
    }
    if (url.origin !== 'http://local.invalid') return target;
    url.searchParams.set(RETURN_QUERY, safe);
    return `${url.pathname}${url.search}`;
}
