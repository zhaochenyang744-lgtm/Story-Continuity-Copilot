import { api, button, expect, reloadAcceptingUnload, setup, shot, test } from "./support/writing";
import { createWorkByApi } from "./support/app";
import type { Page } from "@playwright/test";
async function chapter(page: Page) {
  const id = await setup(page);
  await page.goto(`/projects/${id}/workspace?chapter=3`);
  await expect(page.getByRole("textbox", { name: "第 3 章正文（只读）", exact: true })).toBeVisible();
  const snapshot = await api(page).get(`/projects/${id}/long-term-review`);
  return { id, snapshot, original: snapshot.chapters.find((c: any) => c.number === 3) };
}
async function edit(page: Page) {
  await button(page, "修改这一章").click();
  await page.getByRole("textbox", { name: "第 3 章正文", exact: true }).press("Control+End");
  await page.keyboard.insertText("测试值班员在门边记下了新的潮水高度。");
}
test("已完成章节阅读：只读与回到草稿", async ({ page }) => {
  const { original } = await chapter(page);
  await expect(page.getByRole("textbox", { name: "第 3 章正文（只读）", exact: true })).toHaveAttribute("contenteditable", "false");
  await expect(page.getByRole("textbox", { name: "第 3 章正文（只读）", exact: true })).toContainText(original.body.split("\n")[0]);
  await expect(page.getByRole("navigation", { name: "章节", exact: true }).getByRole("button", { name: /^03/ })).toHaveAttribute("aria-current", "page");
  await shot(page, "chapter-read");
  await button(page, "回到草稿").click();
  await expect(page).not.toHaveURL(/chapter=/);
  await expect(page.getByRole("textbox", { name: "草稿正文", exact: true })).toBeVisible();
});
test("已完成章节修改并提交：影响、对照与历史", async ({ page }) => {
  const { id, snapshot, original } = await chapter(page);
  const oldSpans = await api(page).get(`/projects/${id}/source-revisions/${snapshot.source_revision}/spans`);
  await edit(page);
  const response = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/revisions/preview"));
  await button(page, "预览修改影响").click();
  const preview = (await (await response).json()).data.revision_preview;
  expect(preview.before.body).toBe(original.body);
  expect(preview.after.body).toContain("测试值班员");
  await expect(page.getByText("条已确认的事实需要复核", { exact: true })).toBeVisible();
  await button(page, "看前后对照").click();
  const dialog = page.getByRole("dialog", { name: "第 3 章 · 前后对照", exact: true });
  await expect(dialog.getByText(preview.before.body, { exact: true })).toBeVisible();
  await expect(dialog.getByText(preview.after.body, { exact: true })).toBeVisible();
  await shot(page, "chapter-preview");
  await dialog.getByRole("button", { name: "关闭", exact: true }).click();
  await button(page, "确认提交修改").click();
  await expect.poll(async () => (await api(page).get(`/projects/${id}`)).source_revision).toBe(snapshot.source_revision + 1);
  const after = await api(page).get(`/projects/${id}/long-term-review`);
  expect(after.chapters.find((c: any) => c.id === original.id).body).toBe(preview.after.body);
  expect(after.chapters.find((c: any) => c.id === original.id).source_revision).toBe(snapshot.source_revision + 1);
  expect(await api(page).get(`/projects/${id}/source-revisions/${snapshot.source_revision}/spans`)).toEqual(oldSpans);
  if (preview.impact.affected_memory_count > 0) await expect(page.getByRole("status").filter({ hasText: "事实需要到章节页复核" })).toBeVisible();
});
test("没改动不能提交：预览按钮禁用", async ({ page }) => {
  const { id, snapshot } = await chapter(page);
  await button(page, "修改这一章").click();
  await expect(button(page, "预览修改影响")).toBeDisabled();
  await expect(page.getByText("还没改动", { exact: true })).toBeVisible();
  expect((await api(page).get(`/projects/${id}`)).source_revision).toBe(snapshot.source_revision);
});
test("本机修改副本：接着改与删除", async ({ page }) => {
  const { id, original } = await chapter(page);
  await edit(page);
  await reloadAcceptingUnload(page);
  await expect(page.getByText("这台设备上有这一章没提交的修改。", { exact: true })).toBeVisible();
  await button(page, "接着改").click();
  await expect(page.getByRole("textbox", { name: "第 3 章正文", exact: true })).toContainText("测试值班员");
  await reloadAcceptingUnload(page);
  await button(page, "删除副本").click();
  await expect(page.getByText("这台设备上有这一章没提交的修改。", { exact: true })).toHaveCount(0);
  expect((await api(page).get(`/projects/${id}/long-term-review`)).chapters.find((c: any) => c.id === original.id).body).toBe(original.body);
  expect(await page.evaluate(projectId => Object.keys(localStorage).filter(k => k.startsWith("story-continuity:chapter-revision:") && k.includes(projectId)), id)).toEqual([]);
});
test("没提交就离开：切换作品提醒与保留副本", async ({ page }) => {
  const { id, original } = await chapter(page);
  const other = await createWorkByApi(page, { title: "另一座测试灯塔" });
  await edit(page);
  await page.getByRole("button", { name: /^更换当前作品：/ }).click();
  const dialog = page.getByRole("dialog", { name: "这一章的修改还没提交", exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "留在这里", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${id}/workspace\\?chapter=3$`));
  await page.getByRole("button", { name: /^更换当前作品：/ }).click();
  await dialog.getByRole("button", { name: "先离开", exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  await page.getByRole("main").getByRole("button", { name: /另一座测试灯塔/ }).first().click();
  await expect(page).toHaveURL(new RegExp(`/projects/${other}/`));
  expect((await api(page).get(`/projects/${id}/long-term-review`)).chapters.find((c: any) => c.id === original.id).body).toBe(original.body);
  await page.goto(`/projects/${id}/workspace?chapter=3`);
  await expect(page.getByText("这台设备上有这一章没提交的修改。", { exact: true })).toBeVisible();
});
