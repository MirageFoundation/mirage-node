#!/usr/bin/env node
// Response-shape provenance check for the legacy mobile bridge.
//
// scripts/legacy_mobile_canon_check.mjs proves the bytes we accept are the
// bytes the published app signs. It says nothing about what we send back.
// Our own suites assert the alias keys the bridge adds, but they assert them
// against this repo's understanding of the app, and the app's response types
// are compile-time only — at runtime it just renders undefined and no test
// anywhere fails.
//
// So this pulls real responses out of a running v1.39 node as a legacy client
// (no X-Mirage-Visitor header) and type-checks them against the app's own
// src/api/types.ts. A field the app declares as required and we no longer send
// becomes a tsc error naming the endpoint.
//
//   node scripts/legacy_mobile_shape_check.mjs [base-url] [/path/to/mirage-mobile-app]
//
// Exits non-zero when a payload does not satisfy the app's declared type.
//
// Fixtures are captured with widened inference (no `as const`), so string
// literal unions in the app's types report as `string` mismatches. Those are
// artifacts of the capture, not bridge defects; everything else is real.

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const repoRoot = path.resolve(import.meta.dirname, "..");
const baseUrl = (process.argv[2] || "http://127.0.0.1:80").replace(/\/$/, "");
const mobileRoot = process.argv[3] || path.resolve(repoRoot, "../mirage-mobile-app");

const apiDir = path.join(mobileRoot, "src/api");
if (!fs.existsSync(path.join(apiDir, "types.ts"))) {
  console.error(`mobile api types not found: ${apiDir}/types.ts`);
  console.error("pass the mobile checkout path as the second argument");
  process.exit(2);
}

// Every read the published app performs, paired with the type it declares for
// the response. Sourced from src/api/read/endpoints/*.ts — keep in sync when
// the app adds a read.
const READS = [
  ["get_posts?limit=3", "PostsResponse", "types"],
  ["get_user_posts?owner=$ADDR&address=$ADDR&limit=3", "PostsResponse", "types"],
  ["get_comments?post_id=$POST", "CommentsResponse", "types"],
  ["get_topics", "TopicsResponse", "types"],
  ["search_topics?q=$PREFIX", "SearchTopicsResponse", "types"],
  ["get_agents", "AgentsResponse", "agents"],
  ["get_profile?address=$ADDR", "ProfileResponse", "types"],
  ["get_user_status?address=$ADDR", "UserStatusResponse", "types"],
  ["get_user_followed?address=$ADDR", "UserFollowedResponse", "types"],
  ["get_user_blocked?address=$ADDR", "UserBlockedResponse", "types"],
  ["get_preferences?address=$ADDR", "PreferencesResponse", "types"],
  ["get_similar_users?address=$ADDR", "SimilarUsersResponse", "types"],
  ["get_users?limit=3", "UsersResponse", "types"],
  ["get_invite_codes?owner=$ADDR", "GetInviteCodesResponse", "types"],
  ["get_parameters?address=$ADDR", "ParametersResponse", "types"],
  ["get_chain_config", "ConfigResponse", "types"],
  ["get_node_config", "NodeConfigResponse", "types"],
  ["search?q=$PREFIX", "SearchResponse", "types"],
  ["get_inbox?address=$ADDR", "InboxResponse", "types"],
  ["get_network_stats", "NetworkStatsResponse", "types"],
  ["get_circulation_stats", "CirculationStatsResponse", "types"],
  // /api/get_stats is omitted deliberately: it requires a signed admin proof in
  // v1.38.11 and v1.39.0 alike, so the app's unsigned getAppStats() has always
  // answered 400 and there is no shape to compare.
  ["get_welcome_stats", "WelcomeStatsResponse", "types"],
  ["get_peers", "PeersResponse", "types"],
  ["referrals/precheck?address=$ADDR", "ReferralPrecheckResponse", "types"],
  ["referrals/summary?address=$ADDR", "ReferralSummaryResponse", "types"],
  ["referral/stats?address=$ADDR", "ReferralStatsResponse", "types"],
  ["rewards/summary?owner=$ADDR", "RewardSummaryResponse", "rewards"],
  ["rewards/achievements?owner=$ADDR", "AchievementsResponse", "rewards"],
  ["bootstrap?address=$ADDR&view=feed:home&limit=3", "BootstrapResponse", "bootstrap"],
];

