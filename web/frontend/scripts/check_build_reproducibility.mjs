#!/usr/bin/env node
/**
 * Compare two clean builds for byte-identical hashed JS/CSS assets.
 * Usage: node scripts/check_build_reproducibility.mjs
 * Expects build-a/ and build-b/ already produced, OR runs two builds itself
 * when --run is passed.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const shouldRun = process.argv.includes('--run');

function sha256File(p) {
    return crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
}

function collectHashes(dir) {
    const out = {};
    function walk(d, prefix = '') {
        for (const entr of fs.readdirSync(d, { withFileTypes: true })) {
            const rel = path.join(prefix, entr.name);
            const abs = path.join(d, entr.name);
            if (entr.isDirectory()) walk(abs, rel);
            else if (/\.(js|css)$/i.test(entr.name)) {
                out[rel.replace(/\\/g, '/')] = sha256File(abs);
            }
        }
    }
    walk(dir);
    return out;
}

function runBuild(outDir) {
    const env = {
        ...process.env,
        VITE_APP_VERSION: process.env.VITE_APP_VERSION || 'repro-test',
        VITE_API_BASE: process.env.VITE_API_BASE || '/api',
    };
    const r = spawnSync('npx', ['vite', 'build', '--outDir', outDir], {
        cwd: root,
        env,
        stdio: 'inherit',
        shell: false,
    });
    if (r.status !== 0) {
        console.error(`[repro] build into ${outDir} failed`);
        process.exit(r.status || 1);
    }
}

const aDir = path.join(root, '.repro-build-a');
const bDir = path.join(root, '.repro-build-b');

if (shouldRun) {
    fs.rmSync(aDir, { recursive: true, force: true });
    fs.rmSync(bDir, { recursive: true, force: true });
    runBuild(aDir);
    runBuild(bDir);
}

if (!fs.existsSync(aDir) || !fs.existsSync(bDir)) {
    console.error('[repro] missing .repro-build-a / .repro-build-b — pass --run to build them');
    process.exit(1);
}

const a = collectHashes(aDir);
const b = collectHashes(bDir);
const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
let failed = false;
for (const k of [...keys].sort()) {
    if (!a[k]) {
        console.error(`[repro] only in B: ${k}`);
        failed = true;
        continue;
    }
    if (!b[k]) {
        console.error(`[repro] only in A: ${k}`);
        failed = true;
        continue;
    }
    if (a[k] !== b[k]) {
        console.error(`[repro] hash mismatch: ${k}`);
        failed = true;
    }
}

if (failed) process.exit(1);
console.log(`[repro] ok (${keys.size} hashed assets identical)`);
