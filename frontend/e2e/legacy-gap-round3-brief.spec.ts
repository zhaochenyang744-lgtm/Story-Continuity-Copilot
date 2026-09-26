import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";

const frontendOrigin = "http://127.0.0.1:3239";
const backendOrigin = "http://127.0.0.1:8239";
if (process.env.E2E_BASE_URL !== frontendOrigin || process.env.E2E_BACKEND_ORIGIN !== backendOrigin || !process.env.E2E_ACCOUNT_PREFIX?.startsWith("gapg02r3")) {
  throw new Error("G02 R3 requires the isolated 3239/8239 runner and gapg02r3 accounts");
}
type Source = { source_type: string; source_id: string; excerpt: string };
type Run = { run_id: string; status: string; analysis: {
  evidence_status: string; summary: string; items: { text: string; sources: Source[] }[];
  draft_coverage: { status: string; reasons: string[]; discarded_item_indices: number[] };
} };
type FixtureCall = { mode: string; project_id: string; claim_ids: string[]; payload: { items: { text: string; sources: Source[] }[] } };

async function read<T>(page: Page, url: string): Promise<T> {
  const response = await page.request.get(url);
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()).data as T;
}
async function stats(page: Page) {
  const response = await page.request.get(`${backendOrigin}/api/test/stage12/stats`);
  expect(response.ok()).toBe(true);
  const value = await response.json();
  expect(value.provider_mode).toBe("injected_stub");
  expect(value.external_provider_http_enabled).toBe(false);
  expect(value.provider_http_calls).toBe(0);
  expect(value.test_root).toContain("story-v130-rc-g02-r3-");
  return value;
}
async function prepare(page: Page, mode: "cycle" | "valid") {
  const account = `${process.env.E2E_ACCOUNT_PREFIX}${mode}${Date.now()}${randomUUID().slice(0, 5)}`;
  await page.goto("/register");
  await page.getByLabel("账号", { exact: true }).fill(account);
  await page.getByLabel("显示名称").fill("G02 第三轮验收作者");
  await page.getByLabel("恢复邮箱").fill(`${account}@example.test`);
  await page.locator('input[name="password"]').fill(`safe-${randomUUID()}`);
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "作品管理", exact: true }).click();
  await page.getByRole("button", { name: "新建作品", exact: true }).first().click();
  await page.getByRole("textbox", { name: /作品名称/ }).fill(`G02 引用${mode === "cycle" ? "错配" : "正控"}`);
  await page.getByRole("button", { name: "创建并进入作品", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/overview$/);
  const projectId = page.url().match(/\/projects\/([^/]+)\//)![1];
  const plan = await page.request.post(`/api/projects/${projectId}/author-intent/story-plans`, {
    headers: { "Idempotency-Key": randomUUID() },
    data: { base_author_context_version: 0, title: "温岚调查灯塔", summary: "核对灯塔线索。", goal: "确认记录。", status: "planned", target_chapter_number: 1 },
  });
  expect(plan.status(), await plan.text()).toBe(201);
  await page.getByRole("button", { name: "写作与检查", exact: true }).click();
  await expect(page.locator(".workspace-grid")).toBeVisible();
  const marker = mode === "cycle" ? "E2E_G02_R3_CYCLE" : "E2E_G02_R3_VALID";
  const body = `${marker} 温岚走进东门。黄铜罗盘已经交给许青。灯塔今晚停止点灯。`;
  await page.locator("#draft-body").fill(body);
  await page.getByRole("button", { name: "保存草稿", exact: true }).click();
  await expect(page.getByRole("status").getByText(/草稿已保存于/)).toBeVisible();
  return { account, projectId, body };
}
async function capture(page: Page, info: TestInfo, name: string) {
  await page.screenshot({ path: info.outputPath(`${name}.png`), fullPage: true, animations: "disabled" });
}

for (const mode of ["cycle", "valid"] as const) {
  test(`G02 round3 real validator ${mode} citations survive refresh with correct disclosure`, async ({ page }, info) => {
    await page.setViewportSize({ width: 1440, height: 960 });
    const pageErrors: string[] = [];
    const externalRequests: string[] = [];
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.context().route("**/*", async route => {
      const url = new URL(route.request().url());
      if (["http:", "https:"].includes(url.protocol) && ![frontendOrigin, backendOrigin].includes(url.origin)) {
        externalRequests.push(url.href);
        await route.abort("blockedbyclient");
      } else await route.continue();
    });
    const before = await stats(page);
    const wrapper = await (await page.request.get(`${backendOrigin}/api/test/round3/brief-fixtures`)).json();
    expect(wrapper.wrapper).toBe("g02-round3-real-validator-v1");
    const prepared = await prepare(page, mode);
    const createdPromise = page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith(`/api/projects/${prepared.projectId}/analyses`));
    await page.getByRole("button", { name: "生成章节简报", exact: true }).click();
    const createdResponse = await createdPromise;
    expect(createdResponse.status()).toBe(202);
    const created = (await createdResponse.json()).data as Run;
    const runUrl = `/api/projects/${prepared.projectId}/analyses/${created.run_id}`;
    await expect.poll(async () => (await read<Run>(page, runUrl)).status, { timeout: 20000 }).toBe("completed");
    const run = await read<Run>(page, runUrl);
    const fixtures = await (await page.request.get(`${backendOrigin}/api/test/round3/brief-fixtures`)).json();
    const calls = (fixtures.calls as FixtureCall[]).filter(call => call.project_id === prepared.projectId);
    expect(calls).toHaveLength(1);
    const call = calls[0];
    expect(call.mode).toBe(mode);
    expect(call.claim_ids).toHaveLength(3);
    for (let index = 0; index < 3; index++) {
      expect(call.payload.items[index].sources[0].source_id).toBe(call.claim_ids[mode === "cycle" ? (index + 1) % 3 : index]);
    }
    const brief = page.locator('.writing-analysis-result[aria-label="章节简报结果"]');
    const mismatch = /有\s*3\s*条简报内容引用错配，已从结果移除/;
    const checkUi = async () => {
      await expect(brief).toBeVisible();
      if (mode === "cycle") {
        await expect(brief.getByRole("status")).toContainText("当前已保存草稿：部分覆盖");
        await expect(brief.getByRole("status")).toContainText(mismatch);
        await expect(brief).not.toContainText("G02R3模型分项：");
        await expect(brief.locator(".analysis-items > li")).toHaveCount(1);
      } else {
        await expect(brief.getByRole("status")).toContainText("当前已保存草稿：全部选入主张已引用");
        await expect(brief).not.toContainText("引用错配");
        await expect(brief).not.toContainText("部分覆盖");
        await expect(brief.locator(".analysis-items > li")).toHaveCount(3);
      }
      await brief.getByRole("status").scrollIntoViewIfNeeded();
      await expect(brief.getByRole("status")).toBeInViewport();
    };
    if (mode === "cycle") {
      expect(run.analysis.evidence_status).toBe("partial");
      expect(run.analysis.draft_coverage.status).toBe("partial");
      expect(run.analysis.draft_coverage.reasons).toContain("draft_item_citation_mismatch");
      expect(run.analysis.draft_coverage.discarded_item_indices).toEqual([0, 1, 2]);
      expect(run.analysis.items).toHaveLength(1);
      expect(run.analysis.items[0].sources[0].source_id).toBe(call.claim_ids[0]);
      expect(JSON.stringify(run.analysis)).not.toContain("G02R3模型分项：");
    } else {
      expect(run.analysis.evidence_status).toBe("supported");
      expect(run.analysis.draft_coverage.status).toBe("covered");
      expect(run.analysis.draft_coverage.reasons).toEqual([]);
      expect(run.analysis.draft_coverage.discarded_item_indices).toEqual([]);
      expect(run.analysis.items).toHaveLength(3);
      expect(run.analysis.items.map(item => item.sources[0].source_id)).toEqual(call.claim_ids);
    }
    await checkUi();
    await capture(page, info, `${mode}-before-refresh`);
    await page.reload({ waitUntil: "networkidle" });
    await checkUi();
    const refreshed = await read<Run>(page, runUrl);
    expect(refreshed.run_id).toBe(run.run_id);
    expect(refreshed.analysis).toEqual(run.analysis);
    await capture(page, info, `${mode}-after-refresh`);
    const after = await stats(page);
    expect(pageErrors).toEqual([]);
    expect(externalRequests).toEqual([]);
    await writeFile(info.outputPath("brief-validator-evidence.json"), JSON.stringify({ mode, ...prepared, before, after, call, run, refreshed, pageErrors, externalRequests }, null, 2) + "\n");
  });
}
