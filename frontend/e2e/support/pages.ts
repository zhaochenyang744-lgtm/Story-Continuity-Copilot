import type { Locator, Page, TestInfo } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { api, expect, fixturePath, openTab, registerAccount, sampleWorkId, shot, type Tab } from "./app";
import { button } from "./writing";

export const project = (page: Page, id: string) => api(page).get(`/projects/${id}`);
export const intent = (page: Page, id: string) => api(page).get(`/projects/${id}/author-intent?include_archived=true`);
export const memories = async (page: Page, id: string) => (await api(page).get(`/projects/${id}/memory`)).records as any[];
export async function sample(page: Page, tab: Tab = "overview") {
  await registerAccount(page, "pages08");
  const id = await sampleWorkId(page);
  await openTab(page, id, tab);
  return id;
}
export async function theme(page: Page, value: "day" | "night") {
  if (await page.locator("html").getAttribute("data-theme") !== value)
    await button(page, value === "night" ? "切换到夜间模式" : "切换到日间模式").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", value);
}
export async function pair(page: Page, name: string) {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await theme(page, "day");
  await shot(page, `${name}-day`, false);
  await theme(page, "night");
  await shot(page, `${name}-night`, false);
  await theme(page, "day");
}
export async function evidence(info: TestInfo, name: string, data: unknown) {
  const root = process.env.E2E_OUTPUT_DIR;
  if (!root) throw new Error("E2E_OUTPUT_DIR is required");
  const file = path.join(root, "observations", `${name}.json`);
  await mkdir(path.dirname(file), { recursive: true });
  await writeFile(file, JSON.stringify(data, null, 2));
  await info.attach(name, { path: file, contentType: "application/json" });
}
export async function workMenu(page: Page, action: string) {
  await page.getByLabel("更多：导出、编辑信息、归档", { exact: true }).click();
  await page.getByRole("menuitem", { name: action, exact: true }).click();
}
export async function importBook(page: Page, file = fixturePath("stage9-mist-harbor.md"), title = "测试雾港") {
  await page.goto("/projects/import");
  const chooser = page.waitForEvent("filechooser");
  await page.getByTestId("import-dropzone").getByRole("button", { name: "选择文件", exact: true }).click();
  await (await chooser).setFiles(file);
  await button(page, "下一步：检查分章").click();
  await button(page, "分章没问题，下一步").click();
  await page.getByRole("textbox", { name: /^书名/ }).fill(title);
  await button(page, "导入并创建作品").click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/overview$/);
  const id = new URL(page.url()).pathname.split("/")[2];
  expect((await project(page, id)).title).toBe(title);
  return id;
}
/** Fixed candidates: retain Lin Mo's knowledge for the incremental-review fixture. */
export async function initialize(page: Page, id: string, capture = false) {
  await openTab(page, id, "memory");
  await expect(page.getByRole("heading", { name: "从正文整理事实", exact: true })).toBeVisible();
  await button(page, "开始整理").click();
  const form = page.getByRole("form", { name: "确认整理出的事实", exact: true });
  await expect(form).toBeVisible();
  const init = await api(page).get(`/projects/${id}/memory/initialization`);
  expect(init.candidates).toHaveLength(3);
  for (const candidate of init.candidates) {
    const card = form.getByRole("article").filter({ has: page.getByText(candidate.subject, { exact: true }) });
    await expect(card.getByText(candidate.review_priority === "core" ? "重要 · 必须决定" : "次要 · 可以稍后", { exact: true })).toBeVisible();
    const choice = candidate.subject === "林默" ? "接受" : candidate.subject === "银钥匙" ? "不接受" : "改一下再接受";
    await card.getByRole("radio", { name: choice, exact: true }).check();
    if (choice === "改一下再接受") {
      await card.getByRole("textbox", { name: "内容", exact: true }).fill("钟声响起后，所有船只必须停泊在雾港。");
      await card.getByRole("checkbox", { name: "改过的内容仍然有上面这段原文做依据", exact: true }).check();
    }
  }
  if (capture) await pair(page, "materials-init");
  await button(page, "确认，建立第 1 版资料").click();
  await expect.poll(async () => (await api(page).get(`/projects/${id}/memory/initialization`)).status).toBe("committed");
  await expect.poll(async () => (await project(page, id)).current_memory_version).toBe(1);
  const records = await memories(page, id);
  expect(records).toHaveLength(2);
  expect(records).toEqual(expect.arrayContaining([
    expect.objectContaining({ subject: "林默", predicate: "knowledge", value: "北堤门只在清晨开启" }),
    expect.objectContaining({ subject: "雾港钟声", value: "钟声响起后，所有船只必须停泊在雾港。" }),
  ]));
  expect(records.some(r => r.subject === "银钥匙")).toBe(false);
  const after = await api(page).get(`/projects/${id}/memory/initialization`);
  expect(after.candidates.map((c: any) => c.decision_status).sort()).toEqual(["accepted", "edited", "rejected"]);
  return records;
}
export async function view(page: Page, name: string, value: string) {
  await page.getByRole("navigation", { name: "资料分类", exact: true }).getByRole("button", { name: new RegExp(`^${name}(?:\\s|$)`) }).click();
  expect(new URL(page.url()).searchParams.get("view")).toBe(value === "facts" ? null : value);
}
export async function startAnalysis(page: Page, id: string, click: () => Promise<void>) {
  const pending = page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname === `/api/projects/${id}/analyses`);
  await click();
  const response = await pending;
  expect(response.ok(), await response.text()).toBe(true);
  const data = (await response.json()).data;
  const runId = (data.run ?? data).run_id;
  await expect.poll(async () => (await api(page).get(`/projects/${id}/analyses/${runId}`)).status).not.toMatch(/^(queued|running)$/);
  return api(page).get(`/projects/${id}/analyses/${runId}`);
}
export const cardWith = (page: Page, text: string) => page.getByRole("article").filter({ has: page.getByText(text, { exact: true }) });
export async function noWriteControls(scope: Page | Locator, names: RegExp) {
  const controls = scope.getByRole("button", { name: names });
  for (const control of await controls.all()) if (await control.isVisible()) await expect(control).toBeDisabled();
}
