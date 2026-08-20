import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

describe('no GTM / third-party executables', () => {
    it('index.html has no GTM markers', () => {
        const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
        expect(html).not.toMatch(/googletagmanager/i);
        expect(html).not.toMatch(/GTM-TL3G7VNP/);
        expect(html).not.toMatch(/dataLayer/);
    });

    it('pow worker imports only same-origin argon2', () => {
        const worker = fs.readFileSync(path.join(root, 'public/pow/worker.js'), 'utf8');
        expect(worker).toContain("importScripts('/pow/argon2-bundled.min.js')");
        expect(worker).not.toMatch(/jsdelivr|http:\/\/|https:\/\//);
    });

    it('pow worker fails fast when CSP blocks WASM', () => {
        const worker = fs.readFileSync(path.join(root, 'public/pow/worker.js'), 'utf8');
        expect(worker).toContain('assertWasmAllowed');
        expect(worker).toContain('wasm_csp_blocked');
        expect(worker).toContain('WebAssembly.instantiate');
    });

    it('FAQ markdown embeds via Vite define', () => {
        const faq = fs.readFileSync(path.join(root, 'src/content/faqMarkdown.js'), 'utf8');
        expect(faq).toContain('__MIRAGE_FAQ_MARKDOWN__');
        expect(faq).toContain('vite.config.js');
    });
});
