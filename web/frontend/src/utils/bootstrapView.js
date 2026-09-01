export function deriveBootstrapView(pathname) {
    if (!pathname || typeof pathname !== 'string') return null;
    const path = pathname.split('?')[0];
    if (path === '/home' || path === '/') return 'feed:home';
    if (path === '/following') return 'feed:following';
    if (path.startsWith('/c/')) {
        const community = decodeURIComponent(path.slice(3).split('/')[0] || '').trim();
        return community ? `community:${community}` : null;
    }
    if (path.startsWith('/p/')) {
        const id = path.slice(3).split('/')[0].split('?')[0].trim().toLowerCase();
        return id ? `thread:${id}` : null;
    }
    if (path === '/inbox') return 'inbox';
    return null;
}
