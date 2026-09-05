import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import { scanV130ReleaseArtifact } from "../scripts/v130-release-scan.mjs";

async function fixture() {
  const root = await mkdtemp(path.join(tmpdir(), "story-v130-rc-scan-"));
  await mkdir(path.join(root, ".next-v130-rc", "static"), { recursive: true });
  await mkdir(path.join(root, "public"), { recursive: true });
  await writeFile(path.join(root, "server.js"), "const release = 'v1.3.0';\n");
  await writeFile(path.join(root, "public", "brand.txt"), "Story Continuity\n");
  await writeFile(path.join(root, ".next-v130-rc", "routes-manifest.json"), JSON.stringify({
    rewrites: { beforeFiles: [], afterFiles: [{ source: "/api/:path*", destination: "http://127.0.0.1:8197/api/:path*" }], fallback: [] },
  }));
  return root;
}

test("accepts a standalone artifact with the exact same-origin backend rewrite", async () => {
  const root = await fixture();
  const result = await scanV130ReleaseArtifact(root, { distDir: ".next-v130-rc", backendOrigin: "http://127.0.0.1:8197", identities: ["private-workspace"] });
  assert.equal(result.status, "passed");
  assert.equal(result.rewrite.rewriteCount, 1);
});

test("rejects local identities, test endpoints, account fixtures, and secrets", async () => {
  for (const value of ["C:\\Users\\private\\repo", "/api/test/stats", "person@example.test", "sk-1234567890abcdef"]) {
    const root = await fixture();
    await writeFile(path.join(root, "leak.js"), value);
    await assert.rejects(() => scanV130ReleaseArtifact(root, { distDir: ".next-v130-rc", backendOrigin: "http://127.0.0.1:8197", identities: ["C:\\Users\\private\\repo"] }), /V130_RELEASE_/);
  }
});
