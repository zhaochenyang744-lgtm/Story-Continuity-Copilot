import assert from "node:assert/strict";
import { mkdir, mkdtemp, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import { scanStage13V4RuntimeEvidence } from "../scripts/stage13-v4-runtime-scan.mjs";

test("compressed binary bytes do not become synthetic paths", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "story-stage13-v4-impl-runtime-binary-"));
  await writeFile(path.join(root, "screen.png"), Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x66, 0x3a, 0x5c, 0x03, 0xff, 0x29, 0x1b, 0x08, 0x5c, 0x7f]));
  assert.equal((await scanStage13V4RuntimeEvidence(root, "v4impl")).level4AbsoluteHits, 0);
});

test("printable paths embedded in binary evidence and test hooks still fail closed", async () => {
  const binaryRoot = await mkdtemp(path.join(tmpdir(), "story-stage13-v4-impl-runtime-path-"));
  await writeFile(path.join(binaryRoot, "screen.png"), Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47]), Buffer.from(" metadata C:\\Users\\secret\\file.txt ")]));
  await assert.rejects(() => scanStage13V4RuntimeEvidence(binaryRoot, "v4impl"), /STAGE13_V4_RUNTIME_HIT/);
  const hookRoot = await mkdtemp(path.join(tmpdir(), "story-stage13-v4-impl-runtime-hook-"));
  await writeFile(path.join(hookRoot, "browser.json"), JSON.stringify({ path: "/api/test/stage13/stats" }));
  await assert.rejects(() => scanStage13V4RuntimeEvidence(hookRoot, "v4impl"), /STAGE13_V4_RUNTIME_HIT/);
});

test("Unicode-escaped identities fail closed independent of the identity text", async () => {
  const lowercaseRoot = await mkdtemp(path.join(tmpdir(), "story-stage13-v4-impl-runtime-unicode-lower-"));
  await writeFile(path.join(lowercaseRoot, "client.js"), String.raw`const identity = "\u6d4b\u8bd5\u8005";`);
  await assert.rejects(() => scanStage13V4RuntimeEvidence(lowercaseRoot, "v4impl", ["测试者"]), /STAGE13_V4_RUNTIME_HIT/);
  const uppercaseRoot = await mkdtemp(path.join(tmpdir(), "story-stage13-v4-impl-runtime-unicode-upper-"));
  await writeFile(path.join(uppercaseRoot, "client.js"), String.raw`const identity = "\u6D4B\u8BD5\u8005";`);
  await assert.rejects(() => scanStage13V4RuntimeEvidence(uppercaseRoot, "v4impl", ["测试者"]), /STAGE13_V4_RUNTIME_HIT/);
});

test("runtime evidence rejects a junction without following it", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "story-stage13-v4-impl-runtime-link-"));
  const target = path.join(root, "target");
  await mkdir(target);
  await writeFile(path.join(target, "safe.txt"), "safe");
  await symlink(target, path.join(root, "evidence-link"), "junction");
  await assert.rejects(() => scanStage13V4RuntimeEvidence(root, "v4impl"), /STAGE13_V4_RUNTIME_LINK_FORBIDDEN/);
  const rootContainer = await mkdtemp(path.join(tmpdir(), "story-stage13-v4-impl-runtime-root-link-"));
  const rootTarget = path.join(rootContainer, "target");
  const rootLink = path.join(rootContainer, "evidence-root");
  await mkdir(rootTarget);
  await writeFile(path.join(rootTarget, "safe.txt"), "safe");
  await symlink(rootTarget, rootLink, "junction");
  await assert.rejects(() => scanStage13V4RuntimeEvidence(rootLink, "v4impl"), /STAGE13_V4_RUNTIME_LINK_FORBIDDEN:evidence-root/);
});
