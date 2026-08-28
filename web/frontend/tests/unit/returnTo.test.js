import { describe, expect, it } from 'vitest';
import {
    readReturnTo,
    returnToFromLocation,
    safeReturnTo,
    withReturnTo,
} from '../../src/utils/returnTo.js';

describe('safeReturnTo', () => {
    it('accepts root-relative paths with query strings', () => {
        expect(safeReturnTo('/c/test/teams')).toBe('/c/test/teams');
        expect(safeReturnTo('/c/test/teams?tab=1')).toBe('/c/test/teams?tab=1');
    });

    it('rejects open redirects and auth loops', () => {
        expect(safeReturnTo('https://evil.example/phish')).toBeNull();
        expect(safeReturnTo('//evil.example')).toBeNull();
        expect(safeReturnTo('\\evil')).toBeNull();
        expect(safeReturnTo('c/test')).toBeNull();
        expect(safeReturnTo('/login')).toBeNull();
        expect(safeReturnTo('/signup?x=1')).toBeNull();
    });
});

describe('return helpers', () => {
    it('reads next from the query string', () => {
        expect(readReturnTo('?next=%2Fc%2Ftest%2Fteams')).toBe('/c/test/teams');
        expect(readReturnTo('?next=https%3A%2F%2Fevil.example')).toBeNull();
    });

    it('strips an existing next when capturing the current location', () => {
        expect(returnToFromLocation({
            pathname: '/c/test/teams',
            search: '?next=/elsewhere',
        })).toBe('/c/test/teams');
    });

    it('appends next without clobbering other query params on the target', () => {
        expect(withReturnTo('/subscription', '/c/test/teams'))
            .toBe('/subscription?next=%2Fc%2Ftest%2Fteams');
        expect(withReturnTo('/login?foo=1', '/c/test/teams'))
            .toBe('/login?foo=1&next=%2Fc%2Ftest%2Fteams');
        expect(withReturnTo('/login', 'https://evil.example')).toBe('/login');
    });
});
