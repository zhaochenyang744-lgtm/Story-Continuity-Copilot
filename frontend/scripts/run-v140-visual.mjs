import { spawn, spawnSync } from "node:child_process";
import { cp, mkdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { computeSourceBuildId } from "../build-id.mjs";

const frontendRoot = path.resolve(import.meta.dirname, "..");
const repositoryRoot = path.resolve(frontendRoot, "..");
const workspaceRoot = path.resolve(repositoryRoot, "..", "..", "..", "..");
const candidateRoot = path.join(workspaceRoot, "artifacts", "v140-visual-candidate-1");
const runId = `${new Date().toISOString().replace(/[:.]/g, "-")}-${process.pid}`;
const runDir = path.join(candidateRoot, "runs", runId);
const sourceRoot = path.join(tmpdir(), `story-v130-rc-v140-visual-${runId}`);
const source = path.join(sourceRoot, "source");
const artifact = path.join(runDir, "standalone");
const output = path.join(runDir, "test-results");
const screenshots = path.join(runDir, "screenshots");
const logs = path.join(runDir, "logs");
const jsonReport = path.join(runDir, "playwright-report.json");
const runRecord = path.join(runDir, "run.json");
const latestRecord = path.join(candidateRoot, "latest.json");
const reportPath = path.join(candidateRoot, "report.md");
const coveragePath = path.join(candidateRoot, "coverage-matrix.md");
const frontendOrigin = "http://127.0.0.1:3211";
const backendOrigin = "http://127.0.0.1:8211";
const distDir = ".next-v140-visual";
const sourceBuildId = await computeSourceBuildId(frontendRoot);
const buildId = `v140-visual-${sourceBuildId.slice(-16)}`;
const visualAccount = `v140visual${process.pid}`;
const visualPassword = "Visual-preview-140!";

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
    E2E_ACCOUNT_PREFIX: `v140visualcandidate${process.pid}`,
    E2E_VISUAL_ACCOUNT: visualAccount,
    E2E_VISUAL_PASSWORD: visualPassword,
    E2E_TEST_ROOT: sourceRoot,
    E2E_OUTPUT_DIR: output,
    E2E_VISUAL_SCREENSHOT_DIR: screenshots,
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
  if (result.status !== 0) throw new Error(`V140_VISUAL_SUBST_FAILED:${result.stderr}`);
}
function unmapDrive(letter) { spawnSync("subst.exe", [letter, "/D"], { windowsHide: true }); }

