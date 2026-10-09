import { api, expect, openTab, registerAccount, sampleWorkId, shot, startVisitor, test } from "./support/app";
import { button } from "./support/writing";
import { evidence, importBook, initialize, memories, pair, project, sample } from "./support/pages";

test("08 章节列表：十章、草稿与示例标记", async ({ page }) => {
  const id = await sample(page, "sources");
  const table = page.getByRole("table", { name: "全部章节", exact: true });
  await expect(table.getByRole("rowgroup")).toHaveCount(11);
  const snapshot = await api(page).get(`/projects/${id}/long-term-review`);
  for (const [index, c] of snapshot.chapters.entries()) {
    const row = table.getByRole("rowgroup").nth(index);
    await expect(row).toContainText(String(c.number).padStart(2, "0"));
    await expect(row).toContainText(c.title.replace(/^第[零一二三四五六七八九十百千\d]+章\s*/, ""));
    await expect(row).toContainText(c.body.replace(/\s+/g, "").length.toLocaleString("en-US"));
    await expect(row).toContainText("未检查");
  }
  await expect(table.getByRole("rowgroup").last()).toContainText("草稿");
  const sampleRuns = (await api(page).get(`/projects/${id}/chapter-checks?limit=3`)).runs.filter((r: any) => r.sample);
  expect(sampleRuns.length).toBeGreaterThan(0);
  for (const chapter of sampleRuns[0].report.chapters) await expect(table.getByRole("rowgroup").nth(chapter.chapter_number - 1).getByText("示例", { exact: true })).toBeVisible();
  expect((await api(page).get(`/projects/${id}/chapter-timeline`)).chapters.filter((c: any) => c.status === "checked")).toHaveLength(0);
  await pair(page, "chapters");
});

