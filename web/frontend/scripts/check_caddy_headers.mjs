#!/usr/bin/env node
/**
 * Assert the browser-hardening headers the wallet origin is supposed to serve.
 *
 * Nothing tested any response header, so deleting X-Frame-Options or the CSP
 * would have merged green. These controls are load-bearing precisely because
 * the plaintext seed default makes any script execution on this origin a total
 * wallet compromise, so their presence needs a gate rather than a convention.
 *
 * This reads the Caddy template rather than probing a live origin: the origin
 * config is the repository-controlled guarantee, and a CDN may add headers but
 * cannot be relied on to.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const CADDYFILE = resolve(here, '../../../deploy/templates/caddy/Caddyfile');

const REQUIRED = [
    ['X-Frame-Options', /X-Frame-Options\s+"DENY"/],
    ['X-Content-Type-Options', /X-Content-Type-Options\s+"nosniff"/],
    ['Referrer-Policy', /Referrer-Policy\s+"strict-origin-when-cross-origin"/],
    ['Permissions-Policy', /Permissions-Policy\s+"[^"]*camera=\(\)[^"]*"/],
    ['Cross-Origin-Opener-Policy', /Cross-Origin-Opener-Policy\s+"same-origin"/],
    ['Cross-Origin-Resource-Policy', /Cross-Origin-Resource-Policy\s+"same-origin"/],
];

// Directives that must be present inside the enforcing CSP.
const REQUIRED_CSP_DIRECTIVES = [
    "default-src 'self'",
    "script-src 'self'",
    "worker-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
];

const text = readFileSync(CADDYFILE, 'utf8');
const failures = [];

for (const [name, pattern] of REQUIRED) {
    if (!pattern.test(text)) failures.push(`missing or altered header: ${name}`);
}

// The policy must be enforcing. Report-Only blocks nothing, and this origin
// shipped Report-Only with no reporting endpoint for long enough that it needs
// a gate rather than a comment.
const cspMatch = text.match(/^\s*Content-Security-Policy\s+"([^"]+)"/m);
if (!cspMatch) {
    failures.push('no enforcing Content-Security-Policy header found');
} else {
    for (const directive of REQUIRED_CSP_DIRECTIVES) {
        if (!cspMatch[1].includes(directive)) {
            failures.push(`CSP is missing directive: ${directive}`);
        }
    }
}

if (/Content-Security-Policy-Report-Only/.test(text)) {
    failures.push('Content-Security-Policy-Report-Only is present; the policy must be enforcing');
}

if (failures.length > 0) {
    console.error(`check:headers failed (${CADDYFILE})\n`);
    for (const f of failures) console.error(`  - ${f}`);
    process.exit(1);
}

console.log(`ok (${REQUIRED.length} headers + enforcing CSP with ${REQUIRED_CSP_DIRECTIVES.length} required directives)`);
