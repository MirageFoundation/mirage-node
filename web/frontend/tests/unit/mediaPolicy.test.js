import { describe, it, expect } from 'vitest';
import { classifyMediaUrl, shouldAutoLoadMedia } from '../../src/utils/mediaPolicy.js';

describe('mediaPolicy', () => {
    it('auto-loads allowlisted hosts and same-origin', () => {
        expect(classifyMediaUrl('https://www.youtube.com/watch?v=dQw4w9WgXcQ').autoLoad).toBe(true);
        expect(classifyMediaUrl('https://i.ytimg.com/vi/x/hqdefault.jpg').provider).toBe('youtube');
        expect(classifyMediaUrl('https://api.dicebear.com/9.x/identicon/svg?seed=a').provider).toBe('dicebear');
        expect(classifyMediaUrl('https://mirage-img.b-cdn.net/stickers/a.png').provider).toBe('mirage-cdn');
        expect(shouldAutoLoadMedia('https://www.redgifs.com/watch/abc')).toBe(true);
        expect(classifyMediaUrl('https://rumble.com/v70bqqu-some-title.html').provider).toBe('rumble');
        expect(shouldAutoLoadMedia('https://www.rumble.com/embed/v70bqqu/')).toBe(true);
    });

    it('requires click for unknown hosts and denies proxy hosts', () => {
        const unk = classifyMediaUrl('https://evil.example/private.jpg');
        expect(unk.autoLoad).toBe(false);
        expect(unk.provider).toBe('unknown');
        expect(classifyMediaUrl('https://wsrv.nl/?url=https://evil.example/x').autoLoad).toBe(false);
        expect(classifyMediaUrl('https://i0.wp.com/evil.example/x').reason).toBe('denied-proxy');
    });

    it('rejects credentials, bad schemes, and control characters', () => {
        expect(classifyMediaUrl('javascript:alert(1)').ok).toBe(false);
        expect(classifyMediaUrl('https://user:pass@example.com/x').ok).toBe(false);
        expect(classifyMediaUrl('https://example.com/x\u0000').ok).toBe(false);
    });
});
