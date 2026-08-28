import { beforeEach, describe, expect, it, vi } from 'vitest';
import Api from '../../src/utils/api.js';
import {
    formatUserLabel,
    isMirageAddress,
    resolveUserIdentity,
} from '../../src/utils/UsernameCache.js';

describe('user identity helpers', () => {
    beforeEach(() => {
        vi.restoreAllMocks();
    });

    it('accepts valid mirage1 addresses and rejects junk', () => {
        expect(isMirageAddress('mirage1y2mhj3axv3ujny2hqd8retq25xst2wmj7lw54r')).toBe(true);
        expect(isMirageAddress('not-an-address')).toBe(false);
        expect(isMirageAddress('cosmos1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqnrql8a')).toBe(false);
    });

    it('prefers @username in labels and shortens bare addresses', () => {
        expect(formatUserLabel('Alice', 'mirage1y2mhj3axv3ujny2hqd8retq25xst2wmj7lw54r')).toBe('@Alice');
        expect(formatUserLabel('', 'mirage1y2mhj3axv3ujny2hqd8retq25xst2wmj7lw54r'))
            .toBe('mirage1y2mhj3a…mj7lw54r');
    });

    it('resolves usernames through get_address_from_username and keeps addresses as-is', async () => {
        const get = vi.spyOn(Api, 'get').mockResolvedValue({
            exists: true,
            address: 'mirage1y2mhj3axv3ujny2hqd8retq25xst2wmj7lw54r',
            username: 'Alice',
        });

        const fromName = await resolveUserIdentity('@Alice');
        expect(fromName).toEqual({
            address: 'mirage1y2mhj3axv3ujny2hqd8retq25xst2wmj7lw54r',
            username: 'Alice',
            kind: 'username',
        });
        expect(get).toHaveBeenCalledWith(
            'get_address_from_username',
            { username: 'Alice' },
            { timeoutMs: 8000 },
        );

        const fromAddr = await resolveUserIdentity('mirage1y2mhj3axv3ujny2hqd8retq25xst2wmj7lw54r');
        expect(fromAddr.kind).toBe('address');
        expect(fromAddr.address).toBe('mirage1y2mhj3axv3ujny2hqd8retq25xst2wmj7lw54r');
    });

    it('fails hard when a username does not exist', async () => {
        vi.spyOn(Api, 'get').mockResolvedValue({ exists: false, address: null, username: 'nobody' });
        await expect(resolveUserIdentity('nobody')).rejects.toThrow(/not found/);
    });
});
