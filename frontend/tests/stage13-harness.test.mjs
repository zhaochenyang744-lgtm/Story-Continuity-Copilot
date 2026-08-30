import assert from "node:assert/strict";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import { validateStage13Harness } from "../stage13-harness.mjs";

const profileValues = {
  impl: [3080, 8080, ".next-stage13-impl", "story-stage13-impl-", "stage13impl"],
  pm3: [3081, 8081, ".next-stage13-pm3", "story-stage13-pm3-", "stage13pm3"],
  v4impl: [3084, 8084, ".next-stage13-v4-impl", "story-stage13-v4-impl-", "stage13v4impl"],
  v4pm3: [3085, 8085, ".next-stage13-v4-pm3", "story-stage13-v4-pm3-", "stage13v4pm3"],
};

function profileEnv(profile) {
  const [frontendPort, backendPort, distDir, tempPrefix, accountPrefix] = profileValues[profile];
  const root = path.join(tmpdir(), `${tempPrefix}node-profile`);
  return {
    STAGE13_HARNESS_PROFILE: profile,
    E2E_BASE_URL: `http://127.0.0.1:${frontendPort}`,
    E2E_BACKEND_ORIGIN: `http://127.0.0.1:${backendPort}`,
    BACKEND_ORIGIN: `http://127.0.0.1:${backendPort}`,
    PUBLIC_APP_MODE: "0",
    PUBLIC_BASE_URL: `http://127.0.0.1:${frontendPort}`,
    NEXT_DIST_DIR: distDir,
    E2E_ACCOUNT_PREFIX: `${accountPrefix}node`,
    E2E_TEST_ROOT: root,
    E2E_OUTPUT_DIR: path.join(root, "playwright"),
  };
}

test("accepts the exact V2 and V4 implementation and PM3 frozen profiles", () => {
  assert.equal(validateStage13Harness(profileEnv("impl")).frontendPort, 3080);
  assert.equal(validateStage13Harness(profileEnv("pm3")).backendPort, 8081);
  assert.equal(validateStage13Harness(profileEnv("v4impl")).frontendPort, 3084);
  assert.equal(validateStage13Harness(profileEnv("v4pm3")).backendPort, 8085);
});

test("rejects mixed profiles, other ports, prefixes, dist dirs, and temp roots", () => {
  const mutations = [
    ["E2E_BASE_URL", "http://127.0.0.1:3081"],
    ["E2E_BACKEND_ORIGIN", "http://127.0.0.1:8081"],
    ["NEXT_DIST_DIR", ".next-stage13-pm3"],
    ["E2E_ACCOUNT_PREFIX", "stage13pm3wrong"],
    ["E2E_TEST_ROOT", path.resolve(".")],
  ];
  for (const [name, value] of mutations) {
    const env = profileEnv("impl");
    env[name] = value;
    assert.throws(() => validateStage13Harness(env), /MISMATCH|OUTSIDE_SYSTEM_TEMP/, name);
  }
  assert.throws(
    () => validateStage13Harness({ ...profileEnv("v4impl"), E2E_BASE_URL: "http://127.0.0.1:3085" }),
    /MISMATCH/,
  );
});
