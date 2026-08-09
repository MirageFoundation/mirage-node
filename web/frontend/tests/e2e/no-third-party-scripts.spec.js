import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

test('built index.html contains no GTM', async () => {
    const htmlPath = path.join(root, 'build/index.html');
    test.skip(!fs.existsSync(htmlPath), 'build/index.html missing — run npm run build first');
    const html = fs.readFileSync(htmlPath, 'utf8');
    expect(html).not.toMatch(/googletagmanager|GTM-TL3G7VNP|dataLayer/i);
});

test('preview shell loads without third-party analytics scripts', async ({ page }) => {
    const blocked = [];
    page.on('request', (req) => {
        const u = req.url();
        if (/googletagmanager|gtm\.js|cdn\.jsdelivr\.net/i.test(u)) blocked.push(u);
    });
    await page.goto('/');
    await expect(page.locator('#root')).toBeVisible({ timeout: 15000 });
    expect(blocked).toEqual([]);
});