// Mismatches that v1.38.11 produced identically, so the published app is
// already living with them against prod today. Each entry names the endpoint,
// a substring of the tsc message, and why it is not a bridge defect. A
// diagnostic that matches nothing here fails the check.
const BASELINE = {
  "get_user_posts?owner=$ADDR&address=$ADDR&limit=3": [
    {
      match: "'PostsResponse'",
      // v1.38.11's get_user_posts builds its own rows and sets root_post_id
      // only on comment results; author/root_* are absent for submissions in
      // both versions. The app's Post type declares them required regardless.
      reason: "v1.38.11 omits the same root_*/author keys for submissions",
    },
  ],
  get_topics: [
    { match: "'dominant_tag' are incompatible", reason: "v1.38.11 emits `dominant_tag or None` too" },
  ],
  "search_topics?q=$PREFIX": [
    { match: "'dominant_tag' are incompatible", reason: "v1.38.11 emits `dominant_tag or None` too" },
  ],
  "search?q=$PREFIX": [
    { match: "'dominant_tag' are incompatible", reason: "v1.38.11 emits `dominant_tag or None` too" },
  ],
  get_chain_config: [
    {
      match: "'ConfigResponse'",
      // The app's ConfigResponse is a union of both config payloads. v1.38.11's
      // get_chain_config docstring is explicit: "No difficulty/height — use
      // get_network_stats or get_parameters for those."
      reason: "ConfigResponse over-declares pow/validator fields get_chain_config never returned",
    },
  ],
  "get_inbox?address=$ADDR": [
    {
      match: "'type' are incompatible",
      reason: "capture widens the literal union to string; the value itself is a valid member",
    },
  ],
  "bootstrap?address=$ADDR&view=feed:home&limit=3": [
    { match: "'chain_config' are incompatible", reason: "same ConfigResponse over-declaration" },
  ],
};

async function getJson(url) {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  const text = await res.text();
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    body = null;
  }
  return { status: res.status, body };
}

// Seed values from live data so the personalized reads return populated
// payloads instead of empty envelopes that trivially satisfy any type.
const seed = await getJson(`${baseUrl}/api/get_posts?limit=1`);
if (seed.status !== 200 || !seed.body?.posts?.length) {
  console.error(`cannot seed from ${baseUrl}/api/get_posts (status=${seed.status})`);
  process.exit(2);
}
const seedPost = seed.body.posts[0];
const subs = {
  $ADDR: seedPost.author,
  $POST: seedPost.post_id,
  $PREFIX: String(seedPost.community || "a").slice(0, 2),
};
console.log(`seed address=${subs.$ADDR} post=${subs.$POST} prefix=${subs.$PREFIX}`);

const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "mirage-mobile-shape-"));
const srcDir = path.join(scratch, "src");
fs.cpSync(path.join(mobileRoot, "src"), srcDir, { recursive: true });

// The app's endpoint modules import a React Native axios client, Expo network
// state and MMKV-backed stores. None of that is reachable here and none of it
// affects the declared response types, so replace the runtime modules with
// type-compatible stubs and let tsc resolve everything else for real.
// The stub keeps api.get/post generic: the endpoint modules call them as
// api.get<T>(...), and a plain `any` makes that a "untyped function calls may
// not accept type arguments" error that has nothing to do with payload shapes.
fs.writeFileSync(
  path.join(srcDir, "api/client.ts"),
  [
    "type Stub = {",
    "  get<T>(path: string, params?: unknown, opts?: unknown): Promise<T>;",
    "  post<T>(path: string, body?: unknown, opts?: unknown): Promise<T>;",
    "  getApiUrl(path: string): string;",
    "};",
    "export const api: Stub = {} as Stub;",
    "export const apiClient: Stub = {} as Stub;",
    "",
  ].join("\n"),
);
fs.mkdirSync(path.join(srcDir, "api/signing"), { recursive: true });
fs.writeFileSync(
  path.join(srcDir, "api/signing/simple-sign.ts"),
  "export const buildSimpleSignedPayload: any = () => ({});\n",
);
fs.mkdirSync(path.join(srcDir, "wallet"), { recursive: true });
fs.writeFileSync(path.join(srcDir, "wallet/index.ts"), "export type MirageWallet = any;\n");

const lines = [
  'import type * as T from "./src/api/types";',
  'import type * as R from "./src/api/read/endpoints/rewards";',
  'import type * as B from "./src/api/read/endpoints/bootstrap";',
  'import type * as A from "./src/api/read/endpoints/agents";',
  "",
];
const NS = { types: "T", rewards: "R", bootstrap: "B", agents: "A" };

