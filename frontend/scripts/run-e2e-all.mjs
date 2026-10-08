import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";

// Read before the environment is sanitised below: the caller may point E2E_PYTHON at an interpreter.
const callerPython = process.env.E2E_PYTHON;
const frontendRoot = path.resolve(import.meta.dirname, "..");
const repositoryRoot = path.resolve(frontendRoot, "..");
const playwrightCli = path.join(frontendRoot, "node_modules", "@playwright", "test", "cli.js");
// E2E_PYTHON wins; otherwise the repository's own virtual environment.
const python = callerPython || path.join(repositoryRoot, ".venv", "Scripts", "python.exe");
if (!existsSync(python)) throw new Error(`No Python interpreter at ${python}. Set E2E_PYTHON to a python.exe that can run the backend.`);
// The browser tests exercise the sample work users actually see, not the frozen copy backend unit tests pin.
const sampleWorkFile = path.join(repositoryRoot, "backend", "app", "seed", "sample_work.json");

// Fixed port table. 3170/8170 and 3190/8190 belong to the developer's preview and acceptance servers.
const groups = {
  v170: { ports: [3280, 8280], config: "playwright.v170.config.ts", prefix: "story-v170-e2e-", account: "v170e2e", dist: ".next-e2e-v170" },
};

function options() {
  const args = process.argv.slice(2);
  if (args.length === 1 && args[0] === "--help") {
    console.log(`Usage: npm run test:e2e -- [--group ${Object.keys(groups).join(",")}] [--grep <test title fragment>]\nPorts: ${Object.entries(groups).map(([name, group]) => `${name}=${group.ports.join("/")}`).join(", ")}`);
    return null;
  }
  let selected = Object.keys(groups);
  let grep;
  while (args.length) {
    const arg = args.shift();
    if (arg === "--group" && args[0]) selected = args.shift().split(",");
    else if (arg === "--grep" && args[0]) grep = args.shift();
    else throw new Error(`Unknown or incomplete option: ${arg}`);
  }
  if (!selected.length || new Set(selected).size !== selected.length || selected.some((name) => !groups[name])) throw new Error("Invalid or duplicate E2E group");
  return { selected, grep };
}

// Sanitize the parent as well as every child. No values of removed variables
// are logged, and caller-supplied E2E profiles cannot leak into another group.
function cleanEnvironment(extra = {}) {
  const env = { ...process.env };
  for (const name of Object.keys(env)) {
    if (/^(CONTINUITY_|SMTP_|E2E_)/i.test(name)
      || /(?:API_KEY|PASSWORD|TOKEN|SECRET)$/i.test(name)
      || /^(PUBLIC_RESET_BASE_URL|BACKEND_ORIGIN|PUBLIC_APP_MODE|PUBLIC_BASE_URL|TRUSTED_HOSTS|TRUSTED_ORIGINS|NEXT_DIST_DIR|NEXT_BUILD_ID|NODE_ENV|PLAYWRIGHT_JSON_OUTPUT_NAME|PLAYWRIGHT_JSON_OUTPUT_DIR|PLAYWRIGHT_HTML_OUTPUT_DIR|PLAYWRIGHT_HTML_OPEN|PLAYWRIGHT_MAX_FAILURES|PLAYWRIGHT_BROWSERS_PATH)$/i.test(name)) delete env[name];
  }
  return { ...env, ...extra };
}
for (const name of Object.keys(process.env)) {
  if (/^(CONTINUITY_|SMTP_)/i.test(name) || /(?:API_KEY|PASSWORD|TOKEN|SECRET)$/i.test(name)) delete process.env[name];
}

