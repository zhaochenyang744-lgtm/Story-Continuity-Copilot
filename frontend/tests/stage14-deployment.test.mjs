import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import {
  assertPortableBundleBytes,
  assertPortableBundlePath,
  scanDeployableBytes,
  validateStage14PlatformMetadata,
} from "../scripts/stage14-bundle-scan.mjs";

const repositoryRoot = path.resolve(import.meta.dirname, "..", "..");
const deploymentRoot = path.join(repositoryRoot, "deployment");

async function deploymentFile(name) {
  return readFile(path.join(deploymentRoot, name), "utf8");
}

test("deployment contract freezes one backend worker, persistent volumes, health checks, and root-owned file secrets", async () => {
  const compose = await deploymentFile("compose.yaml");
  const backend = await deploymentFile("Dockerfile.backend");
  const entrypoint = await deploymentFile("backend-entrypoint.sh");
  const secretCheck = await deploymentFile("secret-dir-check.sh");
  const deployEnvironment = await deploymentFile("deploy.env.example");
  assert.match(compose, /WEB_CONCURRENCY: "1"/);
  assert.match(compose, /SINGLE_INSTANCE: "1"/);
  assert.match(compose, /SQLITE_PERSISTENT_VOLUME: "1"/);
  assert.match(compose, /story_runtime:\/app\/runtime/);
  assert.equal((compose.match(/context: \.\./g) || []).length, 2);
  assert.doesNotMatch(compose, /^\s+context: \.\s*$/m);
  assert.match(compose, /\.\/Caddyfile:\/etc\/caddy\/Caddyfile:ro/);
  assert.doesNotMatch(compose, /\.\/deployment\/Caddyfile/);
  assert.match(compose, /condition: service_healthy/);
  assert.match(compose, /\$\{SCC_SECRET_DIR:\?secret directory required\}:\/run\/secrets:ro/);
  assert.equal((compose.match(/replicas: 1/g) || []).length, 2);
  assert.match(backend, /"--workers", "1"/);
  assert.match(backend, /apt-get install -y --no-install-recommends gosu/);
  assert.doesNotMatch(backend, /^USER /m);
  assert.match(entrypoint, /gosu continuity python -m app\.deployment migrate/);
  assert.match(entrypoint, /exec gosu continuity "\$@"/);
  assert.match(secretCheck, /stat -c '%u'/);
  assert.match(secretCheck, /stat -c '%g'/);
  assert.match(secretCheck, /stat -c '%a'/);
  assert.match(secretCheck, /!= "0"/);
  assert.match(secretCheck, /!= "700"/);
  assert.match(secretCheck, /!= "600"/);
  assert.match(deployEnvironment, /SCC_SECRET_DIR=\/etc\/story-continuity\/secrets/);
  const backendEnvironment = compose.split("    environment:\n", 2)[1].split("    volumes:\n", 1)[0];
  assert.doesNotMatch(backendEnvironment, /CONTINUITY_API_KEY/);
  assert.doesNotMatch(backendEnvironment, /SMTP_PASSWORD/);
});

