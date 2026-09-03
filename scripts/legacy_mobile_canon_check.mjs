#!/usr/bin/env node
// Provenance check for the legacy_mobile canonical vectors.
//
// The compatibility bridge only works if the bytes the PUBLISHED mobile app
// signs are exactly the bytes the chain rebuilds. Comparing our vectors against
// shared/canon.py cannot prove that, because both come from this repo. This
// script runs the app's own builder — src/api/write/signing/canonical.ts, taken
// verbatim from the mobile checkout, with only the "@/src/wallet/crypto" import
// replaced by a local concatBytes — and diffs it against
// shared/testdata/canon_v139_vectors.json.
//
// It needs the mobile repo, which is not available inside the test container,
// so it is a local operator tool rather than a suite test. Run it whenever a
// legacy_mobile vector or a canonical builder changes:
//
//   node --experimental-strip-types scripts/legacy_mobile_canon_check.mjs \
//     [/path/to/mirage-mobile-app]
//
// Exits non-zero on any mismatch and prints every offending vector.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const repoRoot = path.resolve(import.meta.dirname, "..");
const mobileRoot = process.argv[2] || path.resolve(repoRoot, "../mirage-mobile-app");
const canonicalSource = path.join(mobileRoot, "src/api/write/signing/canonical.ts");
if (!fs.existsSync(canonicalSource)) {
  console.error(`mobile canonical builder not found: ${canonicalSource}`);
  console.error("pass the mobile checkout path as the first argument");
  process.exit(2);
}

const cryptoImport = 'import { concatBytes } from "@/src/wallet/crypto";';
const concatShim = `
function concatBytes(...arrays) {
  const total = arrays.reduce((n, a) => n + a.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const a of arrays) { out.set(a, offset); offset += a.length; }
  return out;
}
`;
const source = fs.readFileSync(canonicalSource, "utf8");
if (!source.includes(cryptoImport)) {
  console.error(`${canonicalSource} no longer imports concatBytes the expected way; update this script`);
  process.exit(2);
}
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "mirage-mobile-canon-"));
const patchedPath = path.join(scratch, "canonical.mobile.ts");
fs.writeFileSync(patchedPath, source.replace(cryptoImport, concatShim));
const canon = await import(patchedPath);
fs.rmSync(scratch, { recursive: true, force: true });

const vectorFile = JSON.parse(
  fs.readFileSync(path.join(repoRoot, "shared/testdata/canon_v139_vectors.json"), "utf8")
);
const envelopeKeys = {
  legacy_mobile: "legacy_mobile_envelope",
  legacy_mobile_paid: "legacy_mobile_paid_envelope",
};

const hex = (u8) => Buffer.from(u8).toString("hex");

/** Build the vector with the app's builder, or null when the app cannot sign it. */
function published(msg, envelope, fields) {
  const base = {
    pubkey33: Buffer.from(envelope.pubkey_hex, "hex"),
    lastBlockHashBytes: Buffer.from(envelope.block_hash_hex, "hex"),
    difficulty: Number(envelope.difficulty),
    timestampMs: Number(envelope.timestamp),
    envelopeNonce: BigInt(envelope.nonce),
  };
  switch (msg) {
    case "MsgPost":
      // The app has no protocol_version field at all, so it can only produce
      // the protocol-0 form; the protocol-1 vector is what the migrated app
      // must send and is covered by the in-suite encoder instead.
      if (Number(fields.protocol_version) !== 0) return null;
      return canon.canonBasePost({
        ...base,
        target: fields.target,
        topic: fields.community,
        title: fields.title,
        content: fields.content,
        tag: fields.tag,
        media: fields.media,
      });
    case "MsgSubscribe": {
      // Same here: the app never sends period_count.
      if (Number(fields.period_count) !== 0) return null;
      if (Number(base.difficulty) !== 0) {
        throw new Error("the app always signs difficulty 0 for subscriptions");
      }
      const paid = {
        pubkey33: base.pubkey33,
        lastBlockHashBytes: base.lastBlockHashBytes,
        timestampMs: base.timestampMs,
        envelopeNonce: base.envelopeNonce,
        level: Number(fields.level),
      };
      return fields.target
        ? canon.canonBaseGiftSubscription({ ...paid, target: fields.target })
        : canon.canonBaseUpgradeLevel(paid);
    }
    case "MsgFollowTopic":
      return canon.canonBaseFollowTopic({ ...base, target: fields.target, topic: fields.topic });
    case "MsgUnfollowTopic":
      return canon.canonBaseUnfollowTopic({ ...base, target: fields.target, topic: fields.topic });
    case "MsgBlockTopic":
      return canon.canonBaseBlockTopic({ ...base, target: fields.target, topic: fields.topic });
    case "MsgUnblockTopic":
      return canon.canonBaseUnblockTopic({ ...base, target: fields.target, topic: fields.topic });
    default:
      return null;
  }
}

let checked = 0;
const mismatches = [];
for (const vector of vectorFile.vectors) {
  const envelopeKey = envelopeKeys[vector.envelope];
  if (!envelopeKey) continue;
  const built = published(vector.msg, vectorFile[envelopeKey], vector.fields);
  if (built === null) continue;
  checked += 1;
  const got = hex(built);
  if (got !== vector.canon_hex) {
    mismatches.push({ msg: vector.msg, fields: vector.fields, expected: vector.canon_hex, got });
  }
}

if (checked === 0) {
  console.error("no legacy_mobile vectors were comparable; the fixture or this script drifted");
  process.exit(2);
}
if (mismatches.length > 0) {
  console.error(`${mismatches.length} of ${checked} vectors do not match the published app:`);
  console.error(JSON.stringify(mismatches, null, 2));
  process.exit(1);
}
console.log(`ok: ${checked} legacy_mobile vectors match the published app byte for byte`);