function environment(group, root) {
  const frontendOrigin = `http://127.0.0.1:${group.ports[0]}`;
  const backendOrigin = `http://127.0.0.1:${group.ports[1]}`;
  return cleanEnvironment({
    E2E_BASE_URL: frontendOrigin, E2E_BACKEND_ORIGIN: backendOrigin,
    BACKEND_ORIGIN: backendOrigin, PUBLIC_APP_MODE: "0", PUBLIC_BASE_URL: frontendOrigin,
    TRUSTED_HOSTS: `127.0.0.1:${group.ports[1]},testserver`,
    TRUSTED_ORIGINS: `${frontendOrigin},http://testserver`, SCC_DISABLE_DEFAULT_APP: "1",
    NEXT_DIST_DIR: group.dist, E2E_ACCOUNT_PREFIX: `${group.account}${process.pid}`,
    E2E_TEST_ROOT: root, E2E_OUTPUT_DIR: path.join(root, "test-results"),
    E2E_SCREENSHOTS_DIR: path.join(root, "screenshots"),
    E2E_JSON_REPORT: path.join(root, "playwright-report.json"),
    E2E_REPORT_DIR: path.join(root, "playwright-report"),
    E2E_PROVIDER_STATS: path.join(root, "provider-stats.json"),
    E2E_LAST_RUN: path.join(root, "last-run.json"), E2E_ARTIFACT_ROOT: path.join(root, "standalone"),
  });
}

