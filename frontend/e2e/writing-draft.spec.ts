import { api, button, draft, expect, failDraftSaves, localDrafts, readDraftBody, reloadAcceptingUnload, saveBody, setDraftBody, setup, shot, test } from "./support/writing";

test("手动保存：段落、空行、revision 和刷新", async ({ page }) => {
  const id = await setup(page, false), before = await draft(page, id);
  const body = "灯塔门口停着一辆小车。\n\n看守把雨衣挂在门后。\n他翻开今天的值班簿。";
  await setDraftBody(page, body);
  await expect(page.getByText("未保存", { exact: true })).toBeVisible();
  await button(page, "保存").click();
  await expect.poll(async () => (await draft(page, id)).revision).toBe(before.revision + 1);
  expect((await draft(page, id)).body).toBe(body);
  await expect(page.getByLabel("草稿第 1 章", { exact: true }).getByText(/^已保存 \d/)).toBeVisible();
  await page.reload();
  expect(await readDraftBody(page)).toBe(body);
});

test("自动保存：输入保持可用且 revision 只加一", async ({ page }) => {
  const id = await setup(page, false), before = await draft(page, id);
  const pattern = "**/api/projects/*/drafts/*";
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route(pattern, async route => {
    if (route.request().method() === "PATCH") await gate;
    await route.continue();
  });
  try {
    await setDraftBody(page, "值班员记下潮水高度。");
    const editor = page.getByRole("textbox", { name: "草稿正文", exact: true });
    await editor.press("End");
    await page.keyboard.insertText("雨停了。");
    expect(await readDraftBody(page)).toBe("值班员记下潮水高度。雨停了。");
    await expect(page.getByText("保存中", { exact: true })).toBeVisible();
    await expect(editor).toHaveAttribute("contenteditable", "true");
    await expect(editor).toBeEditable();
  } finally { release(); await page.unrouteAll({ behavior: "wait" }); }
  await expect.poll(async () => (await draft(page, id)).revision).toBe(before.revision + 1);
  expect((await draft(page, id)).body).toBe("值班员记下潮水高度。雨停了。");
  expect(await readDraftBody(page)).toBe("值班员记下潮水高度。雨停了。");
  await expect(page.getByLabel("草稿第 1 章", { exact: true }).getByText(/^已保存 \d/)).toBeVisible();
});

test("别处保存了更新的版本：自动保存暂停", async ({ page }) => {
  const id = await setup(page, false), before = await draft(page, id);
  await api(page).patch(`/projects/${id}/drafts/${before.id}`, { base_revision: before.revision, title: before.title, body: "另一台设备写下的新记录。" });
  await setDraftBody(page, "本机写下另一份记录。");
  await expect(page.getByText("自动保存已暂停", { exact: true })).toBeVisible();
  expect(await draft(page, id)).toMatchObject({ revision: before.revision + 1, body: "另一台设备写下的新记录。" });
});

test("保存失败，然后恢复本机副本", async ({ page }) => {
  const id = await setup(page, false), before = await draft(page, id);
  const restore = await failDraftSaves(page);
  await setDraftBody(page, "没有传到服务器的潮水记录。");
  await button(page, "保存").click();
  await expect(page.getByText("没保存成功", { exact: true })).toBeVisible();
  await reloadAcceptingUnload(page);
  await expect(page.getByRole("dialog", { name: "这台设备上有没保存的草稿", exact: true })).toBeVisible();
  await shot(page, "writing-recovery");
  await button(page, "恢复本机副本").click();
  expect(await readDraftBody(page)).toBe("没有传到服务器的潮水记录。");
  expect((await draft(page, id)).revision).toBe(before.revision);
  await restore();
  await button(page, "保存").click();
  await expect.poll(async () => (await draft(page, id)).body).toBe("没有传到服务器的潮水记录。");
  expect((await draft(page, id)).revision).toBe(before.revision + 1);
});

test("两个版本冲突：全文比较和丢弃本机副本", async ({ page }) => {
  const id = await setup(page, false), before = await draft(page, id);
  const restore = await failDraftSaves(page);
  await setDraftBody(page, "本机的完整记录。");
  await expect.poll(() => localDrafts(page, id)).toEqual([expect.objectContaining({ body: "本机的完整记录。" })]);
  await api(page).patch(`/projects/${id}/drafts/${before.id}`, { base_revision: before.revision, title: before.title, body: "服务器的完整记录。" });
  await reloadAcceptingUnload(page);
  await expect(page.getByRole("dialog", { name: "有两个不同版本的草稿", exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "本机副本全文", exact: true })).toHaveValue(before.title + "\n\n本机的完整记录。");
  await expect(page.getByRole("textbox", { name: "服务器版本全文", exact: true })).toHaveValue(before.title + "\n\n服务器的完整记录。");
  await button(page, "查看本机副本（不能直接覆盖）").click();
  await expect(page.getByRole("textbox", { name: "草稿正文", exact: true })).toHaveAttribute("aria-readonly", "true");
  await button(page, "比较两份正文").click();
  await button(page, "用服务器版本，丢掉副本").click();
  expect(await readDraftBody(page)).toBe("服务器的完整记录。");
  expect(await localDrafts(page, id)).toEqual([]);
  expect((await draft(page, id)).revision).toBe(before.revision + 1);
  await restore();
});

