import { defaultUrlTransform } from 'react-markdown';

/**
 * URL transform for post/comment markdown.
 *
 * `defaultUrlTransform` decides "is this a protocol I allow?" by looking for a
 * colon, so anything without one is treated as relative and passes through. A
 * protocol-relative URL has no colon, which means `[click](//evil.example)`
 * survives and the browser resolves it as an off-site https navigation that
 * renders as an ordinary in-app link. That is a phishing primitive rather than
 * script execution, but there is no legitimate use for it in a post body: real
 * external links are written with a scheme, and internal ones start with `/`.
 */
export function markdownUrlTransform(value) {
    const raw = String(value || '');
    // Backslashes are normalised to forward slashes by URL parsers, so `\\host`
    // and `/\host` are the same authority-relative form as `//host`.
    const slashes = raw.replace(/\\/g, '/');
    if (/^\s*\/\//.test(slashes)) return '';
    return defaultUrlTransform(raw);
}