let captured = 0;
const skipped = [];
const fixtures = [];
for (const [spec, typeName, module] of READS) {
  const query = spec.replace(/\$[A-Z]+/g, (m) => encodeURIComponent(subs[m]));
  const { status, body } = await getJson(`${baseUrl}/api/${query}`);
  if (status !== 200 || body === null || typeof body !== "object") {
    skipped.push(`${spec} (status=${status})`);
    continue;
  }
  const id = spec.replace(/[^a-zA-Z0-9]/g, "_");
  // Line attribution counts newlines, not array elements: a captured payload is
  // one array element spanning hundreds of file lines, and tsc reports the file
  // line of the assignment it rejected.
  const lineOf = (arr) => arr.reduce((n, s) => n + s.split("\n").length, 1);
  const start = lineOf(lines);
  lines.push(`// GET /api/${query} -> ${status}`);
  lines.push(`const raw_${id} = ${JSON.stringify(body, null, 1)};`);
  lines.push(`const chk_${id}: ${NS[module]}.${typeName} = raw_${id};`);
  lines.push(`void chk_${id};`);
  lines.push("");
  fixtures.push({ spec, start, end: lineOf(lines) });
  captured += 1;
}

fs.writeFileSync(path.join(scratch, "shapes.ts"), lines.join("\n"));
fs.writeFileSync(
  path.join(scratch, "tsconfig.json"),
  JSON.stringify(
    {
      compilerOptions: {
        strict: true,
        noEmit: true,
        skipLibCheck: true,
        target: "es2022",
        module: "esnext",
        moduleResolution: "bundler",
        types: [],
        baseUrl: ".",
        paths: { "@/*": ["./*"] },
      },
      files: ["shapes.ts"],
    },
    null,
    2,
  ),
);

console.log(`captured ${captured} payloads, skipped ${skipped.length}`);
for (const s of skipped) console.log(`  skipped: ${s}`);
console.log(`typechecking against ${apiDir}/types.ts`);

let raw = "";
try {
  raw = execFileSync(
    "npx",
    ["--yes", "--package", "typescript@5.9", "tsc", "--project", path.join(scratch, "tsconfig.json")],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  );
} catch (err) {
  raw = (err.stdout || "") + (err.stderr || "");
}

// Only diagnostics against the captured payloads are verdicts. The app's own
// files pull in zustand, MMKV and Expo, none of which are installed here, and
// those errors say nothing about whether the bridge answers correctly.
// tsc reports the header on one line and the reason it rejected the assignment
// on the indented lines beneath it, so a diagnostic is the whole block. The
// property name that identifies a known mismatch only appears in the tail.
const blocks = [];
for (const line of raw.split("\n")) {
  if (/error TS\d+/.test(line)) {
    blocks.push(line);
  } else if (blocks.length && /^\s+\S/.test(line)) {
    blocks[blocks.length - 1] += `\n${line}`;
  }
}
const payloadErrors = blocks.filter((b) => b.includes("shapes.ts("));
const envErrors = blocks.filter((b) => !b.includes("shapes.ts("));

const unexpected = [];
const expected = [];
for (const block of payloadErrors) {
  const lineNo = Number(/shapes\.ts\((\d+),/.exec(block)?.[1] ?? 0);
  const fixture = fixtures.find((f) => lineNo >= f.start && lineNo <= f.end);
  const known = (BASELINE[fixture?.spec] || []).find((b) => block.includes(b.match));
  if (fixture && known) {
    expected.push(`${fixture.spec}: ${known.reason}`);
  } else {
    unexpected.push(`${fixture ? fixture.spec : "unattributed"}\n  ${block}`);
  }
}

for (const e of expected) console.log(`  known: ${e}`);
for (const u of unexpected) console.log(`  NEW: ${u}`);
console.log(
  `\n${expected.length} known-benign, ${unexpected.length} new, ${envErrors.length} ignored (missing app dependencies)`,
);
// A read that did not answer 200 was not checked, so it cannot count as a pass.
if (captured !== READS.length) {
  console.log(`only ${captured}/${READS.length} reads captured; a skipped read is not a pass`);
}
const failed = unexpected.length > 0 || captured !== READS.length;
console.log(failed ? "SHAPE CHECK FAILED" : "shape check passed");
if (failed) {
  // Keep the generated fixtures and stub tree so the diagnostic can be read
  // against the payload that produced it.
  console.log(`scratch tree kept for inspection: ${scratch}`);
} else {
  fs.rmSync(scratch, { recursive: true, force: true });
}
process.exit(failed ? 1 : 0);