test("canonical HTTPS proxy exposes public health while keeping the API same-origin", async () => {
  const compose = await deploymentFile("compose.yaml");
  const caddy = await deploymentFile("Caddyfile");
  assert.match(compose, /PUBLIC_BASE_URL: https:\/\/\$\{PUBLIC_HOST/);
  assert.match(compose, /BACKEND_ORIGIN: http:\/\/backend:8000/);
  assert.match(compose, /CONTINUITY_MODEL: deepseek-v4-pro/);
  assert.match(caddy, /handle \/health/);
  assert.match(caddy, /handle \/readiness/);
  assert.match(caddy, /reverse_proxy frontend:3000/);
  const backendService = compose.split("  backend:\n", 2)[1].split("\n  frontend:\n", 1)[0];
  const frontendService = compose.split("  frontend:\n", 2)[1].split("\n  caddy:\n", 1)[0];
  const caddyService = compose.split("  caddy:\n", 2)[1].split("\nvolumes:\n", 1)[0];
  assert.doesNotMatch(backendService, /^    ports:/m);
  assert.doesNotMatch(frontendService, /^    ports:/m);
  assert.match(caddyService, /"80:80"/);
  assert.match(caddyService, /"443:443"/);
  assert.doesNotMatch(compose, /"(?:3000|8000):(?:3000|8000)"/);
});

test("release and rollback require a backup and never restore implicitly", async () => {
  const release = await deploymentFile("release.sh");
  const rollback = await deploymentFile("rollback.sh");
  const restore = await deploymentFile("restore.sh");
  assert.match(release, /app\.deployment backup/);
  assert.match(rollback, /app\.deployment backup/);
  assert.doesNotMatch(rollback, /app\.deployment restore/);
  assert.match(restore, /APPLICATION_STOPPED/);
  assert.match(restore, /app\.deployment restore/);
  assert.match(release, /secret-dir-check\.sh/);
  assert.match(rollback, /secret-dir-check\.sh/);
  assert.match(restore, /secret-dir-check\.sh/);
});

test("deployment scanner rejects identity, private paths, email, and secret values", () => {
  assert.throws(() => scanDeployableBytes(Buffer.from("story-continuity-web-demo")), /LEVEL1_HIT/);
  assert.throws(() => scanDeployableBytes(Buffer.from(String.raw`C:\Users\private\file.txt`)), /ABSOLUTE_PATH_HIT/);
  assert.throws(() => scanDeployableBytes(Buffer.from("person@example.test")), /EMAIL_HIT/);
  assert.throws(() => scanDeployableBytes(Buffer.from("opaque-secret"), [], ["opaque-secret"]), /SECRET_HIT/);
  assert.throws(() => scanDeployableBytes(Buffer.from(`#token=${"a".repeat(48)}`)), /LEVEL0_HIT/);
  assert.doesNotThrow(() => scanDeployableBytes(Buffer.from("CONTINUITY_API_KEY=/run/secrets/CONTINUITY_API_KEY")));
  assert.doesNotThrow(() => scanDeployableBytes(Buffer.from("return `${base}/reset#token=${raw}`")));
});

test("source bundle, Dockerfile, dockerignore, and compose freeze one Linux build contract", async () => {
  const bundleScript = await readFile(path.join(repositoryRoot, "frontend", "scripts", "stage14-bundle.ps1"), "utf8");
  const dockerfile = await deploymentFile("Dockerfile.frontend");
  const dockerignore = await deploymentFile(".dockerignore");
  const compose = await deploymentFile("compose.yaml");
  const verifier = await deploymentFile("verify-frontend-image.sh");
  assert.match(bundleScript, /New-Item[^\n]+"frontend-source"/);
  for (const required of ["package.json", "package-lock.json", "next.config.mjs", "tsconfig.json", "build-id.mjs", "build-origin.mjs", "public-config.mjs", "next-env.d.ts"]) {
    assert.match(bundleScript, new RegExp(required.replace(".", "\\.")));
  }
  assert.match(bundleScript, /Join-Path \$frontend "app"/);
  assert.doesNotMatch(bundleScript, /stage14-build\.ps1|frontend-artifact/);
  assert.equal((dockerfile.match(/^FROM --platform=linux\/amd64 node:[^\s]+-alpine[^\s]* AS /gm) || []).length, 3);
  assert.match(dockerfile, /COPY frontend-source\/package\.json frontend-source\/package-lock\.json \.\//);
  assert.match(dockerfile, /RUN npm ci/);
  assert.match(dockerfile, /COPY frontend-source\/ \.\//);
  assert.match(dockerfile, /npm run build/);
  assert.doesNotMatch(dockerfile, /frontend-artifact/);
  assert.match(dockerignore, /^!frontend-source\/$/m);
  assert.match(dockerignore, /^!frontend-source\/\*\*$/m);
  assert.doesNotMatch(dockerignore, /frontend-artifact/);
  const frontendService = compose.split("\n  frontend:\n", 2)[1].split("\n  caddy:\n", 1)[0];
  assert.match(frontendService, /args:\s*\n\s+PUBLIC_BASE_URL: https:\/\/\$\{PUBLIC_HOST:\?public host required\}/);
  assert.match(verifier, /linux\/amd64/);
  assert.match(verifier, /linux\/x64/);
  assert.match(verifier, /musl/);
  assert.match(verifier, /sharp-linuxmusl-x64/);
  assert.match(verifier, /7f454c46/);
});

test("portable source gate rejects prebuilt trees, native files, PE, ELF, Mach-O, and target mismatch", () => {
  assert.throws(() => assertPortableBundlePath("frontend-artifact/server.js"), /PREBUILT_FRONTEND_FORBIDDEN/);
  assert.throws(() => assertPortableBundlePath("frontend-source/node_modules/@img/sharp-win32-x64/sharp.node"), /PREBUILT_FRONTEND_FORBIDDEN/);
  assert.throws(() => assertPortableBundlePath("frontend-source/app/addon.node"), /NATIVE_FILE_FORBIDDEN/);
  assert.throws(() => assertPortableBundlePath("frontend-source/app/windows-helper.ts"), /WINDOWS_PATH_FORBIDDEN/);
  assert.throws(() => assertPortableBundlePath("frontend-source/tests/deployment.test.mjs"), /CONTROL_FILE_FORBIDDEN/);
  assert.throws(() => assertPortableBundlePath("frontend-source/AGENTS.md"), /CONTROL_FILE_FORBIDDEN/);
  assert.throws(() => assertPortableBundlePath("frontend-source/.env.production"), /CONTROL_FILE_FORBIDDEN/);
  assert.throws(() => assertPortableBundleBytes(Buffer.from([0x4d, 0x5a, 0x90, 0x00])), /PE_BINARY_FORBIDDEN/);
  assert.throws(() => assertPortableBundleBytes(Buffer.from([0x7f, 0x45, 0x4c, 0x46])), /ELF_BINARY_FORBIDDEN/);
  assert.throws(() => assertPortableBundleBytes(Buffer.from([0xfe, 0xed, 0xfa, 0xcf])), /MACHO_BINARY_FORBIDDEN/);
  assert.doesNotThrow(() => {
    assertPortableBundlePath("frontend-source/package-lock.json");
    assertPortableBundleBytes(Buffer.from('{"optional":"@img/sharp-win32-x64"}'));
    scanDeployableBytes(Buffer.from('{"optional":"@img/sharp-win32-x64"}'));
  });
  const valid = {
    profile: "stage14impl",
    publicBaseUrl: "https://43-160-207-57.sslip.io",
    backendOrigin: "http://backend:8000",
    targetOs: "linux",
    targetArch: "amd64",
    targetLibc: "musl",
    frontendBuild: "docker-multistage-source",
  };
  assert.doesNotThrow(() => validateStage14PlatformMetadata(valid, "stage14impl"));
  for (const [key, value] of [["targetOs", "windows"], ["targetArch", "arm64"], ["targetLibc", "glibc"]]) {
    assert.throws(() => validateStage14PlatformMetadata({ ...valid, [key]: value }, "stage14impl"), /PLATFORM_METADATA_MISMATCH/);
  }
});
