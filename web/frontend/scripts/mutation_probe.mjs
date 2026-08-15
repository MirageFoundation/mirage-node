#!/usr/bin/env node
/**
 * Mutation probe for the 2026-08-14 frontend security review.
 *
 * Each entry breaks one of the fixes in the source tree, runs the unit suite, and
 * requires that the named test fails. A mutation that survives means the test
 * would not notice if the fix were reverted, which is the failure mode this
 * guards against. Sources are restored afterwards, including on abort.
 *
 * Usage: node scripts/mutation_probe.mjs
 */
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

const MUTATIONS = [
    {
        name: 'H-1 seed fallback: protected mode never falls back to memory',
        file: 'src/utils/SeedVault.js',
        from: "const mode = this.canStoreWithoutSecret() ? requested : 'memory';",
        to: 'const mode = requested;',
        expect: 'stores the seed after a fallback login',
    },
    {
        name: 'M-7 reveal step-up: freshness check always passes',
        file: 'src/utils/SeedVault.js',
        from: 'return (Date.now() - this._lastUnlockedAt) <= maxAgeMs;',
        to: 'return true;',
        expect: 'treats an unlock as stale',
    },
    {
        name: 'M-2 session reset: API response cache is left populated',
        file: 'src/utils/api.js',
        from: 'responseCache.clear();',
        to: 'void 0;',
        expect: 'drops cached GET responses',
    },
    {
        name: 'L-2 attribution: nonce dropped from the signed payload',
        file: 'src/utils/canonicalEncoding.js',
        from: 'String(nonce || 0),',
        to: "'0',",
        expect: 'binds the nonce',
    },
    {
        name: 'Sub-threshold: protocol-relative markdown links allowed through',
        file: 'src/utils/markdownUrl.js',
        from: "if (/^\\s*\\/\\//.test(slashes)) return '';",
        to: 'void slashes;',
        expect: 'drops authority-relative URLs',
    },
];

function runSuite() {
    try {
        const out = execFileSync('npx', ['vitest', 'run', '--reporter', 'verbose'], {
            cwd: root,
            encoding: 'utf8',
            stdio: ['ignore', 'pipe', 'pipe'],
        });
        return { failed: false, out };
    } catch (err) {
        return { failed: true, out: `${err.stdout || ''}${err.stderr || ''}` };
    }
}

const originals = new Map();
function restoreAll() {
    for (const [path, text] of originals) writeFileSync(path, text);
}
process.on('SIGINT', () => {
    restoreAll();
    process.exit(130);
});

let survived = 0;
try {
    for (const m of MUTATIONS) {
        const path = resolve(root, m.file);
        const original = readFileSync(path, 'utf8');
        originals.set(path, original);

        const count = original.split(m.from).length - 1;
        if (count !== 1) {
            console.error(`SURVIVED  ${m.name}\n          anchor matched ${count} times in ${m.file}; probe is stale`);
            survived += 1;
            continue;
        }

        writeFileSync(path, original.replace(m.from, m.to));
        const { failed, out } = runSuite();
        writeFileSync(path, original);
        originals.delete(path);

        // The suite must fail, and it must fail on the test that covers this fix
        // rather than incidentally somewhere else.
        const blamed = out.includes(m.expect);
        if (failed && blamed) {
            console.log(`KILLED    ${m.name}`);
        } else {
            survived += 1;
            console.error(
                `SURVIVED  ${m.name}\n` +
                    `          suite ${failed ? 'failed but not on' : 'passed despite the mutation; nothing covers'} ` +
                    `"${m.expect}"`,
            );
        }
    }
} finally {
    restoreAll();
}

if (survived) {
    console.error(`\n${survived} of ${MUTATIONS.length} mutations survived`);
    process.exit(1);
}
console.log(`\nall ${MUTATIONS.length} mutations killed`);
