import { describe, it, expect } from 'vitest';
import { classifyMediaUrl } from '../../src/utils/mediaPolicy.js';

describe('mediaPolicy', () => {
    it('labels allowlisted hosts and same-origin', () => {
        expect(classifyMediaUrl('https://www.youtube.com/watch?v=dQw4w9WgXcQ').autoLoad).toBe(true);
        expect(classifyMediaUrl('https://i.ytimg.com/vi/x/hqdefault.jpg').provider).toBe('youtube');
        expect(classifyMediaUrl('https://api.dicebear.com/9.x/identicon/svg?seed=a').provider).toBe('dicebear');
        expect(classifyMediaUrl('https://mirage-img.b-cdn.net/stickers/a.png').provider).toBe('mirage-cdn');
        expect(classifyMediaUrl('https://www.redgifs.com/watch/abc').autoLoad).toBe(true);
        expect(classifyMediaUrl('https://rumble.com/v70bqqu-some-title.html').provider).toBe('rumble');
        expect(classifyMediaUrl('https://www.rumble.com/embed/v70bqqu/').autoLoad).toBe(true);
    });

    it('labels the thumbnail proxies as trusted', () => {
        expect(classifyMediaUrl('https://wsrv.nl/?url=https://example.com/x.jpg').provider).toBe('image-proxy');
        expect(classifyMediaUrl('https://i0.wp.com/example.com/x.jpg').provider).toBe('image-proxy');
    });

    it('marks unknown hosts as not allowlisted but still renderable', () => {
        const unk = classifyMediaUrl('https://evil.example/private.jpg');
        expect(unk.ok).toBe(true);
        expect(unk.autoLoad).toBe(false);
        expect(unk.provider).toBe('unknown');
    });

    it('rejects credentials, bad schemes, and control characters', () => {
        expect(classifyMediaUrl('javascript:alert(1)').ok).toBe(false);
        expect(classifyMediaUrl('https://user:pass@example.com/x').ok).toBe(false);
        expect(classifyMediaUrl('https://example.com/x\u0000').ok).toBe(false);
    });
});
