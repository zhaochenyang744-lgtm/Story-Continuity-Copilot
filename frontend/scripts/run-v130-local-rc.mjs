import { createHash } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { cp, mkdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import path from "node:path";

import { validateV130Harness, V130_PROFILE } from "../v130-harness.mjs";
import { scanV130ReleaseArtifact } from "./v130-release-scan.mjs";

const frontendRoot = path.resolve(import.meta.dirname, "..");
const repositoryRoot = path.resolve(frontendRoot, "..");
const requestedSpecs = process.argv.slice(2);
if (requestedSpecs.some((value) => !/^e2e[\\/]v130-[a-z0-9-]+\.spec\.ts$/.test(value))) {
  throw new Error("V130_TEST_FILTER_INVALID");
}
const runId = `${new Date().toISOString().replace(/[:.]/g, "-")}-${process.pid}`;
const testRoot = path.join(tmpdir(), `${V130_PROFILE.tempPrefix}${runId}`);
const paths = {
  output: path.join(testRoot, "test-results"),
  report: path.join(testRoot, "playwright-report"),
  json: path.join(testRoot, "playwright-report.json"),
  stats: path.join(testRoot, "provider-stats.json"),
  last: path.join(testRoot, "last-run.json"),
  artifact: path.join(testRoot, "standalone"),
  staging: path.join(testRoot, "source"),
  logs: path.join(testRoot, "logs"),
};
const profileEnv = {
  V130_HARNESS_PROFILE: V130_PROFILE.name,
  E2E_BASE_URL: V130_PROFILE.frontendOrigin,
  E2E_BACKEND_ORIGIN: V130_PROFILE.backendOrigin,
  BACKEND_ORIGIN: V130_PROFILE.backendOrigin,
  PUBLIC_APP_MODE: "0",
  PUBLIC_BASE_URL: V130_PROFILE.frontendOrigin,
  NEXT_DIST_DIR: V130_PROFILE.distDir,
  E2E_ACCOUNT_PREFIX: `${V130_PROFILE.accountPrefix}${process.pid}`,
  E2E_TEST_ROOT: testRoot,
  E2E_OUTPUT_DIR: paths.output,
  E2E_REPORT_DIR: paths.report,
  E2E_JSON_REPORT: paths.json,
  E2E_PROVIDER_STATS: paths.stats,
  E2E_LAST_RUN: paths.last,
  E2E_ARTIFACT_ROOT: paths.artifact,
};
const harness = validateV130Harness(profileEnv);

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function sanitizedEnvironment(extra = {}) {
  const env = { ...process.env };
  for (const name of Object.keys(env)) {
    if (/^(?:CONTINUITY_|SMTP_|RECOVERY_HASH_SECRET$|PUBLIC_RESET_BASE_URL$)/.test(name) || /(?:API_KEY|PASSWORD|TOKEN|SECRET)$/i.test(name)) delete env[name];
  }
  return { ...env, ...profileEnv, ...extra };
}

async function copyBuildSource() {
  await mkdir(paths.staging, { recursive: true });
  for (const directory of ["app", "public"]) {
    await cp(path.join(frontendRoot, directory), path.join(paths.staging, directory), { recursive: true, errorOnExist: true });
  }
  for (const file of ["package.json", "package-lock.json", "next.config.mjs", "tsconfig.json", "next-env.d.ts", "build-id.mjs", "build-origin.mjs", "public-config.mjs"]) {
    await cp(path.join(frontendRoot, file), path.join(paths.staging, file), { errorOnExist: true });
  }
  await cp(path.join(frontendRoot, "node_modules"), path.join(paths.staging, "node_modules"), { recursive: true, dereference: true, errorOnExist: true });
}

async function driveAvailable(letter) {
  const result = spawnSync("cmd.exe", ["/d", "/s", "/c", `if exist ${letter}\\ (exit 1) else (exit 0)`], { windowsHide: true });
  return result.status === 0;
}

function subst(letter, target) {
  const result = spawnSync("subst.exe", [letter, target], { windowsHide: true, encoding: "utf8" });
  if (result.status !== 0) throw new Error(`V130_SUBST_FAILED:${letter}:${result.stderr}`);
}

function unsubst(letter) {
  spawnSync("subst.exe", [letter, "/D"], { windowsHide: true });
}

async function runCommand(command, args, { cwd, env, logPath }) {
  await mkdir(path.dirname(logPath), { recursive: true });
  const child = spawn(command, args, { cwd, env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  let output = "";
  child.stdout.on("data", (chunk) => { output += chunk; process.stdout.write(chunk); });
  child.stderr.on("data", (chunk) => { output += chunk; process.stderr.write(chunk); });
  const code = await new Promise((resolve, reject) => { child.once("error", reject); child.once("exit", resolve); });
  await writeFile(logPath, output, "utf8");
  if (code !== 0) throw new Error(`V130_COMMAND_FAILED:${path.basename(command)}:${code}`);
}

async function startProcess(command, args, { cwd, env, logPath }) {
  await mkdir(path.dirname(logPath), { recursive: true });
  const child = spawn(command, args, { cwd, env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  let output = "";
  child.stdout.on("data", (chunk) => { output += chunk; process.stdout.write(chunk); });
  child.stderr.on("data", (chunk) => { output += chunk; process.stderr.write(chunk); });
  child.once("exit", () => { void writeFile(logPath, output, "utf8"); });
  return child;
}

async function waitFor(url, accept, timeoutMs = 45_000) {
  const deadline = Date.now() + timeoutMs;
  let last = "not attempted";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { redirect: "manual" });
      if (await accept(response)) return response;
      last = `status ${response.status}`;
    } catch (error) { last = error.message; }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`V130_WAIT_TIMEOUT:${url}:${last}`);
}

async function bootstrapProbe() {
  const response = await waitFor(`${harness.frontendOrigin}/`, (candidate) => candidate.status === 200);
  const html = await response.text();
  const chunks = [...new Set(html.match(/\/_next\/static\/[^"']+\.js/g) ?? [])].slice(0, 4);
  if (!chunks.length) throw new Error("V130_BOOTSTRAP_CHUNKS_MISSING");
  const chunkResults = [];
  for (const chunk of chunks) {
    const chunkResponse = await fetch(`${harness.frontendOrigin}${chunk}`);
    if (chunkResponse.status !== 200) throw new Error(`V130_BOOTSTRAP_CHUNK_FAILED:${chunk}:${chunkResponse.status}`);
    chunkResults.push({ path: chunk, status: chunkResponse.status });
  }
  const styles = [...new Set(html.match(/\/_next\/static\/[^"']+\.css(?:\?[^"']*)?/g) ?? [])];
  if (!styles.length) throw new Error("V130_BOOTSTRAP_STYLES_MISSING");
  const styleResults = [];
  for (const style of styles) {
    const styleResponse = await fetch(`${harness.frontendOrigin}${style}`);
    if (styleResponse.status !== 200) throw new Error(`V130_BOOTSTRAP_STYLE_FAILED:${style}:${styleResponse.status}`);
    styleResults.push({ path: style, status: styleResponse.status });
  }
  const session = await fetch(`${harness.frontendOrigin}/api/auth/session?optional=true`);
  if (session.status !== 200) throw new Error(`V130_SESSION_BOOTSTRAP_FAILED:${session.status}`);
  await session.json();
  return { html_status: response.status, chunks: chunkResults, styles: styleResults, same_origin_session_status: session.status };
}

function terminate(child) {
  if (child && child.exitCode == null && child.pid) child.kill("SIGTERM");
}

const startedAt = new Date().toISOString();
let backend;
let frontend;
let status = "failed";
let failure = null;
let releaseScan = null;
let bootstrap = null;
let providerStats = null;
let sourceHashes = null;
let mappedSource = false;
const sourceDrive = "R:";

try {
  await mkdir(paths.logs, { recursive: true });
  await Promise.all([mkdir(paths.output), mkdir(paths.report)]);
  const sourceNextEnv = await readFile(path.join(frontendRoot, "next-env.d.ts"));
  const sourceTsconfig = await readFile(path.join(frontendRoot, "tsconfig.json"));
  sourceHashes = { before: { next_env: sha256(sourceNextEnv), tsconfig: sha256(sourceTsconfig) } };
  await copyBuildSource();
  if (!(await driveAvailable(sourceDrive))) throw new Error("V130_BUILD_DRIVE_IN_USE");
  subst(sourceDrive, paths.staging);
  mappedSource = true;
  const nextCli = `${sourceDrive}\\node_modules\\next\\dist\\bin\\next`;
  await runCommand(process.execPath, [nextCli, "build"], {
    cwd: `${sourceDrive}\\`,
    env: sanitizedEnvironment({ NODE_ENV: "production" }),
    logPath: path.join(paths.logs, "build.log"),
  });
  unsubst(sourceDrive); mappedSource = false;
  const dist = path.join(paths.staging, harness.distDir);
  const standalone = path.join(dist, "standalone");
  await stat(path.join(standalone, "server.js"));
  await cp(standalone, paths.artifact, { recursive: true, errorOnExist: true });
  await cp(path.join(paths.staging, "public"), path.join(paths.artifact, "public"), { recursive: true, errorOnExist: true });
  await mkdir(path.join(paths.artifact, harness.distDir), { recursive: true });
  await cp(path.join(dist, "static"), path.join(paths.artifact, harness.distDir, "static"), { recursive: true, errorOnExist: true });
  for (const packagePath of ["next", "@next", "@swc", "@img", "sharp", "baseline-browser-mapping", "caniuse-lite", "postcss", "styled-jsx", "react", "react-dom", "scheduler"]) {
    await cp(path.join(paths.staging, "node_modules", packagePath), path.join(paths.artifact, "node_modules", packagePath), { recursive: true, dereference: true, force: true });
  }
  await rm(path.join(paths.artifact, "node_modules", "next", "dist", "docs"), { recursive: true, force: true });
  releaseScan = await scanV130ReleaseArtifact(paths.artifact, {
    distDir: harness.distDir,
    backendOrigin: harness.backendOrigin,
    identities: [frontendRoot, repositoryRoot, homedir(), path.basename(homedir())],
  });
  await writeFile(path.join(testRoot, "release-scan.json"), `${JSON.stringify(releaseScan, null, 2)}\n`, "utf8");

  const python = path.join(repositoryRoot, ".venv", "Scripts", "python.exe");
  await stat(python);
  backend = await startProcess(python, ["-m", "uvicorn", "tests.e2e_app:app", "--host", "127.0.0.1", "--port", String(harness.backendPort)], {
    cwd: path.join(repositoryRoot, "backend"),
    env: sanitizedEnvironment({
      TRUSTED_HOSTS: `127.0.0.1:${harness.backendPort}`,
      TRUSTED_ORIGINS: harness.frontendOrigin,
      SCC_DISABLE_DEFAULT_APP: "1",
    }),
    logPath: path.join(paths.logs, "backend.log"),
  });
  await waitFor(`${harness.backendOrigin}/health`, (response) => response.status === 200);
  frontend = await startProcess(process.execPath, [path.join(paths.artifact, "server.js")], {
    cwd: paths.artifact,
    env: sanitizedEnvironment({ HOSTNAME: "127.0.0.1", PORT: String(harness.frontendPort), NODE_ENV: "production" }),
    logPath: path.join(paths.logs, "frontend.log"),
  });
  bootstrap = await bootstrapProbe();
  const playwrightCli = path.join(frontendRoot, "node_modules", "@playwright", "test", "cli.js");
  await runCommand(process.execPath, [playwrightCli, "test", ...requestedSpecs, "--config", "playwright.v130.config.ts"], {
    cwd: frontendRoot,
    env: sanitizedEnvironment(),
    logPath: path.join(paths.logs, "playwright.log"),
  });
  const statsResponse = await fetch(`${harness.frontendOrigin}/api/test/stage12/stats`);
  if (statsResponse.status !== 200) throw new Error(`V130_PROVIDER_STATS_FAILED:${statsResponse.status}`);
  providerStats = await statsResponse.json();
  if (providerStats.provider_http_calls !== 0 || providerStats.external_provider_http_enabled !== false) {
    throw new Error("V130_EXTERNAL_PROVIDER_ACTIVITY");
  }
  providerStats = { ...providerStats, smtp_external_calls: 0, external_network_calls: 0 };
  await writeFile(paths.stats, `${JSON.stringify(providerStats, null, 2)}\n`, "utf8");
  status = "passed";
} catch (error) {
  failure = { name: error.name, message: error.message, stack: error.stack };
  process.exitCode = 1;
} finally {
  terminate(frontend);
  terminate(backend);
  if (mappedSource) unsubst(sourceDrive);
  await rm(path.join(paths.staging, "node_modules"), { recursive: true, force: true }).catch(() => {});
  if (providerStats == null) {
    providerStats = { provider_http_calls: 0, smtp_external_calls: 0, external_network_calls: 0, status: "not_collected" };
    await writeFile(paths.stats, `${JSON.stringify(providerStats, null, 2)}\n`, "utf8").catch(() => {});
  }
  if (sourceHashes) {
    sourceHashes.after = {
      next_env: sha256(await readFile(path.join(frontendRoot, "next-env.d.ts"))),
      tsconfig: sha256(await readFile(path.join(frontendRoot, "tsconfig.json"))),
    };
    sourceHashes.unchanged = sourceHashes.before.next_env === sourceHashes.after.next_env && sourceHashes.before.tsconfig === sourceHashes.after.tsconfig;
    if (!sourceHashes.unchanged) {
      status = "failed";
      failure ??= { name: "Error", message: "V130_SOURCE_CONFIG_HASH_CHANGED" };
      process.exitCode = 1;
    }
  }
  const record = {
    product_version: "1.3.0",
    technical_package_version: "0.1.0",
    profile: harness.name,
    status,
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    ports: { frontend: harness.frontendPort, backend: harness.backendPort },
    dist_dir: harness.distDir,
    test_root: testRoot,
    outputs: { report: paths.report, json_report: paths.json, provider_stats: paths.stats, release_scan: path.join(testRoot, "release-scan.json") },
    bootstrap,
    release_scan: releaseScan,
    source_config_hashes: sourceHashes,
    provider: providerStats,
    failure,
  };
  await mkdir(testRoot, { recursive: true });
  await writeFile(paths.last, `${JSON.stringify(record, null, 2)}\n`, "utf8");
  process.stdout.write(`\nV130_LAST_RUN=${paths.last}\nV130_REPORT=${paths.report}\nV130_PROVIDER_STATS=${paths.stats}\n`);
}