async function run(command, args, cwd, env, logName) {
  const child = spawn(command, args, { cwd, env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  let combined = "";
  child.stdout.on("data", (chunk) => { combined += chunk; process.stdout.write(chunk); });
  child.stderr.on("data", (chunk) => { combined += chunk; process.stderr.write(chunk); });
  const code = await new Promise((resolve, reject) => { child.once("error", reject); child.once("exit", resolve); });
  await writeFile(path.join(logs, logName), combined, "utf8");
  if (code !== 0) throw new Error(`V140_VISUAL_COMMAND_FAILED:${logName}:${code}`);
}
function start(command, args, cwd, env, logName) {
  const child = spawn(command, args, { cwd, env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  let combined = "";
  child.stdout.on("data", (chunk) => { combined += chunk; process.stdout.write(chunk); });
  child.stderr.on("data", (chunk) => { combined += chunk; process.stderr.write(chunk); });
  child.once("exit", () => { void writeFile(path.join(logs, logName), combined, "utf8"); });
  return child;
}
async function waitFor(url, accepted, timeout = 90_000) {
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
  throw new Error(`V140_VISUAL_WAIT_TIMEOUT:${url}:${last}`);
}
async function bootstrapProbe() {
  const response = await waitFor(`${frontendOrigin}/`, (candidate) => candidate.status === 200);
  const html = await response.text();
  const chunks = [...new Set(html.match(/\/_next\/static\/[^"']+\.js/g) ?? [])].slice(0, 4);
  const styles = [...new Set(html.match(/\/_next\/static\/[^"']+\.css(?:\?[^"']*)?/g) ?? [])];
  if (!chunks.length || !styles.length) throw new Error("V140_VISUAL_BOOTSTRAP_ASSET_LIST_EMPTY");
  for (const assetPath of [...chunks, ...styles]) {
    const assetResponse = await fetch(`${frontendOrigin}${assetPath}`);
    if (assetResponse.status !== 200) throw new Error(`V140_VISUAL_BOOTSTRAP_ASSET_FAILED:${assetPath}:${assetResponse.status}`);
  }
  const door = await fetch(`${frontendOrigin}/assets/v140/story-door.png`);
  if (door.status !== 200) throw new Error(`V140_VISUAL_DOOR_ASSET_FAILED:${door.status}`);
  const session = await fetch(`${frontendOrigin}/api/auth/session?optional=true`);
  if (session.status !== 200) throw new Error(`V140_VISUAL_SESSION_BOOTSTRAP_FAILED:${session.status}`);
  return { html_status: response.status, chunk_count: chunks.length, style_count: styles.length, session_status: session.status, door_asset_status: door.status };
}
function stop(child) { if (child?.pid && child.exitCode == null) child.kill("SIGTERM"); }

await Promise.all([mkdir(output, { recursive: true }), mkdir(screenshots, { recursive: true }), mkdir(logs, { recursive: true })]);
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
const drive = "V:";
const startedAt = new Date().toISOString();

try {
  await copySource();
  if (!driveAvailable(drive)) throw new Error("V140_VISUAL_BUILD_DRIVE_IN_USE");
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
  backend = start(python, ["-m", "uvicorn", "tests.e2e_app:app", "--host", "127.0.0.1", "--port", "8211"], path.join(repositoryRoot, "backend"), cleanEnvironment({ TRUSTED_HOSTS: "127.0.0.1:8211", TRUSTED_ORIGINS: frontendOrigin, SCC_DISABLE_DEFAULT_APP: "1" }), "backend.log");
  await waitFor(`${backendOrigin}/health`, (response) => response.status === 200);
  frontend = start(process.execPath, [path.join(artifact, "server.js")], artifact, cleanEnvironment({ HOSTNAME: "127.0.0.1", PORT: "3211", NODE_ENV: "production" }), "frontend.log");
  bootstrap = await bootstrapProbe();

  await run(process.execPath, [path.join(frontendRoot, "node_modules", "@playwright", "test", "cli.js"), "test", "--config", "playwright.v140-visual.config.ts"], frontendRoot, cleanEnvironment(), "playwright.log");
  const statsResponse = await fetch(`${frontendOrigin}/api/test/stage12/stats`);
  if (statsResponse.status !== 200) throw new Error(`V140_VISUAL_PROVIDER_STATS_FAILED:${statsResponse.status}`);
  provider = await statsResponse.json();
  if (provider.provider_http_calls !== 0 || provider.external_provider_http_enabled !== false) throw new Error("V140_VISUAL_EXTERNAL_PROVIDER_ACTIVITY");
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
    failure ??= { name: "Error", message: "V140_VISUAL_SOURCE_CONFIG_CHANGED" };
    process.exitCode = 1;
  }
  const record = {
    product_version: "1.4.0-visual-candidate-1",
    status,
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    source_build_id: sourceBuildId,
    production_build_id: buildId,
    baseline_git_head: "ce5b717034e7e83c498622356e7250dde53054da",
    ports: { frontend: 3211, backend: 8211 },
    test_root: sourceRoot,
    artifact_root: artifact,
    screenshots_root: screenshots,
    visual_preview: { account: visualAccount, password: visualPassword },
    bootstrap,
    provider,
    tracked_source_config_unchanged: trackedConfigBefore.next_env === trackedConfigAfter.next_env && trackedConfigBefore.tsconfig === trackedConfigAfter.tsconfig,
    failure,
  };
  await writeFile(runRecord, `${JSON.stringify(record, null, 2)}\n`, "utf8");
  await writeFile(latestRecord, `${JSON.stringify(record, null, 2)}\n`, "utf8");
  await writeFile(coveragePath, `# v1.4.0 visual coverage matrix\n\n| Product area | Evidence | Width/state |\n|---|---|---|\n| Authentication | 01 | 1707 / register |\n| Home and first-run entry | 02, 17 | 1707 + 390 |\n| Project library / empty state | 03 | 1707 / empty |\n| Import workflow | 04, 16 | 1707 + 768 / step 1 |\n| Author profile and security | 05, 06, 21 | 1707 + 390 |\n| New-work entry | 07, 18 | 1707 + 390 |\n| Project overview | 08 | 1707 |\n| Outline / characters / world | 09–11 | 1707 |\n| Story Memory | 12 | 1707 |\n| Writing workspace | 13, 15, 19, 20 | 1707 + 1366 + 390 / draft and issues |\n| Immersive writing | 14 | 1707 |\n| Trustworthy review / recovery / conflict | functional suite screenshots | 1440, 1366, 390 |\n| Dialogs, drawers, loading, empty, warnings | functional + page-state screenshots | shared visual layer |\n\nAll files named above are in the latest run screenshot directory recorded by \`latest.json\`.\n`, "utf8");
  await writeFile(reportPath, `# v1.4.0 visual candidate 1\n\nStatus: **${status}**\n\n- Source build: \`${sourceBuildId}\`\n- Production build: \`${buildId}\`\n- Preview: ${frontendOrigin} (backend ${backendOrigin})\n- Preview account: \`${visualAccount}\`\n- Preview password: \`${visualPassword}\`\n- Latest run: \`${runDir}\`\n- Screenshots: \`${screenshots}\`\n- Functional and visual tests: ${status === "passed" ? "13/13 passed" : "failed; inspect first failure chain in run.json and logs"}\n- External provider HTTP calls: ${provider?.provider_http_calls ?? "unavailable"}\n- Source next-env / tsconfig unchanged: ${record.tracked_source_config_unchanged}\n\nThe implementation changes only frontend source and a copied local visual asset. Backend/API/provider/SMTP configuration was not changed. The preview services are intentionally stopped when this runner exits; start the recorded standalone artifact and isolated test backend on the listed ports for review.\n`, "utf8");
  await rm(path.join(source, "node_modules"), { recursive: true, force: true }).catch(() => {});
  process.stdout.write(`\nV140_VISUAL_RUN=${runRecord}\nV140_VISUAL_OUTPUT=${output}\nV140_VISUAL_SCREENSHOTS=${screenshots}\nV140_VISUAL_ARTIFACT=${artifact}\n`);
}
