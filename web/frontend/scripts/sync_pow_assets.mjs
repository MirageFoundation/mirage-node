#!/usr/bin/env node
/**
 * Sync argon2-browser PoW runtime assets into public/pow/.
 * Usage:
 *   node scripts/sync_pow_assets.mjs          # copy + write MANIFEST
 *   node scripts/sync_pow_assets.mjs --check  # verify hashes match lockfile package
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const require = createRequire(import.meta.url);
const checkOnly = process.argv.includes('--check');

function sha256(buf) {
    return crypto.createHash('sha256').update(buf).digest('hex');
}

function resolvePkg() {
    const pkgJsonPath = require.resolve('argon2-browser/package.json');
    const pkg = JSON.parse(fs.readFileSync(pkgJsonPath, 'utf8'));
    const distDir = path.join(path.dirname(pkgJsonPath), 'dist');
    return { pkg, distDir, version: pkg.version, name: pkg.name };
}

const { distDir, version, name } = resolvePkg();
const assets = [
    { src: 'argon2-bundled.min.js', dest: 'argon2-bundled.min.js' },
];

// Some builds also ship a separate wasm; include if present.
const optionalWasm = path.join(distDir, 'argon2.wasm');
if (fs.existsSync(optionalWasm)) {
    assets.push({ src: 'argon2.wasm', dest: 'argon2.wasm' });
}

const outDir = path.join(root, 'public', 'pow');
const manifestPath = path.join(outDir, 'MANIFEST.txt');

const lines = [
    `package=${name}@${version}`,
    `synced_at=${new Date().toISOString()}`,
];

for (const asset of assets) {
    const srcPath = path.join(distDir, asset.src);
    if (!fs.existsSync(srcPath)) {
        console.error(`[pow] missing source asset: ${srcPath}`);
        process.exit(1);
    }
    const buf = fs.readFileSync(srcPath);
    const hash = sha256(buf);
    const destPath = path.join(outDir, asset.dest);
    lines.push(`${asset.dest} sha256=${hash} bytes=${buf.length}`);

    if (checkOnly) {
        if (!fs.existsSync(destPath)) {
            console.error(`[pow] missing vendored asset: ${destPath}`);
            process.exit(1);
        }
        const existing = fs.readFileSync(destPath);
        const existingHash = sha256(existing);
        if (existingHash !== hash) {
            console.error(`[pow] hash mismatch for ${asset.dest}: expected ${hash}, got ${existingHash}`);
            process.exit(1);
        }
    } else {
        fs.mkdirSync(outDir, { recursive: true });
        fs.writeFileSync(destPath, buf);
        console.log(`[pow] wrote ${asset.dest} (${buf.length} bytes, sha256=${hash})`);
    }
}

if (checkOnly) {
    if (!fs.existsSync(manifestPath)) {
        console.error(`[pow] missing MANIFEST.txt`);
        process.exit(1);
    }
    const existingManifest = fs.readFileSync(manifestPath, 'utf8').trim().split('\n');
    // Compare asset lines (skip synced_at which changes)
    const expectedAssets = lines.filter((l) => l.includes('sha256='));
    const actualAssets = existingManifest.filter((l) => l.includes('sha256='));
    const pkgLine = existingManifest.find((l) => l.startsWith('package='));
    if (pkgLine !== `package=${name}@${version}`) {
        console.error(`[pow] package drift: ${pkgLine} vs package=${name}@${version}`);
        process.exit(1);
    }
    for (const line of expectedAssets) {
        if (!actualAssets.includes(line)) {
            console.error(`[pow] manifest drift: expected ${line}`);
            process.exit(1);
        }
    }
    console.log(`[pow] check ok (${name}@${version}, ${assets.length} assets)`);
    process.exit(0);
}

fs.writeFileSync(manifestPath, lines.join('\n') + '\n');
console.log(`[pow] wrote MANIFEST.txt for ${name}@${version}`);
