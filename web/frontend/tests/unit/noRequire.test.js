import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const srcRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../src');

function walkJsFiles(dir, out = []) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walkJsFiles(full, out);
        else if (entry.isFile() && /\.(js|jsx)$/.test(entry.name)) out.push(full);
    }
    return out;
}

describe('no CommonJS require in browser src', () => {
    it('src tree does not call require()', () => {
        const offenders = [];
        for (const file of walkJsFiles(srcRoot)) {
            const text = fs.readFileSync(file, 'utf8');
            // Match runtime require(...); ignore comments that mention "require".
            const re = /(?:^|[^.\w])require\s*\(/gm;
            let m;
            while ((m = re.exec(text))) {
                const line = text.slice(0, m.index).split('\n').length;
                offenders.push(`${path.relative(srcRoot, file)}:${line}`);
            }
        }
        expect(offenders).toEqual([]);
    });
});