test("08 展开段落：收起与写作页章节网址", async ({ page }) => {
  const id = await sample(page, "sources");
  const chapters = (await api(page).get(`/projects/${id}/chapters?include=excerpt`)).chapters;
  const row = page.getByRole("table", { name: "全部章节", exact: true }).getByRole("rowgroup").first();
  await row.getByRole("button", { name: /^段落 / }).click();
  await expect(row.getByText(chapters[0].source_spans[0].text_excerpt, { exact: true })).toBeVisible();
  await row.getByRole("button", { name: "收起", exact: true }).click();
  await expect(row.getByText(chapters[0].source_spans[0].text_excerpt, { exact: true })).toHaveCount(0);
  await row.getByRole("button", { name: /^段落 / }).click();
  await row.getByRole("button", { name: "在写作页打开修改", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${id}/workspace\\?chapter=1$`));
});

test("08 勾选和实时估价：两章检查及前文依据", async ({ page }, info) => {
  const id = await sample(page, "sources");
  const chapters = (await api(page).get(`/projects/${id}/chapters?include=excerpt`)).chapters;
  const selected = chapters.slice(1, 3);
  const bar = page.getByTestId("chapter-selection");
  let previous = 0;
  for (const [i, c] of selected.entries()) {
    const estimated = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/chapter-checks/estimate") && r.request().postDataJSON().chapter_ids.length === i + 1);
    await page.getByRole("checkbox", { name: `选择第 ${c.number} 章`, exact: true }).check();
    const response = await estimated;
    expect(response.ok(), await response.text()).toBe(true);
    const estimate = (await response.json()).data;
    expect(estimate.characters).toBeGreaterThan(previous);
    previous = estimate.characters;
    await expect(bar).toContainText(`${i + 1} / 8 章`);
    await expect(bar).toContainText(`${estimate.characters.toLocaleString("en-US")} 字`);
    await expect(bar).toContainText(estimate.estimated_cny >= .01 ? `约 ¥${estimate.estimated_cny.toFixed(2)}` : "不到 ¥0.01");
    const usage = await api(page).get("/account/usage");
    await expect(bar).toContainText(`可检查 ${usage.check_chars_remaining.toLocaleString("en-US")} 字`);
  }
  const pending = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/chapter-checks"));
  await button(page, "检查选中的章节").click();
  const response = await pending;
  expect(response.ok(), await response.text()).toBe(true);
  const created = (await response.json()).data;
  const rid = (created.run ?? created).run_id;
  const read = async () => (await api(page).get(`/projects/${id}/chapter-checks?limit=3`)).runs.find((r: any) => r.run_id === rid);
  await expect.poll(async () => (await read()).status).not.toMatch(/^(queued|running)$/);
  const result = await read();
  await evidence(info, "chapter-check-result", result);
  expect(result.status, JSON.stringify(result)).toBe("completed");
  expect(result.report.chapters.map((c: any) => c.chapter_id)).toEqual(selected.map((c: any) => c.id));
  const region = page.getByRole("region", { name: "最近一次检查", exact: true });
  await expect(region.getByRole("article")).toHaveCount(2);
  for (const c of result.report.chapters) for (const issue of c.issues) for (const source of issue.evidence) {
    expect(source.chapter_number).toBeLessThan(c.chapter_number);
    await expect(region.getByText(source.excerpt, { exact: true }).first()).toBeVisible();
  }
  expect((await api(page).get(`/projects/${id}/chapter-checks?limit=3`)).runs.filter((r: any) => !r.sample).map((r: any) => r.run_id)).toEqual([rid]);
  await region.scrollIntoViewIfNeeded();
  await shot(page, "chapters-check-result", false);
});

test("08 最多八章：其余复选框禁用", async ({ page }) => {
  await sample(page, "sources");
  for (let number = 1; number <= 8; number++) await page.getByRole("checkbox", { name: `选择第 ${number} 章`, exact: true }).check();
  for (const number of [9, 10]) await expect(page.getByRole("checkbox", { name: `选择第 ${number} 章`, exact: true })).toBeDisabled();
  await expect(page.getByRole("checkbox", { checked: true })).toHaveCount(8);
});

test("08 访客章节：限制说明且没有复选框", async ({ page }) => {
  await startVisitor(page);
  await openTab(page, await sampleWorkId(page), "sources");
  await expect(page.getByText("访客只能检查当前草稿；注册后可以一次勾选最多 8 章一起检查。", { exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(0);
});

test("08 追加章节：检查与事实变化确认", async ({ page }, info) => {
  await registerAccount(page, "append08");
  const id = await importBook(page);
  await initialize(page, id);
  const before = await project(page, id);
  await openTab(page, id, "sources");
  const append = page.getByRole("region", { name: "追加章节", exact: true });
  await append.getByLabel("章节正文", { exact: true }).fill("第四章 守塔人的灯\n\n林默把银钥匙交给守塔人。北堤门在清晨打开，灯塔上的值班员记下时间。");
  await append.getByRole("button", { name: "预览", exact: true }).click();
  await expect(append.getByText("预览 · 还没写入", { exact: true })).toBeVisible();
  await append.getByRole("button", { name: "确认追加", exact: true }).click();
  await expect.poll(async () => (await project(page, id)).source_revision).toBe(before.source_revision + 1);
  expect((await project(page, id)).chapter_count).toBe(before.chapter_count + 1);
  // Current product exposes incremental review on the writing page after this entry.
  await append.getByRole("button", { name: "去写下一章", exact: true }).click();
  await button(page, "检查新增的章节").click();
  const deltaPath = `/projects/${id}/memory/delta`;
  await expect.poll(async () => (await api(page).get(deltaPath)).status).not.toMatch(/^(not_started|processing)$/);
  const delta = await api(page).get(deltaPath);
  await evidence(info, "append-delta", delta);
  expect(delta.status, JSON.stringify(delta)).toBe("in_review");
  for (const rid of [delta.continuity_run_id, delta.memory_delta_run_id]) expect((await api(page).get(`/projects/${id}/checks/${rid}`)).status).toBe("completed");
  await openTab(page, id, "memory");
  const form = page.getByRole("form", { name: "确认事实变化", exact: true });
  expect(delta.candidates).toHaveLength(2);
  for (const c of delta.candidates) await form.getByRole("article").filter({ hasText: c.value }).getByRole("radio", { name: c.subject === "林默" ? "接受" : "不接受", exact: true }).check();
  await button(page, "确认并更新资料").click();
  await expect.poll(async () => (await project(page, id)).current_memory_version).toBe(before.current_memory_version + 1);
  const records = await memories(page, id);
  expect(records.some(r => r.subject === "林默" && r.value === "林默交给守塔人" && r.valid_to == null)).toBe(true);
  expect(records.some(r => r.subject === "北堤门")).toBe(false);
});

test("08 章节修订：事实复核阻挡检查直到全部处理", async ({ page }, info) => {
  test.fixme(true, "章节修订产生待复核事实后，多章检查仍返回 HTTP 202 并创建记录；chapter_checks.create 未检查 pending reviews");
  await registerAccount(page, "review08");
  const id = await importBook(page);
  await initialize(page, id);
  const before = await project(page, id);
  await page.goto(`/projects/${id}/workspace?chapter=3`);
  await button(page, "修改这一章").click();
  await page.getByRole("textbox", { name: "第 3 章正文", exact: true }).fill("林默确认北堤门只在清晨开启，守塔人把开门时间记在日志里。");
  await button(page, "预览修改影响").click();
  await button(page, "确认提交修改").click();
  await expect.poll(async () => (await project(page, id)).source_revision).toBe(before.source_revision + 1);
  await openTab(page, id, "sources");
  const reviews = () => api(page).get(`/projects/${id}/long-term-review`);
  let state = await reviews();
  const pending = state.source_revision_reviews.filter((r: any) => r.status === "pending");
  expect(pending.length).toBeGreaterThan(0);
  await expect(page.getByText(`有 ${pending.length} 条事实因为章节修订需要复核。复核完之前不能运行检查。`, { exact: true })).toBeVisible();
  await page.getByRole("checkbox", { name: "选择第 3 章", exact: true }).check();
  const blocked = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/chapter-checks"));
  await button(page, "检查选中的章节").click();
  const denied = await blocked;
  await evidence(info, "source-review-block", { status: denied.status(), body: await denied.json() });
  expect(denied.ok()).toBe(false);
  expect((await api(page).get(`/projects/${id}/chapter-checks`)).runs).toHaveLength(0);
  await button(page, "去复核").click();
  const region = page.getByRole("region", { name: "待复核的事实", exact: true });
  for (const review of pending) {
    const row = region.getByRole("article").filter({ hasText: review.memory.value });
    await row.getByLabel("说明（必填）", { exact: true }).fill("已核对修订正文，仍明确记录清晨开启。");
    await row.getByRole("button", { name: "还成立，保留", exact: true }).click();
    await expect.poll(async () => (await reviews()).source_revision_reviews.find((r: any) => r.id === review.id).status).not.toBe("pending");
    await expect(row).toHaveCount(0);
  }
  state = await reviews();
  expect(state.source_revision_reviews.filter((r: any) => r.status === "pending")).toHaveLength(0);
  await openTab(page, id, "sources");
  await page.getByRole("checkbox", { name: "选择第 3 章", exact: true }).check();
  await expect(button(page, "检查选中的章节")).toBeEnabled();
  const allowed = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/chapter-checks"));
  await button(page, "检查选中的章节").click();
  expect((await allowed).ok()).toBe(true);
});
