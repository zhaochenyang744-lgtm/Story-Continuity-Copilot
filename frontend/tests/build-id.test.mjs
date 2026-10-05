import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import { computeSourceBuildId, optionalBuildId, SOURCE_BUILD_ID_FILES, sourceBuildIdFromEntries } from "../build-id.mjs";

async function sourceFixture(prefix) {
  const root = await mkdtemp(path.join(tmpdir(), prefix));
  await mkdir(path.join(root, "app/components"), { recursive: true });
  for (const relativePath of SOURCE_BUILD_ID_FILES) {
    await writeFile(path.join(root, relativePath), `controlled:${relativePath}\n`);
  }
  await writeFile(path.join(root, "app/layout.tsx"), "export default 'layout';\n");
  await writeFile(path.join(root, "app/components/Workbench.tsx"), "export default 'workbench';\n");
  return root;
}

test("source digest is path-independent and ignores files outside its explicit boundary", async () => {
  const left = await sourceFixture("story-stage13-v4-impl-build-id-left-");
  const right = await sourceFixture("story-stage13-v4-impl-build-id-right-");
  assert.equal(await computeSourceBuildId(left), await computeSourceBuildId(right));
  await writeFile(path.join(right, "local-machine-path.txt"), "C:\\Users\\somebody\\workspace");
  assert.equal(await computeSourceBuildId(left), await computeSourceBuildId(right));
});

test("source and lockfile changes produce different build ids", async () => {
  const root = await sourceFixture("story-stage13-v4-impl-build-id-change-");
  const original = await computeSourceBuildId(root);
  await writeFile(path.join(root, "app/layout.tsx"), "export default 'changed';\n");
  const sourceChanged = await computeSourceBuildId(root);
  assert.notEqual(sourceChanged, original);
  await writeFile(path.join(root, "package-lock.json"), "controlled:changed-lock\n");
  assert.notEqual(await computeSourceBuildId(root), sourceChanged);
});

test("invalid build ids, absolute inputs, and duplicate inputs fail closed", () => {
  for (const value of ["", "Stage13-V4", "stage13_v4", "../stage13-v4", "C:\\Users\\builder", "stage13-v4/impl", "a".repeat(65)]) {
    assert.throws(() => optionalBuildId(value), /NEXT_BUILD_ID_INVALID/, value);
  }
  assert.throws(() => sourceBuildIdFromEntries([{ relativePath: "C:/source.ts", bytes: Buffer.from("x") }]), /SOURCE_BUILD_ID_PATH_INVALID/);
  assert.throws(() => sourceBuildIdFromEntries([
    { relativePath: "app/a.ts", bytes: Buffer.from("x") },
    { relativePath: "app/a.ts", bytes: Buffer.from("x") },
  ]), /SOURCE_BUILD_ID_INPUT_INVALID/);
});
