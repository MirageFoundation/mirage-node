#!/usr/bin/env node
/**
 * Gate `npm audit` at moderate, with an explicit allowlist.
 *
 * Gating at `high` meant moderate advisories never surfaced at all, so nobody
 * had to decide about them. Gating at `moderate` with no escape hatch would
 * fail CI on advisories that were reviewed and accepted. This does both: any
 * moderate-or-worse advisory fails the build unless its GHSA id is listed here
 * with a reason, so an accepted risk is a recorded decision rather than a
 * threshold that hides it.
 *
 * Adding an entry is a security decision. Removing one is free.
 */

import { execFileSync } from 'node:child_process';

const SEVERITY_ORDER = ['info', 'low', 'moderate', 'high', 'critical'];
const MIN_SEVERITY = 'moderate';

const ACCEPTED = new Map([
    ['GHSA-wrjc-x8rr-h8h6', 'react-router open redirect via backslash in Link/useNavigate. Reachable only from a router target built from user input; mention and hashtag plugins constrain their path segments to [A-Za-z0-9-] and encodeURIComponent. Fix is a breaking major bump to 7.x. Accepted 2026-08-15 (frontend review 2026-08-14).'],
    ['GHSA-337j-9hxr-rhxg', 'react-router arbitrary constructor injection via deserializeErrors() during SSR hydration. Unreachable: this is a client-rendered Vite app using BrowserRouter with no hydration path. Accepted 2026-08-15 (frontend review 2026-08-14).'],
    ['GHSA-jjmj-jmhj-qwj2', 'react-router-dom open redirect leading to XSS, same root cause and same reachability argument as GHSA-wrjc-x8rr-h8h6. Accepted 2026-08-15 (frontend review 2026-08-14).'],
]);

function auditJson() {
    try {
        // npm audit exits non-zero when it finds anything, so the throw carries the report.
        return JSON.parse(execFileSync('npm', ['audit', '--json'], { encoding: 'utf8' }));
    } catch (err) {
        if (!err.stdout) throw err;
        return JSON.parse(err.stdout);
    }
}

function meetsThreshold(severity) {
    return SEVERITY_ORDER.indexOf(severity) >= SEVERITY_ORDER.indexOf(MIN_SEVERITY);
}

const report = auditJson();
const vulnerabilities = report.vulnerabilities || {};
const unaccepted = [];
const accepted = [];

for (const [pkg, entry] of Object.entries(vulnerabilities)) {
    if (!meetsThreshold(entry.severity)) continue;
    for (const via of entry.via || []) {
        if (typeof via !== 'object' || !via.url) continue;
        if (!meetsThreshold(via.severity)) continue;
        const id = String(via.url).split('/').pop();
        (ACCEPTED.has(id) ? accepted : unaccepted).push({ pkg, id, title: via.title, severity: via.severity });
    }
}

for (const a of accepted) {
    console.log(`accepted  ${a.severity.padEnd(8)} ${a.id}  ${a.pkg}  ${a.title}`);
}

if (unaccepted.length === 0) {
    console.log(`ok (${accepted.length} accepted, 0 unreviewed at ${MIN_SEVERITY}+)`);
    process.exit(0);
}

console.error(`\n${unaccepted.length} unreviewed advisory/advisories at ${MIN_SEVERITY}+:\n`);
for (const u of unaccepted) {
    console.error(`  ${u.severity.padEnd(8)} ${u.id}  ${u.pkg}  ${u.title}`);
}
console.error('\nFix it, or add the GHSA id to ACCEPTED in scripts/check_audit.mjs with a reason.');
process.exit(1);
