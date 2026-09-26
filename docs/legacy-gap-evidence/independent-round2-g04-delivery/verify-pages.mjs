import { spawn } from 'node:child_process';
import { cp, mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import path from 'node:path';
import net from 'node:net';

const evidence = import.meta.dirname;
const repo = path.resolve(evidence, '../../..');
const front = path.join(repo, 'frontend');
const distName = '.next-gap-final-accept';
const dist = path.join(front, distName);
const frontendOrigin = 'http://127.0.0.1:3238';
const backendOrigin = 'http://127.0.0.1:8238';
const output = path.join(evidence, `pages-attempt-${Date.now()}-${process.pid}`);
await mkdir(output);
const result = { started_at: new Date().toISOString(), status: 'failed', output, frontendOrigin, backendOrigin, pages: [], externalRequests: [], cleanup: [] };
const children = [];
let browser;

function isolatedEnv(extra = {}) {
  const clean = { ...process.env };
  for (const key of Object.keys(clean)) {
    if (/^(?:CONTINUITY_|SMTP_|RECOVERY_HASH_SECRET$|PUBLIC_RESET_BASE_URL$)/.test(key) || /(?:API_KEY|PASSWORD|TOKEN|SECRET)$/i.test(key)) delete clean[key];
  }
  return { ...clean, BACKEND_ORIGIN: backendOrigin, PUBLIC_APP_MODE: '0', PUBLIC_BASE_URL: frontendOrigin, NEXT_DIST_DIR: distName, E2E_TEST_ROOT: result.root, SCC_DISABLE_DEFAULT_APP: '1', ...extra };
}
async function free(port) {
  await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(port, '127.0.0.1', () => server.close(resolve));
  });
}
function start(command, args, cwd, name, extra) {
  const child = spawn(command, args, { cwd, env: isolatedEnv(extra), windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  const record = { child, name, text: '' };
  record.done = new Promise(resolve => {
    child.once('error', error => { record.text += String(error); resolve({ error: String(error) }); });
    child.once('exit', (code, signal) => resolve({ code, signal }));
  });
  child.stdout.on('data', chunk => record.text += chunk);
  child.stderr.on('data', chunk => record.text += chunk);
  children.push(record);
}
async function ready(url) {
  const deadline = Date.now() + 45000;
  while (Date.now() < deadline) {
    try { if ((await fetch(url)).status === 200) return; } catch { /* bounded local readiness wait */ }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw Error(`Local service not ready: ${url}`);
}
function assert(value, message) { if (!value) throw Error(message); }
async function sha(file) { return createHash('sha256').update(await readFile(file)).digest('hex'); }
async function stats() {
  const data = await (await fetch(`${backendOrigin}/api/test/stage12/stats`)).json();
  assert(data.provider_mode === 'injected_stub' && data.external_provider_http_enabled === false && data.provider_http_calls === 0, 'Provider isolation check failed');
  assert(path.resolve(data.test_root) === path.resolve(result.root), 'Backend does not use this new temporary root');
  return data;
}

try {
  await Promise.all([free(3238), free(8238)]);
  result.ports_free_before_start = true;
  result.build_id = (await readFile(path.join(dist, 'BUILD_ID'), 'utf8')).trim();
  assert(result.build_id === 'W52CgAUpNgqPizlf_vc_k', 'Unexpected artifact identity');
  result.root = await mkdtemp(path.join(tmpdir(), 'story-v130-rc-g04-delivery-pages-'));
  result.artifact = path.join(result.root, 'standalone');
  await cp(path.join(dist, 'standalone'), result.artifact, { recursive: true, errorOnExist: true });
  await cp(path.join(front, 'public'), path.join(result.artifact, 'public'), { recursive: true, errorOnExist: true });
  await cp(path.join(dist, 'static'), path.join(result.artifact, distName, 'static'), { recursive: true, errorOnExist: true });
  result.route_manifest_sha256 = await sha(path.join(dist, 'server', 'app-paths-manifest.json'));
  result.copied_route_manifest_sha256 = await sha(path.join(result.artifact, distName, 'server', 'app-paths-manifest.json'));
  assert(result.route_manifest_sha256 === result.copied_route_manifest_sha256, 'Copied artifact manifest mismatch');
  start(path.join(repo, '.venv', 'Scripts', 'python.exe'), ['-m', 'uvicorn', 'tests.e2e_app:app', '--host', '127.0.0.1', '--port', '8238'], path.join(repo, 'backend'), 'backend.log', { TRUSTED_HOSTS: '127.0.0.1:8238', TRUSTED_ORIGINS: frontendOrigin });
  await ready(`${backendOrigin}/health`);
  result.provider_before = await stats();
  start(process.execPath, [path.join(result.artifact, 'server.js')], result.artifact, 'frontend.log', { HOSTNAME: '127.0.0.1', PORT: '3238', NODE_ENV: 'production' });
  await ready(frontendOrigin);

  const { chromium } = createRequire(path.join(front, 'package.json'))('playwright');
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (['http:', 'https:'].includes(url.protocol) && ![frontendOrigin, backendOrigin].includes(url.origin)) {
      result.externalRequests.push(route.request().url());
      await route.abort('blockedbyclient');
    } else await route.continue();
  });
  await context.tracing.start({ screenshots: true, snapshots: true, sources: false });
  for (const scenario of [
    { route: '/test-writing-tools', heading: '登录', finalPath: '/login', image: 'test-writing-tools-catchall-to-login-1440.png' },
    { route: '/register', heading: '创建账号', finalPath: '/register', image: 'register-production-1440.png' },
  ]) {
    const record = { route: scenario.route, pageErrors: [], consoleErrors: [], failedRequests: [], errorResponses: [], writeRequests: [] };
    result.pages.push(record);
    const page = await context.newPage();
    page.on('pageerror', error => record.pageErrors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') record.consoleErrors.push(message.text()); });
    page.on('requestfailed', request => record.failedRequests.push({ url: request.url(), reason: request.failure()?.errorText }));
    page.on('response', response => { if (response.status() >= 400) record.errorResponses.push({ url: response.url(), status: response.status() }); });
    page.on('request', request => { if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) record.writeRequests.push({ method: request.method(), url: request.url() }); });
    const response = await page.goto(frontendOrigin + scenario.route, { waitUntil: 'networkidle' });
    record.initial_http_status = response.status();
    await page.waitForURL(frontendOrigin + scenario.finalPath);
    await page.getByRole('heading', { name: scenario.heading, exact: true }).waitFor({ state: 'visible' });
    await page.evaluate(() => document.fonts.ready);
    record.final_url = page.url();
    record.title = await page.title();
    record.body_text = await page.locator('body').innerText();
    record.harness_elements = await page.locator('#rich-test-body, #rich-case, [data-testid="serialized-body"]').count();
    record.dev_overlay_elements = await page.locator('nextjs-portal, [data-nextjs-dialog-overlay], [data-nextjs-toast], [data-nextjs-dev-tools-button]').count();
    record.harness_text = /富文本建议替换浏览器测试|富文本测试正文|隔离测试页；调用实际/.test(record.body_text);
    record.screenshot = path.join(output, scenario.image);
    await page.screenshot({ path: record.screenshot, fullPage: true });
    assert(record.harness_elements === 0 && !record.harness_text, 'Test harness appeared in production');
    assert(record.dev_overlay_elements === 0, 'Development overlay appeared in production');
    assert(record.pageErrors.length === 0 && record.consoleErrors.length === 0, 'Browser page or console error');
    assert(record.failedRequests.length === 0 && record.errorResponses.length === 0, 'Browser request failure');
    assert(record.writeRequests.length === 0, 'Unexpected browser write request');
    await page.close();
  }
  await context.tracing.stop({ path: path.join(output, 'two-pages-trace.zip') });
  result.provider_after = await stats();
  assert(result.externalRequests.length === 0, 'Unexpected external browser request');
  result.status = 'passed';
} catch (error) {
  result.failure = { name: error.name, message: error.message };
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  for (const record of [...children].reverse()) {
    if (record.child.exitCode === null) record.child.kill('SIGTERM');
    const stopped = await Promise.race([record.done, new Promise(resolve => setTimeout(() => resolve({ timeout: true }), 5000))]);
    result.cleanup.push({ name: record.name, pid: record.child.pid, ...stopped });
    await writeFile(path.join(output, record.name), record.text, 'utf8');
  }
  try { await Promise.all([free(3238), free(8238)]); result.ports_free_after_cleanup = true; }
  catch (error) { result.cleanup_error = error.message; result.status = 'failed'; process.exitCode = 1; }
  result.completed_at = new Date().toISOString();
  await writeFile(path.join(output, 'result.json'), JSON.stringify(result, null, 2) + '\n', 'utf8');
  process.stdout.write(JSON.stringify({ status: result.status, output, build_id: result.build_id, pages: result.pages.map(p => ({ route: p.route, final_url: p.final_url, screenshot: p.screenshot })), ports_free_after_cleanup: result.ports_free_after_cleanup, failure: result.failure }, null, 2) + '\n');
}
