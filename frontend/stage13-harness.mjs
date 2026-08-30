import path from "node:path";
import { tmpdir } from "node:os";

const profiles = Object.freeze({
  impl: Object.freeze({
    frontendOrigin: "http://127.0.0.1:3080",
    backendOrigin: "http://127.0.0.1:8080",
    distDir: ".next-stage13-impl",
    tempPrefix: "story-stage13-impl-",
    accountPrefix: "stage13impl",
  }),
  pm3: Object.freeze({
    frontendOrigin: "http://127.0.0.1:3081",
    backendOrigin: "http://127.0.0.1:8081",
    distDir: ".next-stage13-pm3",
    tempPrefix: "story-stage13-pm3-",
    accountPrefix: "stage13pm3",
  }),
  v4impl: Object.freeze({
    frontendOrigin: "http://127.0.0.1:3084",
    backendOrigin: "http://127.0.0.1:8084",
    distDir: ".next-stage13-v4-impl",
    tempPrefix: "story-stage13-v4-impl-",
    accountPrefix: "stage13v4impl",
  }),
  v4pm3: Object.freeze({
    frontendOrigin: "http://127.0.0.1:3085",
    backendOrigin: "http://127.0.0.1:8085",
    distDir: ".next-stage13-v4-pm3",
    tempPrefix: "story-stage13-v4-pm3-",
    accountPrefix: "stage13v4pm3",
  }),
});

function isolatedPath(value, profile, name, { root } = {}) {
  if (!value) throw new Error(`${name}_REQUIRED`);
  const resolved = path.resolve(value);
  const relativeToTemp = path.relative(path.resolve(tmpdir()), resolved);
  if (!relativeToTemp || relativeToTemp.startsWith("..") || path.isAbsolute(relativeToTemp)) {
    throw new Error(`${name}_OUTSIDE_SYSTEM_TEMP`);
  }
  if (!resolved.split(path.sep).some((part) => part.startsWith(profile.tempPrefix))) {
    throw new Error(`${name}_PROFILE_MISMATCH`);
  }
  if (root) {
    const relativeToRoot = path.relative(root, resolved);
    if (relativeToRoot.startsWith("..") || path.isAbsolute(relativeToRoot)) {
      throw new Error(`${name}_OUTSIDE_TEST_ROOT`);
    }
  }
  return resolved;
}

export function validateStage13Harness(env) {
  const profileName = env.STAGE13_HARNESS_PROFILE;
  const profile = profiles[profileName];
  if (!profile) throw new Error("STAGE13_HARNESS_PROFILE_INVALID");
  const exact = {
    E2E_BASE_URL: profile.frontendOrigin,
    E2E_BACKEND_ORIGIN: profile.backendOrigin,
    BACKEND_ORIGIN: profile.backendOrigin,
    PUBLIC_APP_MODE: "0",
    PUBLIC_BASE_URL: profile.frontendOrigin,
    NEXT_DIST_DIR: profile.distDir,
  };
  for (const [name, expected] of Object.entries(exact)) {
    if (env[name] !== expected) throw new Error(`${name}_PROFILE_MISMATCH`);
  }
  if (!env.E2E_ACCOUNT_PREFIX?.startsWith(profile.accountPrefix)) {
    throw new Error("E2E_ACCOUNT_PREFIX_PROFILE_MISMATCH");
  }
  const testRoot = isolatedPath(env.E2E_TEST_ROOT, profile, "E2E_TEST_ROOT");
  const outputDir = isolatedPath(env.E2E_OUTPUT_DIR, profile, "E2E_OUTPUT_DIR", { root: testRoot });
  return {
    profileName,
    ...profile,
    frontendPort: Number(new URL(profile.frontendOrigin).port),
    backendPort: Number(new URL(profile.backendOrigin).port),
    accountPrefix: env.E2E_ACCOUNT_PREFIX,
    testRoot,
    outputDir,
  };
}
