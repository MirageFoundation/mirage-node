import { describe, it, expect } from 'vitest';
import { extractRumbleId, buildRumbleEmbedUrl } from '../../src/utils/media.js';

describe('rumble embeds', () => {
    it('extracts ids from watch and embed URLs', () => {
        expect(extractRumbleId('https://rumble.com/v70bqqu-some-title.html')).toBe('v70bqqu');
        expect(extractRumbleId('https://www.rumble.com/embed/v70bqqu/')).toBe('v70bqqu');
        expect(extractRumbleId('https://rumble.com/embed/u4nvf6q.v70bqqu/?pub=x')).toBe('u4nvf6q.v70bqqu');
        expect(extractRumbleId('https://example.com/v70bqqu-x.html')).toBeNull();
    });

    it('builds embed URLs with optional muted autoplay', () => {
        expect(buildRumbleEmbedUrl('v70bqqu')).toBe('https://rumble.com/embed/v70bqqu/');
        expect(buildRumbleEmbedUrl('v70bqqu', true)).toBe('https://rumble.com/embed/v70bqqu/?autoplay=2');
    });
});
