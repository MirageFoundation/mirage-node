import { describe, it, expect } from 'vitest';
import { buildThumbProxy, buildThumbProxyFallback, buildPhotonUrl, buildWsrvUrl } from '../../src/utils/media.js';

describe('thumbnail proxy', () => {
    it('routes plain URLs through Photon', () => {
        const t = buildThumbProxy('https://example.com/a.jpg');
        expect(t.proxy).toBe('photon');
        expect(t.src).toBe('https://i0.wp.com/example.com/a.jpg?w=240&h=240&crop=1');
        expect(t.original).toBe('https://example.com/a.jpg');
    });

    it('routes query-string URLs through wsrv because Photon drops the query', () => {
        const t = buildThumbProxy('https://example.com/a.jpg?sig=abc');
        expect(t.proxy).toBe('wsrv');
        expect(t.src).toContain('https://wsrv.nl/?url=');
        expect(t.blurSrc).toContain('blur=18');
    });

    it('serves YouTube posters direct', () => {
        const t = buildThumbProxy('https://i.ytimg.com/vi/abc/hqdefault.jpg');
        expect(t.proxy).toBe('direct');
        expect(t.src).toBe('https://i.ytimg.com/vi/abc/hqdefault.jpg');
    });

    it('returns an empty state for missing URLs', () => {
        expect(buildThumbProxy(null).proxy).toBe('none');
        expect(buildThumbProxy('   ').src).toBeNull();
    });

    it('falls back from Photon to wsrv', () => {
        const f = buildThumbProxyFallback('https://example.com/a.jpg');
        expect(f.proxy).toBe('wsrv');
        expect(f.src).toBe(buildWsrvUrl('https://example.com/a.jpg', { w: 240, h: 240 }));
    });

    it('never leaks the raw URL when a proxy is used', () => {
        expect(buildPhotonUrl('https://example.com/a.jpg', { w: 10, h: 10 })).not.toContain('https://example.com/a.jpg');
    });
});
