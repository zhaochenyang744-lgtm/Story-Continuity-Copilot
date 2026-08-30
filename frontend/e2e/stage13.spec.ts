import { expect, test, type APIRequestContext, type BrowserContext, type APIResponse } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { validateStage13Harness } from "../stage13-harness.mjs";

const harness = validateStage13Harness(process.env);
const prefix = harness.accountPrefix;
const origin = harness.frontendOrigin;
const idempotency = () => ({ Origin: origin, "Idempotency-Key": crypto.randomUUID() });
const mutation = () => ({ Origin: origin });

async function data<T>(response: APIResponse): Promise<T> {
  const payload = await response.json();
  expect(response.ok(), JSON.stringify(payload)).toBeTruthy();
  return payload.data as T;
}

async function visitor(context: BrowserContext) {
  return data<{ user: { id: string }; seeded_projects: { id: string }[] }>(
    await context.request.post("/api/auth/visitor", { headers: mutation() }),
  );
}

async function register(context: BrowserContext, suffix: string) {
  const account = `${prefix}${suffix}`.toLowerCase().replace(/[^a-z0-9_.-]/g, "").slice(0, 60);
  const recovery = `${account}@example.test`;
  const response = await context.request.post("/api/auth/register", {
    headers: idempotency(),
    data: { account_name: account, display_name: suffix, password: "valid-password-13", recovery_email: recovery },
  });
  const payload = await data<{ user: { id: string }; seeded_projects: { id: string }[] }>(response);
  return { ...payload, account, recovery };
}

async function projectDraft(context: BrowserContext, projectId: string) {
  const project = await data<{ current_draft: { id: string } }>(await context.request.get(`/api/projects/${projectId}`));
  return data<{ id: string; revision: number }>(await context.request.get(`/api/projects/${projectId}/drafts/${project.current_draft.id}`));
}

async function waitRun(context: BrowserContext, projectId: string, runId: string) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const run = await data<{ run_id: string; status: string; error_code: string | null; retryable: boolean }>(
      await context.request.get(`/api/projects/${projectId}/checks/${runId}`),
    );
    if (["completed", "failed", "timed_out", "cancelled"].includes(run.status)) return run;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`run did not finish: ${runId}`);
}

async function capturedMail(request: APIRequestContext, purpose: "verify_email" | "password_reset") {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const payload = await (await request.get(`/api/test/stage13/mail/${purpose}`)).json();
    if (payload.available) return payload as { available: true; path: string; token: string };
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw new Error(`captured ${purpose} mail did not become active`);
}

