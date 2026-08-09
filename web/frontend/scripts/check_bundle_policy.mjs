#!/usr/bin/env node
/**
 * Fail if the production build contains forbidden third-party script patterns.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const buildDir = path.join(root, 'build');

const FORBIDDEN = [
    /googletagmanager/i,
    /gtm\.js/i,
    /GTM-TL3G7VNP/,
    /dataLayer/,
    /cdn\.jsdelivr\.net/i,
    /importScripts\s*\(\s*['"]https?:\/\//i,
];

function walk(dir, out = []) {
    if (!fs.existsSync(dir)) return out;
    for (const entr of fs.readdirSync(dir, { withFileTypes: true })) {
        const p = path.join(dir, entr.name);
        if (entr.isDirectory()) walk(p, out);
        else if (/\.(js|html|css|txt|map)$/i.test(entr.name)) out.push(p);
    }
    return out;
}

if (!fs.existsSync(buildDir)) {
    console.error('[bundle-policy] build/ missing — run npm run build first');
    process.exit(1);
}

const files = walk(buildDir);
let failed = false;
for (const file of files) {
    if (file.endsWith('.map')) {
        console.error(`[bundle-policy] source map present: ${path.relative(root, file)}`);
        failed = true;
        continue;
    }
    const text = fs.readFileSync(file, 'utf8');
    for (const re of FORBIDDEN) {
        if (re.test(text)) {
            console.error(`[bundle-policy] forbidden pattern ${re} in ${path.relative(root, file)}`);
            failed = true;
        }
    }
}

const indexHtml = path.join(buildDir, 'index.html');
if (fs.existsSync(indexHtml)) {
    const html = fs.readFileSync(indexHtml, 'utf8');
    if (/googletagmanager|GTM-TL3G7VNP|dataLayer/i.test(html)) {
        console.error('[bundle-policy] GTM still present in build/index.html');
        failed = true;
    }
}

if (failed) process.exit(1);
console.log(`[bundle-policy] ok (${files.length} files scanned)`);
