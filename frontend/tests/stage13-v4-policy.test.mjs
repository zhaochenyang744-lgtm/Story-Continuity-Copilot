import assert from "node:assert/strict";
import { copyFile, mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { scanStage13V4Artifact } from "../scripts/stage13-v4-policy.mjs";

const frontendRoot = path.resolve(import.meta.dirname, "..");

async function fixture(profile = "v4impl") {
  const impl = profile === "v4impl";
  const prefix = impl ? "story-stage13-v4-impl-unit-" : "story-stage13-v4-pm3-unit-";
  const dist = impl ? ".next-stage13-v4-impl" : ".next-stage13-v4-pm3";
  const backend = impl ? "http://127.0.0.1:8084" : "http://127.0.0.1:8085";
  const genericRoot = impl ? "V:\\" : "W:\\";
  const root = await mkdtemp(path.join(tmpdir(), prefix));
  await mkdir(path.join(root, dist), { recursive: true });
  await writeFile(path.join(root, "package.json"), JSON.stringify({ name: "story-continuity-app", version: "0.1.0" }));
  await writeFile(path.join(root, "server.js"), genericRoot.repeat(3));
  await writeFile(path.join(root, dist, "required-server-files.json"), genericRoot.repeat(4));
  await writeFile(path.join(root, dist, "routes-manifest.json"), JSON.stringify({ rewrites: { beforeFiles: [], afterFiles: [{ source: "/api/:path*", destination: `${backend}/api/:path*` }], fallback: [] } }));
  const copies = [
    ["node_modules/next/package.json", "node_modules/next/package.json"],
    ["node_modules/@img/sharp-win32-x64/package.json", "node_modules/@img/sharp-win32-x64/package.json"],
    ["node_modules/@img/sharp-win32-x64/lib/sharp-win32-x64-0.35.3.node", "node_modules/@img/sharp-win32-x64/lib/sharp-win32-x64-0.35.3.node"],
    ["node_modules/next/dist/lib/find-config.js", "node_modules/next/dist/lib/find-config.js"],
    ["node_modules/next/dist/server/patch-error-inspect.js", "node_modules/next/dist/server/patch-error-inspect.js"],
  ];
  for (const [source, destination] of copies) {
    const target = path.join(root, destination);
    await mkdir(path.dirname(target), { recursive: true });
    await copyFile(path.join(frontendRoot, source), target);
  }
  return { root, dist };
}

test("accepts only the exact V4 Level 2 and Level 3 tuples", async () => {
  for (const profile of ["v4impl", "v4pm3"]) {
    const { root } = await fixture(profile);
    const report = await scanStage13V4Artifact(root, profile);
    assert.equal(report.level2Hits.length, 2);
    assert.equal(report.level3Hits.length, 4);
  }
});

test("rejects Level 1 identity and unknown absolute roots", async () => {
  const identity = await fixture();
  await writeFile(path.join(identity.root, "identity.txt"), "story-continuity-web-demo-frontend");
  await assert.rejects(() => scanStage13V4Artifact(identity.root, "v4impl"), /LEVEL1_HIT/);
  const unknown = await fixture();
  await writeFile(path.join(unknown.root, "unknown.txt"), String.raw`X:\private\build\file.txt`);
  await assert.rejects(() => scanStage13V4Artifact(unknown.root, "v4impl"), /UNKNOWN_ABSOLUTE/);
  const escapedIdentity = await fixture();
  await writeFile(path.join(escapedIdentity.root, "escaped.js"), String.raw`const identity = "\u6D4B\u8BD5\u8005";`);
  await assert.rejects(
    () => scanStage13V4Artifact(escapedIdentity.root, "v4impl", ["测试者"]),
    /LEVEL1_HIT/,
  );
  const derivedIdentity = await fixture();
  const syntheticCheckout = path.join(homedir(), "Documents", "Workspace", "Story-Continuity-Copilot", "output", "story-continuity-web-demo", "frontend");
  await writeFile(path.join(derivedIdentity.root, "derived.txt"), path.basename(homedir()));
  await assert.rejects(
    () => scanStage13V4Artifact(derivedIdentity.root, "v4impl", [syntheticCheckout]),
    /LEVEL1_HIT/,
  );
  const lowercaseSegmented = await fixture();
  await writeFile(path.join(lowercaseSegmented.root, "lowercase.txt"), String.raw`c:\Users\secret\file.txt`);
  await assert.rejects(() => scanStage13V4Artifact(lowercaseSegmented.root, "v4impl"), /UNKNOWN_ABSOLUTE/);
});

test("rejects Level 2 location/count and Level 3 hash/count/version drift", async () => {
  const generic = await fixture();
  await writeFile(path.join(generic.root, "client.js"), "V:\\");
  await assert.rejects(() => scanStage13V4Artifact(generic.root, "v4impl"), /LEVEL2_MISMATCH/);
  const hash = await fixture();
  const findConfig = path.join(hash.root, "node_modules/next/dist/lib/find-config.js");
  await writeFile(findConfig, Buffer.concat([await readFile(findConfig), Buffer.from("\n") ]));
  await assert.rejects(() => scanStage13V4Artifact(hash.root, "v4impl"), /LEVEL3_TUPLE_MISMATCH/);
  const version = await fixture();
  const nextPackage = path.join(version.root, "node_modules/next/package.json");
  const packageJson = JSON.parse(await readFile(nextPackage, "utf8"));
  packageJson.version = "16.3.4";
  await writeFile(nextPackage, JSON.stringify(packageJson));
  await assert.rejects(() => scanStage13V4Artifact(version.root, "v4impl"), /LEVEL3_TUPLE_MISMATCH/);
});

test("rejects mixed profile temp roots", async () => {
  const { root } = await fixture("v4pm3");
  await assert.rejects(() => scanStage13V4Artifact(root, "v4impl"), /ARTIFACT_PROFILE_MISMATCH/);
});
