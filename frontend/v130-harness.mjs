import path from "node:path";
import { tmpdir } from "node:os";

export const V130_PROFILE = Object.freeze({
  name: "localrc",
  frontendOrigin: "http://127.0.0.1:3197",
  backendOrigin: "http://127.0.0.1:8197",
  distDir: ".next-v130-rc",
  tempPrefix: "story-v130-rc-",
  accountPrefix: "v130rc",
});

function isolatedPath(value, name, { root } = {}) {
  if (!value) throw new Error(`${name}_REQUIRED`);
  const resolved = path.resolve(value);
  const relativeToTemp = path.relative(path.resolve(tmpdir()), resolved);
  if (!relativeToTemp || relativeToTemp.startsWith("..") || path.isAbsolute(relativeToTemp)) {
    throw new Error(`${name}_OUTSIDE_SYSTEM_TEMP`);
  }
  if (!resolved.split(path.sep).some((part) => part.startsWith(V130_PROFILE.tempPrefix))) {
    throw new Error(`${name}_PROFILE_MISMATCH`);
  }
  if (root) {
    const relativeToRoot = path.relative(root, resolved);
    if (!relativeToRoot || relativeToRoot.startsWith("..") || path.isAbsolute(relativeToRoot)) {
      throw new Error(`${name}_OUTSIDE_TEST_ROOT`);
    }
  }
  return resolved;
}

export function validateV130Harness(env) {
  if (env.V130_HARNESS_PROFILE !== V130_PROFILE.name) {
    throw new Error("V130_HARNESS_PROFILE_INVALID");
  }
  const exact = {
    E2E_BASE_URL: V130_PROFILE.frontendOrigin,
    E2E_BACKEND_ORIGIN: V130_PROFILE.backendOrigin,
    BACKEND_ORIGIN: V130_PROFILE.backendOrigin,
    PUBLIC_APP_MODE: "0",
    PUBLIC_BASE_URL: V130_PROFILE.frontendOrigin,
    NEXT_DIST_DIR: V130_PROFILE.distDir,
  };
  for (const [name, expected] of Object.entries(exact)) {
    if (env[name] !== expected) throw new Error(`${name}_PROFILE_MISMATCH`);
  }
  if (!env.E2E_ACCOUNT_PREFIX?.startsWith(V130_PROFILE.accountPrefix)) {
    throw new Error("E2E_ACCOUNT_PREFIX_PROFILE_MISMATCH");
  }
  const testRoot = isolatedPath(env.E2E_TEST_ROOT, "E2E_TEST_ROOT");
  const outputDir = isolatedPath(env.E2E_OUTPUT_DIR, "E2E_OUTPUT_DIR", { root: testRoot });
  const reportDir = isolatedPath(env.E2E_REPORT_DIR, "E2E_REPORT_DIR", { root: testRoot });
  const jsonReport = isolatedPath(env.E2E_JSON_REPORT, "E2E_JSON_REPORT", { root: testRoot });
  const providerStats = isolatedPath(env.E2E_PROVIDER_STATS, "E2E_PROVIDER_STATS", { root: testRoot });
  const lastRun = isolatedPath(env.E2E_LAST_RUN, "E2E_LAST_RUN", { root: testRoot });
  const artifactRoot = isolatedPath(env.E2E_ARTIFACT_ROOT, "E2E_ARTIFACT_ROOT", { root: testRoot });
  return {
    ...V130_PROFILE,
    frontendPort: Number(new URL(V130_PROFILE.frontendOrigin).port),
    backendPort: Number(new URL(V130_PROFILE.backendOrigin).port),
    accountPrefix: env.E2E_ACCOUNT_PREFIX,
    testRoot,
    outputDir,
    reportDir,
    jsonReport,
    providerStats,
    lastRun,
    artifactRoot,
  };
}
