import { spawn, spawnSync } from "node:child_process";
import { cp, mkdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { computeSourceBuildId } from "../build-id.mjs";

const frontendRoot = path.resolve(import.meta.dirname, "..");
const repositoryRoot = path.resolve(frontendRoot, "..");
const runId = `${new Date().toISOString().replace(/[:.]/g, "-")}-${process.pid}`;
const root = path.join(tmpdir(), `story-v130-rc-v140-${runId}`);
const source = path.join(root, "source");
const artifact = path.join(root, "standalone");
const output = path.join(root, "test-results");
const logs = path.join(root, "logs");
const jsonReport = path.join(root, "playwright-report.json");
const lastRun = path.join(root, "last-run.json");
const frontendOrigin = "http://127.0.0.1:3205";
const backendOrigin = "http://127.0.0.1:8205";
const distDir = ".next-v140-candidate";
const sourceBuildId = await computeSourceBuildId(frontendRoot);
const buildId = `v140-${sourceBuildId.slice(-20)}`;

function cleanEnvironment(extra = {}) {
  const env = { ...process.env };
  for (const name of Object.keys(env)) {
    if (/^(?:CONTINUITY_|SMTP_|RECOVERY_HASH_SECRET$|PUBLIC_RESET_BASE_URL$)/.test(name) || /(?:API_KEY|PASSWORD|TOKEN|SECRET)$/i.test(name)) delete env[name];
  }
  return {
    ...env,
    BACKEND_ORIGIN: backendOrigin,
    PUBLIC_APP_MODE: "0",
    PUBLIC_BASE_URL: frontendOrigin,
    NEXT_DIST_DIR: distDir,
    NEXT_BUILD_ID: buildId,
    E2E_BASE_URL: frontendOrigin,
    E2E_BACKEND_ORIGIN: backendOrigin,
    E2E_ACCOUNT_PREFIX: `v140candidate${process.pid}`,
    E2E_TEST_ROOT: root,
    E2E_OUTPUT_DIR: output,
    E2E_JSON_REPORT: jsonReport,
    ...extra,
  };
}

async function copySource() {
  await mkdir(source, { recursive: true });
  for (const directory of ["app", "public"]) {
    await cp(path.join(frontendRoot, directory), path.join(source, directory), { recursive: true, errorOnExist: true });
  }
  for (const file of ["package.json", "package-lock.json", "next.config.mjs", "tsconfig.json", "next-env.d.ts", "build-id.mjs", "build-origin.mjs", "public-config.mjs"]) {
    await cp(path.join(frontendRoot, file), path.join(source, file), { errorOnExist: true });
  }
  await cp(path.join(frontendRoot, "node_modules"), path.join(source, "node_modules"), { recursive: true, dereference: true, errorOnExist: true });
}

function driveAvailable(letter) {
  return spawnSync("cmd.exe", ["/d", "/s", "/c", `if exist ${letter}\\ (exit 1) else (exit 0)`], { windowsHide: true }).status === 0;
}

function mapDrive(letter, target) {
  const result = spawnSync("subst.exe", [letter, target], { windowsHide: true, encoding: "utf8" });
  if (result.status !== 0) throw new Error(`V140_SUBST_FAILED:${result.stderr}`);
}

function unmapDrive(letter) {
  spawnSync("subst.exe", [letter, "/D"], { windowsHide: true });
}

async function run(command, args, cwd, env, logName) {
  const child = spawn(command, args, { cwd, env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  let combined = "";
  child.stdout.on("data", (chunk) => { combined += chunk; process.stdout.write(chunk); });
  child.stderr.on("data", (chunk) => { combined += chunk; process.stderr.write(chunk); });
  const code = await new Promise((resolve, reject) => { child.once("error", reject); child.once("exit", resolve); });
  await writeFile(path.join(logs, logName), combined, "utf8");
  if (code !== 0) throw new Error(`V140_COMMAND_FAILED:${logName}:${code}`);
}

function start(command, args, cwd, env, logName) {
  const child = spawn(command, args, { cwd, env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  let combined = "";
  child.stdout.on("data", (chunk) => { combined += chunk; process.stdout.write(chunk); });
  child.stderr.on("data", (chunk) => { combined += chunk; process.stderr.write(chunk); });
  child.once("exit", () => { void writeFile(path.join(logs, logName), combined, "utf8"); });
  return child;
}

async function waitFor(url, accepted, timeout = 60_000) {
  const deadline = Date.now() + timeout;
  let last = "not attempted";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { redirect: "manual" });
      if (accepted(response)) return response;
      last = `HTTP ${response.status}`;
    } catch (error) { last = error.message; }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`V140_WAIT_TIMEOUT:${url}:${last}`);
}

async function bootstrapProbe() {
  const response = await waitFor(`${frontendOrigin}/`, (candidate) => candidate.status === 200);
  const html = await response.text();
  const chunks = [...new Set(html.match(/\/_next\/static\/[^"']+\.js/g) ?? [])].slice(0, 4);
  const styles = [...new Set(html.match(/\/_next\/static\/[^"']+\.css(?:\?[^"']*)?/g) ?? [])];
  if (!chunks.length || !styles.length) throw new Error("V140_BOOTSTRAP_ASSET_LIST_EMPTY");
  for (const asset of [...chunks, ...styles]) {
    const assetResponse = await fetch(`${frontendOrigin}${asset}`);
    if (assetResponse.status !== 200) throw new Error(`V140_BOOTSTRAP_ASSET_FAILED:${asset}:${assetResponse.status}`);
  }
  const session = await fetch(`${frontendOrigin}/api/auth/session?optional=true`);
  if (session.status !== 200) throw new Error(`V140_SESSION_BOOTSTRAP_FAILED:${session.status}`);
  await session.json();
  return { html_status: response.status, chunk_count: chunks.length, style_count: styles.length, session_status: session.status };
}

function stop(child) {
  if (child?.pid && child.exitCode == null) child.kill("SIGTERM");
}

await Promise.all([mkdir(output, { recursive: true }), mkdir(logs, { recursive: true })]);
const trackedConfigBefore = {
  next_env: await readFile(path.join(frontendRoot, "next-env.d.ts"), "utf8"),
  tsconfig: await readFile(path.join(frontendRoot, "tsconfig.json"), "utf8"),
};
let backend;
let frontend;
let bootstrap = null;
let provider = null;
let mapped = false;
let status = "failed";
let failure = null;
const drive = "T:";
const startedAt = new Date().toISOString();

try {
  await copySource();
  if (!driveAvailable(drive)) throw new Error("V140_BUILD_DRIVE_IN_USE");
  mapDrive(drive, source);
  mapped = true;
  await run(process.execPath, [`${drive}\\node_modules\\next\\dist\\bin\\next`, "build"], `${drive}\\`, cleanEnvironment({ NODE_ENV: "production" }), "build.log");
  unmapDrive(drive);
  mapped = false;

  const dist = path.join(source, distDir);
  const standalone = path.join(dist, "standalone");
  await stat(path.join(standalone, "server.js"));
  await cp(standalone, artifact, { recursive: true, errorOnExist: true });
  await cp(path.join(source, "public"), path.join(artifact, "public"), { recursive: true, errorOnExist: true });
  await mkdir(path.join(artifact, distDir), { recursive: true });
  await cp(path.join(dist, "static"), path.join(artifact, distDir, "static"), { recursive: true, errorOnExist: true });

  const python = path.join(repositoryRoot, ".venv", "Scripts", "python.exe");
  await stat(python);
  backend = start(python, ["-m", "uvicorn", "tests.e2e_app:app", "--host", "127.0.0.1", "--port", "8205"], path.join(repositoryRoot, "backend"), cleanEnvironment({
    TRUSTED_HOSTS: "127.0.0.1:8205",
    TRUSTED_ORIGINS: frontendOrigin,
    SCC_DISABLE_DEFAULT_APP: "1",
  }), "backend.log");
  await waitFor(`${backendOrigin}/health`, (response) => response.status === 200);
  frontend = start(process.execPath, [path.join(artifact, "server.js")], artifact, cleanEnvironment({ HOSTNAME: "127.0.0.1", PORT: "3205", NODE_ENV: "production" }), "frontend.log");
  bootstrap = await bootstrapProbe();

  await run(process.execPath, [path.join(frontendRoot, "node_modules", "@playwright", "test", "cli.js"), "test", "--config", "playwright.v140.config.ts"], frontendRoot, cleanEnvironment(), "playwright.log");
  const statsResponse = await fetch(`${frontendOrigin}/api/test/stage12/stats`);
  if (statsResponse.status !== 200) throw new Error(`V140_PROVIDER_STATS_FAILED:${statsResponse.status}`);
  provider = await statsResponse.json();
  if (provider.provider_http_calls !== 0 || provider.external_provider_http_enabled !== false) throw new Error("V140_EXTERNAL_PROVIDER_ACTIVITY");
  status = "passed";
} catch (error) {
  failure = { name: error.name, message: error.message, stack: error.stack };
  process.exitCode = 1;
} finally {
  stop(frontend);
  stop(backend);
  if (mapped) unmapDrive(drive);
  const trackedConfigAfter = {
    next_env: await readFile(path.join(frontendRoot, "next-env.d.ts"), "utf8"),
    tsconfig: await readFile(path.join(frontendRoot, "tsconfig.json"), "utf8"),
  };
  if (trackedConfigBefore.next_env !== trackedConfigAfter.next_env || trackedConfigBefore.tsconfig !== trackedConfigAfter.tsconfig) {
    status = "failed";
    failure ??= { name: "Error", message: "V140_SOURCE_CONFIG_CHANGED" };
    process.exitCode = 1;
  }
  const record = {
    product_version: "1.4.0-frontend-candidate",
    status,
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    source_build_id: sourceBuildId,
    production_build_id: buildId,
    baseline_git_head: "ce5b717034e7e83c498622356e7250dde53054da",
    ports: { frontend: 3205, backend: 8205 },
    test_root: root,
    artifact_root: artifact,
    bootstrap,
    provider,
    tracked_source_config_unchanged: trackedConfigBefore.next_env === trackedConfigAfter.next_env && trackedConfigBefore.tsconfig === trackedConfigAfter.tsconfig,
    failure,
  };
  await writeFile(lastRun, `${JSON.stringify(record, null, 2)}\n`, "utf8");
  await rm(path.join(source, "node_modules"), { recursive: true, force: true }).catch(() => {});
  process.stdout.write(`\nV140_LAST_RUN=${lastRun}\nV140_OUTPUT=${output}\nV140_ARTIFACT=${artifact}\n`);
}
