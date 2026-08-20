import { describe, it, expect, beforeEach } from 'vitest';

import { getAllowedTags, getAllowedTagsParam } from '../../src/utils/ContentTags.js';
import Storage from '../../src/utils/Storage.js';

const OWNER = 'mirage1abcdefghijklmnopqrstuvwxyz0123456789';

describe('allowed content tags', () => {
    beforeEach(() => {
        localStorage.clear();
    });

    it('asks for nothing when signed out', () => {
        expect(getAllowedTags()).toEqual([]);
        expect(getAllowedTagsParam()).toBe('');
    });

    it('asks for nothing for an explicit guest', () => {
        Storage.save('publicKey', 'guest');
        expect(getAllowedTags()).toEqual([]);
    });

    it('still asks for nothing when the tag toggles are on but nobody is signed in', () => {
        Storage.save('show_tag_sensitive', true);
        Storage.save('show_tag_adult', true);
        expect(getAllowedTags()).toEqual([]);
    });

    it('defaults a signed-in viewer to sensitive only', () => {
        Storage.save('publicKey', OWNER);
        expect(getAllowedTags()).toEqual(['sensitive']);
    });

    it('honours a signed-in viewer turning sensitive off', () => {
        Storage.save('publicKey', OWNER);
        Storage.save('show_tag_sensitive', false);
        expect(getAllowedTags()).toEqual([]);
    });

    it('honours a signed-in viewer opting into the other tags', () => {
        Storage.save('publicKey', OWNER);
        Storage.save('show_tag_adult', true);
        Storage.save('show_tag_gore', true);
        expect(getAllowedTagsParam()).toBe('sensitive,adult,gore');
    });
});
