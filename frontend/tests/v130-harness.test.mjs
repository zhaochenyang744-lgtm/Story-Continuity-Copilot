import assert from "node:assert/strict";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import { validateV130Harness } from "../v130-harness.mjs";

function validEnv() {
  const root = path.join(tmpdir(), "story-v130-rc-node-contract");
  return {
    V130_HARNESS_PROFILE: "localrc",
    E2E_BASE_URL: "http://127.0.0.1:3197",
    E2E_BACKEND_ORIGIN: "http://127.0.0.1:8197",
    BACKEND_ORIGIN: "http://127.0.0.1:8197",
    PUBLIC_APP_MODE: "0",
    PUBLIC_BASE_URL: "http://127.0.0.1:3197",
    NEXT_DIST_DIR: ".next-v130-rc",
    E2E_ACCOUNT_PREFIX: "v130rcnode",
    E2E_TEST_ROOT: root,
    E2E_OUTPUT_DIR: path.join(root, "test-results"),
    E2E_REPORT_DIR: path.join(root, "report"),
    E2E_JSON_REPORT: path.join(root, "report.json"),
    E2E_PROVIDER_STATS: path.join(root, "provider-stats.json"),
    E2E_LAST_RUN: path.join(root, "last-run.json"),
    E2E_ARTIFACT_ROOT: path.join(root, "standalone"),
  };
}

test("accepts only the fixed v1.3.0 local release-candidate profile", () => {
  const result = validateV130Harness(validEnv());
  assert.equal(result.frontendPort, 3197);
  assert.equal(result.backendPort, 8197);
  assert.equal(result.distDir, ".next-v130-rc");
});

test("rejects wrong ports, mixed origins, dist, account prefix, and roots", () => {
  const mutations = [
    ["E2E_BASE_URL", "http://127.0.0.1:3196"],
    ["E2E_BACKEND_ORIGIN", "http://127.0.0.1:8196"],
    ["BACKEND_ORIGIN", "http://127.0.0.1:8198"],
    ["PUBLIC_BASE_URL", "http://127.0.0.1:3198"],
    ["NEXT_DIST_DIR", ".next-v120"],
    ["E2E_ACCOUNT_PREFIX", "v120mixed"],
    ["E2E_TEST_ROOT", path.resolve(".")],
  ];
  for (const [name, value] of mutations) {
    assert.throws(() => validateV130Harness({ ...validEnv(), [name]: value }), /INVALID|MISMATCH|OUTSIDE_SYSTEM_TEMP/, name);
  }
  const env = validEnv();
  env.E2E_REPORT_DIR = path.join(tmpdir(), "other-report");
  assert.throws(() => validateV130Harness(env), /PROFILE_MISMATCH|OUTSIDE_TEST_ROOT/);
});
