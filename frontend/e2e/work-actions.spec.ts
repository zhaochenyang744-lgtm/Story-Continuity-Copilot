import { readFile } from "node:fs/promises";
import { api, createWorkByApi, decideFirstFinding, expect, openTab, registerAccount, sampleCheck, tabOrder, tempFile, test } from "./support/app";
import { button, draft, saveBody, setup } from "./support/writing";
import { intent, memories, noWriteControls, pair, project, sample, workMenu } from "./support/pages";

test("08 编辑作品信息：标题类型简介同步", async ({ page }) => {
  await registerAccount(page, "meta08");
  const id = await createWorkByApi(page, { title: "旧书名" });
  await openTab(page, id, "overview");
  await workMenu(page, "编辑作品信息");
  const d = page.getByRole("dialog", { name: "编辑作品信息", exact: true });
  for (const [label, value] of [["书名", "新的潮汐"], ["类型", "科幻"], ["简介", "一次关于潮水的测试旅程。"]]) await d.getByLabel(label, { exact: true }).fill(value);
  await d.getByRole("button", { name: "保存", exact: true }).click();
  await expect(d).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1, name: "新的潮汐", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "更换当前作品：新的潮汐", exact: true })).toBeVisible();
  expect(await project(page, id)).toMatchObject({ title: "新的潮汐", genre: "科幻", summary: "一次关于潮水的测试旅程。" });
});

test("08 归档恢复作品：五页只读与恢复编辑", async ({ page }) => {
  await registerAccount(page, "archive08");
  const id = await createWorkByApi(page, { title: "归档的灯塔" });
  await openTab(page, id, "workspace");
  await saveBody(page, id, "值班员在码头点亮了灯。");
  const initial = await draft(page, id), plans = await intent(page, id);
  await api(page).post(`/projects/${id}/author-intent/story-plans`, { base_author_context_version: plans.author_context_version, title: "回来点灯", summary: "他会回来。", goal: "", status: "planned", target_chapter_number: 2 });
  expect((await intent(page, id)).story_plans).toHaveLength(1);
  await openTab(page, id, "overview");
  await workMenu(page, "归档作品");
  await page.getByRole("dialog", { name: "归档作品", exact: true }).getByRole("button", { name: "归档", exact: true }).click();
  await expect.poll(async () => (await project(page, id)).status).toBe("archived");
  for (const tab of tabOrder) {
    await openTab(page, id, tab);
    await expect(page.getByText("这部作品已归档，只能浏览。恢复后才能保存、检查和处理。", { exact: true })).toBeVisible();
    await noWriteControls(page, /^(保存|检查这一章|再检查一次|新建计划|检查选中的章节)$/);
    if (tab === "workspace") {
      await expect(page.getByRole("textbox", { name: "草稿正文（只读）", exact: true })).toHaveAttribute("contenteditable", "false");
      await pair(page, "archived-writing");
    }
  }
  expect((await draft(page, id)).body).toBe(initial.body);
  await openTab(page, id, "overview");
  await workMenu(page, "恢复作品");
  await page.getByRole("dialog", { name: "恢复作品", exact: true }).getByRole("button", { name: "恢复作品", exact: true }).click();
  await expect.poll(async () => (await project(page, id)).status).toBe("active");
  await openTab(page, id, "plan");
  await expect(button(page, "新建计划")).toBeEnabled();
  await openTab(page, id, "workspace");
  await expect(page.getByRole("textbox", { name: "草稿正文", exact: true })).toHaveAttribute("contenteditable", "true");
  await expect(button(page, "检查这一章")).toBeEnabled();
  await saveBody(page, id, "值班员在码头点亮了灯。恢复后继续写作。");
});

test("08 重置示例作品：草稿结果恢复和决定清空", async ({ page }) => {
  const id = await setup(page), original = await draft(page, id), initial = await sampleCheck(page, id);
  await decideFirstFinding(page, id, "false_positive");
  expect((await sampleCheck(page, id)).issues[0].decision).toBeTruthy();
  await saveBody(page, id, `${original.body}\n测试重置前的草稿变化。`);
  await openTab(page, id, "overview");
  await workMenu(page, "重置作品");
  const d = page.getByRole("dialog", { name: "重置作品", exact: true });
  await expect(d).toContainText("示例的初始状态：章节、已确认的事实、草稿和示例检查结果都恢复。");
  await d.getByRole("button", { name: "确认重置", exact: true }).click();
  await expect(d).toHaveCount(0);
  expect((await draft(page, id)).body).toBe(original.body);
  const restored = await sampleCheck(page, id);
  expect(restored.issues.map((i: any) => i.claim_text)).toEqual(initial.issues.map((i: any) => i.claim_text));
  expect(restored.issues.every((i: any) => !i.decision)).toBe(true);
  expect(restored.result_origin).toBe(initial.result_origin);
});

test("08 重置新建作品：资料与草稿回到初始状态", async ({ page }) => {
  const id = await setup(page, false), original = await draft(page, id);
  const c = await intent(page, id);
  await api(page).post(`/projects/${id}/author-intent/story-plans`, { base_author_context_version: c.author_context_version, title: "重置前计划", summary: "出港", goal: "", status: "planned" });
  expect((await intent(page, id)).story_plans).toHaveLength(1);
  await saveBody(page, id, "新建作品中的测试正文。");
  await openTab(page, id, "overview");
  await workMenu(page, "重置作品");
  const d = page.getByRole("dialog", { name: "重置作品", exact: true });
  await expect(d).toContainText("刚创建时的样子：资料清空，草稿回到初始状态。");
  await d.getByRole("button", { name: "确认重置", exact: true }).click();
  await expect(d).toHaveCount(0);
  expect((await draft(page, id)).body).toBe(original.body);
  expect(await memories(page, id)).toEqual([]);
  expect((await intent(page, id)).story_plans).toEqual([]);
  expect((await project(page, id)).latest_run).toBeNull();
});

test("08 导出作品：三种文件和草稿开关", async ({ page }) => {
  const id = await sample(page), saved = await draft(page, id);
  const chapters = (await api(page).get(`/projects/${id}/long-term-review`)).chapters;
  await workMenu(page, "导出作品");
  const d = page.getByRole("dialog", { name: "导出作品", exact: true });
  const marker = saved.body.split("\n").find((s: string) => s.trim() && !chapters.some((c: any) => c.body.includes(s)))!;
  expect(marker).toBeTruthy();
  for (const [label, extension] of [["完整资料包", "zip"], ["正文 TXT", "txt"], ["正文 Markdown", "md"], ["正文 TXT", "txt"]]) {
    await d.getByRole("radio", { name: new RegExp(`^${label}`) }).check();
    const include = label === "正文 TXT" && await d.getByRole("checkbox").isChecked();
    const event = page.waitForEvent("download");
    await d.getByRole("button", { name: "下载", exact: true }).click();
    const download = await event;
    expect(download.suggestedFilename()).toMatch(new RegExp(`\\.${extension}$`));
    const output = await tempFile(download.suggestedFilename(), "");
    await download.saveAs(output);
    const bytes = await readFile(output);
    expect(bytes.length).toBeGreaterThan(0);
    if (extension === "zip") expect(bytes.subarray(0, 2).toString()).toBe("PK");
    if (extension === "txt") {
      expect(bytes.toString("utf8")).toContain(chapters[0].title);
      if (include) expect(bytes.toString("utf8")).toContain(marker);
      else expect(bytes.toString("utf8")).not.toContain(marker);
      await d.getByRole("checkbox").check();
    }
  }
});
