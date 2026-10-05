import { spawn } from 'node:child_process';
import { cp, mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { computeSourceBuildId } from '../../../frontend/build-id.mjs';

const evidence = import.meta.dirname;
const repo = path.resolve(evidence, '../../..');
const front = path.join(repo, 'frontend');
const distName = '.next-gap-r2-repair';
const dist = path.join(front, distName);
const frontendOrigin = 'http://127.0.0.1:3239';
const backendOrigin = 'http://127.0.0.1:8239';
const output = path.join(evidence, `attempt-${Date.now()}-${process.pid}`);
await mkdir(output);
const children = [];
const result = { status: 'failed', started_at: new Date().toISOString(), output, frontendOrigin, backendOrigin, cleanup: [] };
async function hash(file) { return createHash('sha256').update(await readFile(path.join(repo, file))).digest('hex'); }
async function sourceIdentity() {
  const names = ['backend/app/engine.py', 'backend/app/v2_database.py', 'backend/app/provider.py', 'backend/tests/e2e_app.py', 'frontend/app/components/Workbench.tsx', 'frontend/app/model.ts', 'frontend/next-env.d.ts', 'frontend/tsconfig.json', 'frontend/e2e/legacy-gap-round3-brief.spec.ts', 'docs/legacy-gap-evidence/independent-round3-browser/g02_brief_app.py'];
  return { frontend_source_build_id: await computeSourceBuildId(front), files: Object.fromEntries(await Promise.all(names.map(async name => [name, await hash(name)]))) };
}
function env(extra = {}) {
  const clean = { ...process.env };
  for (const key of Object.keys(clean)) if (/^(?:CONTINUITY_|SMTP_|RECOVERY_HASH_SECRET$|PUBLIC_RESET_BASE_URL$)/.test(key) || /(?:API_KEY|PASSWORD|TOKEN|SECRET)$/i.test(key)) delete clean[key];
  return { ...clean, BACKEND_ORIGIN: backendOrigin, PUBLIC_APP_MODE: '0', PUBLIC_BASE_URL: frontendOrigin, NEXT_DIST_DIR: distName,
    E2E_BASE_URL: frontendOrigin, E2E_BACKEND_ORIGIN: backendOrigin, E2E_ACCOUNT_PREFIX: `gapg02r3${process.pid}`,
    E2E_TEST_ROOT: result.root, E2E_OUTPUT_DIR: output, SCC_DISABLE_DEFAULT_APP: '1', SCC_G02_ROUND3_BROWSER: '1',
    PYTHONPATH: path.join(repo, 'backend'), ...extra };
}
async function free(port) {
  await new Promise((resolve, reject) => { const server = net.createServer(); server.once('error', reject); server.listen(port, '127.0.0.1', () => server.close(resolve)); });
}
function start(command, args, cwd, name, extra = {}) {
  const child = spawn(command, args, { cwd, env: env(extra), windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  const record = { child, name, text: '' };
  record.done = new Promise(resolve => { child.once('error', error => { record.text += String(error); resolve(-1); }); child.once('exit', resolve); });
  child.stdout.on('data', chunk => record.text += chunk); child.stderr.on('data', chunk => record.text += chunk);
  children.push(record); return record;
}
async function ready(url) {
  const deadline = Date.now() + 45000;
  while (Date.now() < deadline) {
    try { const response = await fetch(url); if (response.status === 200) return response; } catch { /* bounded local readiness wait */ }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw Error(`Not ready: ${url}`);
}
function assert(condition, message) { if (!condition) throw Error(message); }
async function stats() {
  const value = await (await fetch(`${backendOrigin}/api/test/stage12/stats`)).json();
  assert(value.provider_mode === 'injected_stub' && value.external_provider_http_enabled === false && value.provider_http_calls === 0, 'Real provider isolation failed');
  assert(path.resolve(value.test_root) === path.resolve(result.root), 'Backend root mismatch');
  return value;
}
try {
  await Promise.all([free(3239), free(8239)]); result.ports_free_before_start = true;
  result.source_before = await sourceIdentity();
  result.build_id = (await readFile(path.join(dist, 'BUILD_ID'), 'utf8')).trim();
  assert(result.build_id === 'zh0KdT5LoRWDgI31kwXkx', 'Wrong production artifact');
  result.routes = JSON.parse(await readFile(path.join(dist, 'routes-manifest.json'), 'utf8'));
  assert(result.routes.rewrites.afterFiles.some(route => route.source === '/api/:path*' && route.destination === `${backendOrigin}/api/:path*`), 'Wrong baked backend rewrite');
  result.app_paths = JSON.parse(await readFile(path.join(dist, 'server', 'app-paths-manifest.json'), 'utf8'));
  assert(!Object.keys(result.app_paths).some(route => route.includes('test-writing-tools')), 'Test page in production artifact');
  result.root = await mkdtemp(path.join(tmpdir(), 'story-v130-rc-g02-r3-'));
  result.artifact = path.join(result.root, 'standalone');
  await cp(path.join(dist, 'standalone'), result.artifact, { recursive: true, errorOnExist: true });
  await cp(path.join(front, 'public'), path.join(result.artifact, 'public'), { recursive: true, errorOnExist: true });
  await cp(path.join(dist, 'static'), path.join(result.artifact, distName, 'static'), { recursive: true, errorOnExist: true });
  result.copied_build_id = (await readFile(path.join(result.artifact, distName, 'BUILD_ID'), 'utf8')).trim();
  assert(result.copied_build_id === result.build_id, 'Copied build identity mismatch');
  await writeFile(path.join(output, 'artifact-identity.json'), JSON.stringify({ build_id: result.build_id, source_before: result.source_before, routes: result.routes, app_paths: result.app_paths }, null, 2) + '\n');
  start(path.join(repo, '.venv', 'Scripts', 'python.exe'), ['-B', '-m', 'uvicorn', 'g02_brief_app:app', '--app-dir', evidence, '--host', '127.0.0.1', '--port', '8239'], path.join(repo, 'backend'), 'backend.log', { TRUSTED_HOSTS: '127.0.0.1:8239', TRUSTED_ORIGINS: frontendOrigin });
  await ready(`${backendOrigin}/health`); result.provider_before = await stats();
  start(process.execPath, [path.join(result.artifact, 'server.js')], result.artifact, 'frontend.log', { HOSTNAME: '127.0.0.1', PORT: '3239', NODE_ENV: 'production' });
  const html = await (await ready(frontendOrigin)).text();
  result.assets = [];
  const assets = [...new Set(html.match(/\/_next\/static\/[^"']+\.(?:js|css)(?:\?[^"']*)?/g) ?? [])];
  assert(assets.length > 0, 'No bootstrap assets');
  for (const asset of assets) { const response = await fetch(frontendOrigin + asset); result.assets.push({ asset, status: response.status }); assert(response.status === 200, `Broken asset: ${asset}`); }
  result.session_status = (await fetch(`${frontendOrigin}/api/auth/session?optional=true`)).status;
  assert(result.session_status === 200, 'Session bootstrap failed');
  const browser = start(process.execPath, [path.join(front, 'node_modules', '@playwright', 'test', 'cli.js'), 'test', '--config', 'playwright.config.ts', 'e2e/legacy-gap-round3-brief.spec.ts', 'e2e/v130-writing-analysis.spec.ts', '--output', path.join(output, 'results'), '--reporter', 'line'], front, 'playwright.log');
  result.test_exit = await browser.done; process.stdout.write(browser.text);
  result.provider_after = await stats();
  result.fixture_calls = await (await fetch(`${backendOrigin}/api/test/round3/brief-fixtures`)).json();
  assert(result.test_exit === 0, 'Playwright failed');
  result.status = 'passed';
} catch (error) { result.failure = { name: error.name, message: error.message }; process.exitCode = 1; }
finally {
  for (const record of [...children].reverse()) {
    if (record.child.exitCode === null) record.child.kill('SIGTERM');
    const exit = await record.done;
    result.cleanup.push({ name: record.name, pid: record.child.pid, exit, signal: record.child.signalCode });
    await writeFile(path.join(output, record.name), record.text, 'utf8');
  }
  result.source_after = await sourceIdentity();
  result.source_unchanged = JSON.stringify(result.source_before) === JSON.stringify(result.source_after);
  if (!result.source_unchanged) { result.status = 'failed'; process.exitCode = 1; result.failure ??= { message: 'Source identity changed during acceptance' }; }
  try { await Promise.all([free(3239), free(8239)]); result.ports_free_after_cleanup = true; }
  catch (error) { result.status = 'failed'; process.exitCode = 1; result.cleanup_error = error.message; }
  result.completed_at = new Date().toISOString();
  await writeFile(path.join(output, 'result.json'), JSON.stringify(result, null, 2) + '\n');
  process.stdout.write(JSON.stringify({ status: result.status, build_id: result.build_id, output, test_exit: result.test_exit, source_unchanged: result.source_unchanged, ports_free_after_cleanup: result.ports_free_after_cleanup, failure: result.failure }, null, 2) + '\n');
}
