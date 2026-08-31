import { beforeEach, describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { getMaxInputLength } from '../../src/utils/chainParams.js';

const srcRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../src');

function walkJsFiles(dir, out = []) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walkJsFiles(full, out);
        else if (entry.isFile() && /\.(js|jsx)$/.test(entry.name)) out.push(full);
    }
    return out;
}

describe('usernames carry no Anon- prefix', () => {
    beforeEach(() => {
        localStorage.clear();
    });

    it('offers the whole chain limit to every tier', () => {
        localStorage.setItem('chainConfig', JSON.stringify({ max_username_size: 30 }));
        // Free accounts used to lose 5 characters to the prefix.
        expect(getMaxInputLength()).toBe(30);
    });

    it('reports null when chain params are not cached, so callers can fall back', () => {
        expect(getMaxInputLength()).toBeNull();
    });

    it('never writes the prefix back into a username', () => {
        const offenders = [];
        for (const file of walkJsFiles(srcRoot)) {
            const text = fs.readFileSync(file, 'utf8');
            const re = /Anon-/g;
            let m;
            while ((m = re.exec(text))) {
                offenders.push(`${path.relative(srcRoot, file)}:${text.slice(0, m.index).split('\n').length}`);
            }
        }
        expect(offenders).toEqual([]);
    });

    it('seeds the change-username field with the stored name in full', () => {
        // Trimming a legacy "Anon-alice" down to "alice" here would rename the
        // account the moment an unrelated submit went through.
        const hook = fs.readFileSync(path.join(srcRoot, 'logic/useChangeUsername.js'), 'utf8');
        expect(hook).toContain('useState(() => currentUsername)');
        expect(hook).not.toMatch(/slice\(5\)/);
    });
});