const active = new Set();
let interrupted = false;
function start(command, args, cwd, env, logPath, echo = true) {
  const child = spawn(command, args, { cwd, env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  const managed = { child, output: "", logPath, done: null };
  active.add(managed);
  for (const stream of [child.stdout, child.stderr]) stream.on("data", (chunk) => {
    managed.output += chunk;
    if (echo) process.stdout.write(chunk);
  });
  managed.done = new Promise((resolve) => {
    child.once("error", (error) => resolve({ code: null, error: error.message }));
    child.once("close", (code, signal) => { active.delete(managed); resolve({ code, signal }); });
  });
  return managed;
}

async function finish(managed) {
  const result = await managed.done;
  await writeFile(managed.logPath, managed.output);
  return { ...result, output: managed.output };
}

async function run(command, args, cwd, env, logPath, echo = true) {
  if (interrupted) throw new Error("E2E run interrupted");
  return finish(start(command, args, cwd, env, logPath, echo));
}

async function checked(command, args, cwd, env, logPath) {
  const result = await run(command, args, cwd, env, logPath);
  if (result.code !== 0) throw new Error(`${path.basename(logPath)}: exit ${result.code}: ${result.error ?? result.output.slice(-1500)}`);
  return result;
}

async function stop(managed) {
  if (!managed) return;
  const child = managed.child;
  if (child.pid && child.exitCode === null && child.signalCode === null) {
    if (process.platform === "win32") {
      const killed = spawnSync("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, encoding: "utf8" });
      if (killed.status !== 0 && child.exitCode === null && child.signalCode === null) throw new Error(`Process tree cleanup failed for owned PID ${child.pid}: ${killed.stderr}`);
    } else child.kill("SIGTERM");
  }
  await finish(managed);
}

for (const signal of ["SIGINT", "SIGTERM"]) process.once(signal, () => {
  interrupted = true;
  for (const managed of active) {
    if (process.platform === "win32") spawnSync("taskkill.exe", ["/PID", String(managed.child.pid), "/T", "/F"], { windowsHide: true });
    else managed.child.kill("SIGTERM");
  }
});

async function assertPortsFree(ports) {
  for (const port of ports) await new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", (error) => reject(new Error(`Port ${port} is unavailable: ${error.code}`)));
    server.listen({ port, host: "127.0.0.1", exclusive: true }, () => server.close((error) => error ? reject(error) : resolve()));
  });
}

async function waitFor(url, managed) {
  const deadline = Date.now() + 60_000;
  let last;
  while (Date.now() < deadline && !interrupted) {
    if (managed.child.exitCode !== null || managed.child.signalCode !== null) throw new Error(`Server exited before ${url}: ${managed.output.slice(-1500)}`);
    try {
      const response = await fetch(url, { redirect: "manual", signal: AbortSignal.timeout(2000) });
      if (response.status === 200) return response;
      last = `HTTP ${response.status}`;
    } catch (error) { last = error.message; }
    // Poll server readiness; this is not a fixed delay inside a browser test.
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Server readiness failed: ${url}: ${last}`);
}

async function removeTempRoot(root, prefix) {
  const resolved = path.resolve(root);
  if (path.dirname(resolved) !== path.resolve(tmpdir()) || !path.basename(resolved).startsWith(prefix)) throw new Error(`Unsafe temporary cleanup target: ${resolved}`);
  await rm(resolved, { recursive: true, force: true });
}

async function copySource(source) {
  await mkdir(source, { recursive: true });
  for (const dir of ["app", "public"]) await cp(path.join(frontendRoot, dir), path.join(source, dir), { recursive: true, errorOnExist: true });
  for (const file of ["package.json", "package-lock.json", "next.config.mjs", "tsconfig.json", "next-env.d.ts", "build-id.mjs", "build-origin.mjs", "public-config.mjs", "stage13-harness.mjs"]) await cp(path.join(frontendRoot, file), path.join(source, file), { errorOnExist: true });
  // Reuse stage serving/build scripts in the copy; no app route is written to
  // the checkout, and no .env file is copied.
  await cp(path.join(frontendRoot, "scripts"), path.join(source, "scripts"), { recursive: true });
  if (process.platform === "win32") {
    const copied = spawnSync("robocopy.exe", [path.join(frontendRoot, "node_modules"), path.join(source, "node_modules"), "/E", "/MT:16", "/NFL", "/NDL", "/NJH", "/NJS", "/R:0", "/W:0"], { windowsHide: true, encoding: "utf8" });
    if (copied.status === null || copied.status > 7) throw new Error(`Dependency copy failed: ${copied.stderr}`);
  } else await cp(path.join(frontendRoot, "node_modules"), path.join(source, "node_modules"), { recursive: true, dereference: true });
}

async function buildSource(source, env, logs) {
  const drive = "Q:";
  let mapped = false;
  try {
    if (process.platform === "win32") {
      if (existsSync(`${drive}\\`)) throw new Error("Build drive Q: is already in use");
      const result = spawnSync("subst.exe", [drive, source], { windowsHide: true, encoding: "utf8" });
      if (result.status !== 0) throw new Error(`Build drive mapping failed: ${result.stderr}`);
      mapped = true;
    }
    const cwd = mapped ? `${drive}\\` : source;
    await checked(process.execPath, [path.join(cwd, "node_modules", "next", "dist", "bin", "next"), "build"], cwd, { ...env, NODE_ENV: "production" }, path.join(logs, "build.log"));
  } finally {
    if (mapped) {
      const result = spawnSync("subst.exe", [drive, "/D"], { windowsHide: true, encoding: "utf8" });
      if (result.status !== 0) throw new Error(`Build drive cleanup failed: ${result.stderr}`);
    }
  }
}

function flatten(report) {
  const rows = [];
  function visit(suites, titles = []) {
    for (const suite of suites ?? []) {
      const ancestry = suite.title ? [...titles, suite.title] : titles;
      for (const spec of suite.specs ?? []) for (const test of spec.tests ?? []) {
        const result = test.results?.at(-1);
        // test.fixme / test.skip are declared, not failed: they are counted apart from tests that never ran.
        const status = result?.status === "passed" && test.status === "expected" ? "passed"
          : test.status === "skipped" ? "skipped"
          : !result || ["skipped", "interrupted"].includes(result.status) ? "not_run" : "failed";
        const error = result?.errors?.find((error) => error.message?.startsWith("Error:"))?.message ?? result?.errors?.[0]?.message ?? result?.error?.message ?? "";
        rows.push({ file: spec.file.replaceAll("\\", "/"), line: spec.line, title: [...ancestry.slice(1), spec.title].join(" › "), project: test.projectName, status, error: error.replace(/\x1b\[[0-9;]*m/g, "") });
      }
      visit(suite.suites, ancestry);
    }
  }
  visit(report.suites);
  return rows;
}

async function inventory(group, root, env, grep) {
  const listFile = path.join(root, "inventory.json");
  await checked(process.execPath, [playwrightCli, "test", "--config", path.join(frontendRoot, group.config), "--list", "--reporter=json", ...(grep ? ["--grep", grep] : [])], repositoryRoot, { ...env, PLAYWRIGHT_JSON_OUTPUT_NAME: listFile }, path.join(root, "inventory.log"));
  return flatten(JSON.parse(await readFile(listFile, "utf8")));
}

async function generic(group, root, env, grep) {
  const logs = path.join(root, "logs");
  await mkdir(logs);
  await mkdir(env.E2E_SCREENSHOTS_DIR);
  const source = path.join(root, "source");
  const artifact = path.join(root, "standalone");
  let backend;
  let frontend;
  try {
    await copySource(source);
    await buildSource(source, env, logs);
    const dist = path.join(source, group.dist);
    await cp(path.join(dist, "standalone"), artifact, { recursive: true, errorOnExist: true });
    await cp(path.join(source, "public"), path.join(artifact, "public"), { recursive: true, errorOnExist: true });
    await mkdir(path.join(artifact, group.dist), { recursive: true });
    await cp(path.join(dist, "static"), path.join(artifact, group.dist, "static"), { recursive: true, errorOnExist: true });

    backend = start(python, ["-m", "uvicorn", "tests.e2e_app:app", "--host", "127.0.0.1", "--port", String(group.ports[1]), "--timeout-keep-alive", "75", "--log-level", "warning"], path.join(repositoryRoot, "backend"), { ...env, STORY_SAMPLE_WORK_FILE: sampleWorkFile }, path.join(logs, "backend.log"));
    await waitFor(`${env.E2E_BACKEND_ORIGIN}/health`, backend);
    frontend = start(process.execPath, [path.join(artifact, "server.js")], artifact, { ...env, NODE_ENV: "production", HOSTNAME: "127.0.0.1", PORT: String(group.ports[0]) }, path.join(logs, "frontend.log"));
    await waitFor(`${env.E2E_BASE_URL}/`, frontend);
    const bootstrap = await fetch(`${env.E2E_BASE_URL}/api/auth/session?optional=true`);
    if (bootstrap.status !== 200) throw new Error(`Same-origin session bootstrap failed: ${bootstrap.status}`);
    const result = await run(process.execPath, [playwrightCli, "test", "--config", path.join(frontendRoot, group.config), ...(grep ? ["--grep", grep] : [])], repositoryRoot, env, path.join(logs, "playwright.log"));
    const statsResponse = await fetch(`${env.E2E_BASE_URL}/api/test/stage12/stats`);
    if (!statsResponse.ok) throw new Error(`Provider statistics unavailable: ${statsResponse.status}`);
    const stats = await statsResponse.json();
    await writeFile(path.join(root, "provider-stats.json"), JSON.stringify(stats, null, 2));
    if (stats.provider_http_calls !== 0 || stats.smtp_external_calls > 0) throw new Error("External provider or SMTP activity detected");
    return { code: result.code, reportPath: env.E2E_JSON_REPORT, stats };
  } finally {
    const cleanup = await Promise.allSettled([stop(frontend), stop(backend)]);
    const failures = cleanup.filter((item) => item.status === "rejected");
    if (failures.length) throw new AggregateError(failures.map((item) => item.reason), "Server process cleanup failed");
  }
}

const hash = async (file) => createHash("sha256").update(await readFile(path.join(frontendRoot, file))).digest("hex");

async function main() {
  const requested = options();
  if (!requested) return;
  const reportRoot = await mkdtemp(path.join(tmpdir(), "story-e2e-all-report-"));
  const before = { nextEnv: await hash("next-env.d.ts"), tsconfig: await hash("tsconfig.json") };
  const summary = { started_at: new Date().toISOString(), groups: [], source_hashes_before: before };
  console.log(`E2E_REPORT_ROOT=${reportRoot}`);
  for (const name of requested.selected) {
    if (interrupted) break;
    const group = groups[name];
    const root = await mkdtemp(path.join(tmpdir(), group.prefix));
    const savedRoot = path.join(reportRoot, name);
    await mkdir(savedRoot);
    const row = { group: name, ports: group.ports, passed: 0, failed: 0, not_run: 0, skipped: 0, tests: [], infrastructure_errors: [] };
    let result;
    try {
      console.log(`\n=== ${name} (${group.ports.join("/")}) ===`);
      await assertPortsFree(group.ports);
      const env = environment(group, root);
      row.tests = await inventory(group, root, env, requested.grep);
      result = await generic(group, root, env, requested.grep);
      if (!existsSync(result.reportPath)) throw new Error(`No browser report: ${result.reportPath}`);
      const report = JSON.parse(await readFile(result.reportPath, "utf8"));
      await cp(result.reportPath, path.join(savedRoot, "playwright-report.json"));
      row.tests = flatten(report);
      for (const error of report.errors ?? []) row.infrastructure_errors.push(error.message);
      if (result.code !== 0 && !row.tests.some((test) => test.status === "failed") && !row.infrastructure_errors.length) row.infrastructure_errors.push(`Runner exit ${result.code}`);
      row.exit_code = result.code;
      row.provider = result.stats;
    } catch (error) {
      row.infrastructure_errors.push(error.message);
      console.error(`${name}: ${error.message}`);
      // A post-test infrastructure failure must not erase completed browser
      // results or turn them into tests that were never run.
      const reportPath = path.join(root, "playwright-report.json");
      if (existsSync(reportPath)) row.tests = flatten(JSON.parse(await readFile(reportPath, "utf8")));
    } finally {
      try {
        // Preserve diagnostic records before deleting this invocation's own
        // temporary sources, builds, databases and browser attachments.
        await cp(root, savedRoot, { recursive: true, filter: (source) => !["source", "standalone", "playwright-report"].includes(path.relative(root, source).split(path.sep)[0]) });
        await removeTempRoot(root, group.prefix);
        await assertPortsFree(group.ports);
      } catch (error) { row.infrastructure_errors.push(`Cleanup: ${error.message}`); }
    }
    row.passed = row.tests.filter((test) => test.status === "passed").length;
    row.failed = row.tests.filter((test) => test.status === "failed").length;
    row.not_run = row.tests.filter((test) => test.status === "not_run").length;
    row.skipped = row.tests.filter((test) => test.status === "skipped").length;
    summary.groups.push(row);
  }
  summary.source_hashes_after = { nextEnv: await hash("next-env.d.ts"), tsconfig: await hash("tsconfig.json") };
  summary.source_configs_unchanged = JSON.stringify(before) === JSON.stringify(summary.source_hashes_after);
  summary.completed_at = new Date().toISOString();
  summary.interrupted = interrupted;
  summary.failed = interrupted || !summary.source_configs_unchanged || summary.groups.some((row) => row.failed || row.not_run || row.infrastructure_errors.length);
  const table = ["| group | passed | failed | skipped (fixme) | not run | infrastructure errors |", "|---|---:|---:|---:|---:|---:|", ...summary.groups.map((row) => `| ${row.group} | ${row.passed} | ${row.failed} | ${row.skipped} | ${row.not_run} | ${row.infrastructure_errors.length} |`)];
  const failures = summary.groups.flatMap((row) => [
    ...row.tests.filter((test) => test.status === "failed").map((test) => `${row.group}: ${test.file}:${test.line} ${test.title}\n  ${test.error.split("\n").find((line) => line.trim()) ?? "Test failed"}`),
    ...row.infrastructure_errors.map((error) => `${row.group}: INFRASTRUCTURE ${error}`),
  ]);
  console.log(`\n${table.join("\n")}\n\n${failures.join("\n")}\n\nSource next-env.d.ts / tsconfig.json unchanged: ${summary.source_configs_unchanged}`);
  await writeFile(path.join(reportRoot, "summary.json"), JSON.stringify(summary, null, 2));
  await writeFile(path.join(reportRoot, "summary.md"), `${table.join("\n")}\n\n${failures.join("\n")}\n`);
  console.log(`E2E_SUMMARY=${path.join(reportRoot, "summary.json")}`);
  process.exitCode = summary.failed ? 1 : 0;
}

await main();