test("专注写作：共享正文、Esc 和焦点归还", async ({ page }) => {
  await setup(page, false);
  await button(page, "专注写作").click();
  const dialog = page.getByRole("dialog", { name: "专注写作", exact: true });
  await dialog.getByRole("textbox", { name: "草稿正文", exact: true }).fill("窗外的海面恢复了平静。");
  await shot(page, "writing-focus");
  await dialog.getByRole("button", { name: "退出专注写作", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(await readDraftBody(page)).toBe("窗外的海面恢复了平静。");
  await button(page, "专注写作").click();
  await dialog.press("Escape");
  await expect(dialog).toHaveCount(0);
  expect(await readDraftBody(page)).toBe("窗外的海面恢复了平静。");
  await expect(button(page, "专注写作")).toBeFocused();
});

test("完成本章：禁用未保存内容、预览和新草稿", async ({ page }) => {
  const id = await setup(page);
  await setDraftBody(page, "值班员将记录收好，今天的故事结束了。");
  await page.getByLabel("更多：完成本章、技术详情、重置", { exact: true }).click();
  await expect(page.getByRole("menuitem", { name: "完成本章，开始下一章", exact: true })).toBeDisabled();
  await page.keyboard.press("Escape");
  await button(page, "保存").click();
  await expect(button(page, "保存")).toHaveCount(0);
  const saved = await draft(page, id);
  await page.getByLabel("更多：完成本章、技术详情、重置", { exact: true }).click();
  await page.getByRole("menuitem", { name: "完成本章，开始下一章", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "完成本章，开始下一章", exact: true });
  await expect(dialog.getByRole("button", { name: "完成本章", exact: true })).toBeEnabled();
  await expect(dialog).toContainText("第 11 章");
  await shot(page, "writing-complete-dialog");
  await button(page, "完成本章").click();
  await expect.poll(async () => (await draft(page, id)).chapter_number).toBe(12);
  expect((await draft(page, id)).body).toBe("");
  const chapters = (await api(page).get(`/projects/${id}/long-term-review`)).chapters;
  expect(chapters).toHaveLength(11);
  expect(chapters.find((c: {number: number}) => c.number === 11).body).toBe(saved.body);
  await expect(page.getByLabel("草稿第 12 章", { exact: true })).toBeVisible();
});

test("写作页的一级标题：读屏能读到「第 N 章 · 标题」，看不见；标题为空时只有「第 N 章」", async ({ page }) => {
  const id = await setup(page);
  const h1 = page.getByRole("heading", { level: 1 });
  await expect(h1).toHaveCount(1);
  await expect(h1).toHaveText("第 11 章 · 桌上的留白");
  // Not drawn: it occupies one pixel, clipped, like the other text only a screen reader needs.
  const box = await h1.boundingBox();
  expect(box!.width).toBeLessThanOrEqual(1);
  expect(box!.height).toBeLessThanOrEqual(1);
  // An empty title leaves the chapter number alone.
  const title = page.getByRole("textbox", { name: "章节标题", exact: true });
  await title.fill("");
  await expect(h1).toHaveText("第 11 章");
  await title.fill("雨停之后");
  await expect(h1).toHaveText("第 11 章 · 雨停之后");
  // A written chapter, opened by its number, has the same.
  await page.goto(`/projects/${id}/workspace?chapter=3`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^第 3 章 · /);
});

test("键盘聚焦：章标题的底线变蓝加粗，正文左边出现 3px 蓝线，没有整圈的框", async ({ page }) => {
  await setup(page);
  const title = page.getByRole("textbox", { name: "章节标题", exact: true });
  const body = page.getByRole("textbox", { name: "草稿正文", exact: true });
  const read = (target: import("@playwright/test").Locator) => target.evaluate(e => { const style = getComputedStyle(e); return { outline: style.outlineStyle, shadow: style.boxShadow, border: style.borderBottomColor }; });
  const blue = "rgb(31, 43, 255)";
  const before = await read(title);
  expect(before.shadow).toBe("none");
  await title.focus();
  await expect(title).toBeFocused();
  const withFocus = await read(title);
  expect(withFocus.border).toBe(blue);
  await expect.poll(async () => (await read(title)).shadow).toBe(`${blue} 0px 2px 0px 0px`);
  await body.focus();
  await expect(body).toBeFocused();
  // The shadow eases in over a moment, so it is read until it settles.
  await expect.poll(async () => (await read(body)).shadow).toBe(`${blue} -3px 0px 0px 0px`);
  expect((await read(body)).outline, "正文没有整圈的框").toBe("none");
  // The bar is only a shadow: nothing moves.
  const box = await body.boundingBox();
  await title.focus();
  expect(await body.boundingBox()).toEqual(box);
});