test("visitor creates three demos, imports Markdown, and remains usable at 390px", async ({ page }) => {
  const evidence = { requests: [] as { method: string; path: string }[], responses: [] as { status: number; path: string; contentType: string }[], console: [] as { type: string; text: string }[], pageErrors: [] as string[] };
  page.on("request", (request) => evidence.requests.push({ method: request.method(), path: new URL(request.url()).pathname }));
  page.on("response", (response) => evidence.responses.push({ status: response.status(), path: new URL(response.url()).pathname, contentType: response.headers()["content-type"] || "" }));
  page.on("console", (message) => evidence.console.push({ type: message.type(), text: message.text() }));
  page.on("pageerror", (error) => evidence.pageErrors.push(error.stack || error.message));
  await mkdir(harness.outputDir, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/login");
  const loginDesktopOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(loginDesktopOverflow).toBeLessThanOrEqual(1);
  await page.screenshot({ path: path.join(harness.outputDir, "stage13-v4-login-1440.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  const loginMobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(loginMobileOverflow).toBeLessThanOrEqual(1);
  await page.screenshot({ path: path.join(harness.outputDir, "stage13-v4-login-390.png"), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "以访客身份体验 24 小时" }).click();
  await expect(page).toHaveURL("/");
  const projectsResponse = await page.request.get("/api/projects");
  const projects = await data<{ projects: { id: string }[] }>(projectsResponse);
  expect(projects.projects).toHaveLength(3);
  await page.goto("/projects/import");
  await page.locator('input[type="file"]').setInputFiles({
    name: "stage13-real.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# 第一章 潮声\n林默在清晨打开潮汐门。\n# 第二章 银钥匙\n银钥匙由守塔人保管。", "utf8"),
  });
  await page.getByRole("button", { name: "解析并预览章节" }).click();
  await expect(page.getByRole("heading", { name: "章节预览" })).toBeVisible();
  await page.getByRole("button", { name: "继续确认" }).click();
  await page.getByLabel("作品名").fill("Stage 13 导入作品");
  await page.getByRole("button", { name: "确认导入" }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/overview/);
  const desktopOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(desktopOverflow).toBeLessThanOrEqual(1);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByText(/浏览只读/)).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toBeVisible();
  expect(evidence.pageErrors).toEqual([]);
  await writeFile(path.join(harness.outputDir, "stage13-v4-browser-runtime.json"), JSON.stringify({
    viewports: [{ width: 1440, height: 900, overflow: loginDesktopOverflow }, { width: 390, height: 844, overflow: loginMobileOverflow }, { width: 390, height: 844, overflow }],
    keyboardFocusVisible: true,
    statusAnnouncementVisible: true,
    apiProjectsStatus: projectsResponse.status(),
    ...evidence,
  }, null, 2));
});

test("visitor and registered contexts are mutually isolated; quota and cleanup stop before writes", async ({ browser }) => {
  const visitorA = await browser.newContext({ baseURL: origin });
  const visitorB = await browser.newContext({ baseURL: origin });
  const registeredA = await browser.newContext({ baseURL: origin });
  const registeredB = await browser.newContext({ baseURL: origin });
  const va = await visitor(visitorA);
  const vb = await visitor(visitorB);
  const ra = await register(registeredA, "isolationa");
  const rb = await register(registeredB, "isolationb");
  const resources = [
    [visitorA, vb.seeded_projects[0].id], [visitorA, ra.seeded_projects[0].id],
    [visitorB, va.seeded_projects[0].id], [registeredA, va.seeded_projects[0].id],
    [registeredA, rb.seeded_projects[0].id], [registeredB, ra.seeded_projects[0].id],
  ] as const;
  for (const [context, projectId] of resources) {
    expect((await context.request.get(`/api/projects/${projectId}`)).status()).toBe(404);
  }
  const ownProject = va.seeded_projects[0].id;
  const draft = await projectDraft(visitorA, ownProject);
  for (let index = 0; index < 3; index += 1) {
    const response = await visitorA.request.post(`/api/projects/${ownProject}/checks`, {
      headers: idempotency(), data: { draft_id: draft.id, draft_revision: draft.revision },
    });
    expect(response.status()).toBe(202);
    const created = await data<{ run_id: string }>(response);
    expect((await waitRun(visitorA, ownProject, created.run_id)).status).toBe("completed");
  }
  const statsBefore = await (await visitorA.request.get("/api/test/stage13/stats")).json();
  const fourth = await visitorA.request.post(`/api/projects/${ownProject}/checks`, {
    headers: idempotency(), data: { draft_id: draft.id, draft_revision: draft.revision },
  });
  expect(fourth.status()).toBe(429);
  expect((await fourth.json()).error.code).toBe("workflow_quota_exceeded");
  const statsAfter = await (await visitorA.request.get("/api/test/stage13/stats")).json();
  expect(statsAfter.provider_calls).toBe(statsBefore.provider_calls);
  await visitorA.request.post(`/api/test/stage13/expire/${va.user.id}`);
  expect((await visitorA.request.get("/api/home")).status()).toBe(401);
  await visitorA.request.post("/api/test/stage13/cleanup");
  expect(await (await visitorA.request.get(`/api/test/stage13/counts/${va.user.id}`)).json()).toEqual({ projects: 0, sessions: 0, usage: 0 });
  expect((await visitorB.request.get("/api/projects")).status()).toBe(200);
  await Promise.all([visitorA.close(), visitorB.close(), registeredA.close(), registeredB.close()]);
});

test("verified recovery email resets once, revokes old sessions, and keeps enumeration safe", async ({ browser, page }) => {
  const account = `${prefix}recovery`.toLowerCase().slice(0, 60);
  const email = `${account}@example.test`;
  await page.goto("/register");
  await page.getByLabel("账号").fill(account);
  await page.getByLabel("显示名称").fill("Recovery Author");
  await page.getByLabel("恢复邮箱").fill(email);
  await page.getByLabel("密码", { exact: true }).fill("valid-password-13");
  await page.getByRole("button", { name: "创建账号" }).click();
  await expect(page).toHaveURL("/");
  const verifyMail = await capturedMail(page.request, "verify_email");
  await page.goto(`${verifyMail.path}#token=${verifyMail.token}`);
  await expect.poll(() => page.evaluate(() => window.location.hash)).toBe("");
  await expect(page.getByText("恢复邮箱已验证，可用于密码找回。")).toBeVisible();
  const oldContext = await browser.newContext({ baseURL: origin });
  expect((await oldContext.request.post("/api/auth/login", { headers: mutation(), data: { account_name: account, password: "valid-password-13" } })).status()).toBe(200);
  const unknown = await page.request.post("/api/auth/password-reset/request", { headers: mutation(), data: { recovery_email: `${account}-unknown@example.test` } });
  const known = await page.request.post("/api/auth/password-reset/request", { headers: mutation(), data: { recovery_email: email } });
  expect(unknown.status()).toBe(202);
  expect(known.status()).toBe(202);
  expect((await unknown.json()).data).toEqual((await known.json()).data);
  const resetMail = await capturedMail(page.request, "password_reset");
  await page.goto(`${resetMail.path}#token=${resetMail.token}`);
  await expect.poll(() => page.evaluate(() => window.location.hash)).toBe("");
  await page.getByLabel("新密码").fill("new-valid-password-13");
  await page.getByRole("button", { name: "更新密码" }).click();
  await expect(page.getByText(/所有旧会话均已撤销/)).toBeVisible();
  expect((await oldContext.request.get("/api/home")).status()).toBe(401);
  const replay = await page.request.post("/api/auth/password-reset/confirm", { headers: mutation(), data: { token: resetMail.token, password: "another-valid-password-13" } });
  expect(replay.status()).toBe(400);
  expect((await replay.json()).error.code).toBe("recovery_token_invalid");
  expect((await page.request.post("/api/auth/login", { headers: mutation(), data: { account_name: account, password: "valid-password-13" } })).status()).toBe(401);
  expect((await page.request.post("/api/auth/login", { headers: mutation(), data: { account_name: account, password: "new-valid-password-13" } })).status()).toBe(200);
  const invalidContext = await browser.newContext({ baseURL: origin });
  const invalidPage = await invalidContext.newPage();
  await invalidPage.goto(`/password-reset/confirm#token=${"x".repeat(48)}`);
  await expect.poll(() => invalidPage.evaluate(() => window.location.hash)).toBe("");
  await invalidPage.getByLabel("新密码").fill("another-valid-password-13");
  await invalidPage.getByRole("button", { name: "更新密码" }).click();
  await expect(invalidPage.locator(".inline-error")).toBeVisible();
  expect(await invalidPage.evaluate(() => window.location.hash)).toBe("");
  await invalidPage.goto(`/verify-email#token=${"y".repeat(48)}`);
  await expect.poll(() => invalidPage.evaluate(() => window.location.hash)).toBe("");
  await expect(invalidPage.locator(".inline-error")).toBeVisible();
  expect(await invalidPage.evaluate(() => window.location.hash)).toBe("");
  await invalidContext.close();
  await oldContext.close();
});

test("Stage 12 lifecycle and incremental pair remain atomic through the Stage 13 app", async ({ browser }) => {
  const context = await browser.newContext({ baseURL: origin });
  const author = await register(context, "lifecycle");
  const projectId = author.seeded_projects[0].id;
  let draft = await projectDraft(context, projectId);
  const runFor = async (body: string) => {
    const saved = await data<{ revision: number }>(await context.request.patch(`/api/projects/${projectId}/drafts/${draft.id}`, {
      headers: idempotency(), data: { base_revision: draft.revision, title: "Stage 13 lifecycle", body },
    }));
    draft = { ...draft, revision: saved.revision };
    const created = await data<{ run_id: string }>(await context.request.post(`/api/projects/${projectId}/checks`, {
      headers: idempotency(), data: { draft_id: draft.id, draft_revision: draft.revision },
    }));
    return waitRun(context, projectId, created.run_id);
  };
  expect((await runFor("普通完成路径。" )).status).toBe("completed");
  const blockedDraft = await data<{ revision: number }>(await context.request.patch(`/api/projects/${projectId}/drafts/${draft.id}`, {
    headers: idempotency(), data: { base_revision: draft.revision, title: "Stage 13 cancel", body: "STAGE13_BLOCK" },
  }));
  draft = { ...draft, revision: blockedDraft.revision };
  const blockedRun = await data<{ run_id: string }>(await context.request.post(`/api/projects/${projectId}/checks`, {
    headers: idempotency(), data: { draft_id: draft.id, draft_revision: draft.revision },
  }));
  let observedBlocked = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if ((await (await context.request.get("/api/test/stage13/stats")).json()).blocked) { observedBlocked = true; break; }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  expect(observedBlocked).toBeTruthy();
  await data(await context.request.post(`/api/projects/${projectId}/checks/${blockedRun.run_id}/cancel`, { headers: idempotency(), data: {} }));
  await context.request.post("/api/test/stage13/release");
  expect((await waitRun(context, projectId, blockedRun.run_id)).status).toBe("cancelled");
  const timedOut = await runFor("STAGE13_TIMEOUT");
  expect([timedOut.status, timedOut.error_code]).toEqual(["timed_out", "provider_timeout"]);
  const failed = await runFor("STAGE13_FAIL_ONCE");
  expect(failed.status).toBe("failed");
  const retried = await data<{ run: { run_id: string } }>(await context.request.post(`/api/projects/${projectId}/checks/${failed.run_id}/retry`, { headers: idempotency(), data: {} }));
  expect((await waitRun(context, projectId, retried.run.run_id)).status).toBe("completed");

  const importPreview = await data<{ import_id: string; detected: { chapters: { preview_id: string }[] } }>(await context.request.post("/api/imports/preview", {
    headers: idempotency(), multipart: { file: { name: "incremental.md", mimeType: "text/markdown", buffer: Buffer.from("# 第一章\n潮汐门清晨开启。", "utf8") } },
  }));
  const imported = await data<{ project: { id: string } }>(await context.request.post(`/api/imports/${importPreview.import_id}/commit`, {
    headers: idempotency(), data: { confirm: true, title: "增量作品", chapter_preview_ids: importPreview.detected.chapters.map((item) => item.preview_id) },
  }));
  const importedId = imported.project.id;
  const initialized = await data<{ initialization: { id: string; candidates: { id: string }[] } }>(await context.request.post(`/api/projects/${importedId}/memory/initializations?view=full`, {
    headers: idempotency(), data: { source_revision: 1 },
  }));
  for (const candidate of initialized.initialization.candidates) {
    await data(await context.request.post(`/api/projects/${importedId}/memory/initializations/${initialized.initialization.id}/candidates/${candidate.id}/decision?view=compact`, {
      headers: idempotency(), data: { decision: "accepted" },
    }));
  }
  await data(await context.request.post(`/api/projects/${importedId}/memory/initializations/${initialized.initialization.id}/commit?view=compact`, { headers: idempotency(), data: { confirm: true } }));
  const append = await data<{ source_change_set: { id: string; content_sha256: string } }>(await context.request.post(`/api/projects/${importedId}/source-change-sets/preview`, {
    headers: idempotency(), data: { mode: "append", input_method: "paste", base_source_revision: 1, content: "# 第二章\n银钥匙交给守塔人。" },
  }));
  await data(await context.request.post(`/api/projects/${importedId}/source-change-sets/${append.source_change_set.id}/commit`, {
    headers: idempotency(), data: { confirm: true, content_sha256: append.source_change_set.content_sha256 },
  }));
  const pair = await data<{ continuity_run_id: string; memory_delta_run_id: string }>(await context.request.post(`/api/projects/${importedId}/incremental-reviews`, {
    headers: idempotency(), data: { source_revision: 2 },
  }));
  const statuses = await Promise.all([pair.continuity_run_id, pair.memory_delta_run_id].map(async (runId) => (await waitRun(context, importedId, runId)).status));
  expect(statuses).toEqual(["completed", "completed"]);
  const stats = await (await context.request.get("/api/test/stage13/stats")).json();
  expect(stats.provider_http_calls).toBe(0);
  expect(stats.smtp_external_calls).toBe(0);
  await writeFile(path.join(harness.outputDir, "external-call-counts.json"), JSON.stringify({
    provider_http_calls: stats.provider_http_calls,
    smtp_external_calls: stats.smtp_external_calls,
  }, null, 2));
  await context.close();
});
