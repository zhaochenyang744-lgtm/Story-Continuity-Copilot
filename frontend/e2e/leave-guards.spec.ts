import { button, draft, expect, failDraftSaves, readDraftBody, setDraftBody, setup, shot, test } from "./support/writing";

test("同一作品里切换标签不提醒", async ({ page }) => {
  const id = await setup(page, false), before = await draft(page, id);
  const restore = await failDraftSaves(page);
  try {
    await setDraftBody(page, "尚未保存的灯塔记录。");
    for (const name of ["章节", "资料", "写作"]) {
      await page.getByRole("navigation", { name: "作品", exact: true }).getByRole("button", { name, exact: true }).click();
      await expect(page.getByRole("dialog", { name: "草稿还没保存", exact: true })).toHaveCount(0);
    }
    expect(await readDraftBody(page)).toBe("尚未保存的灯塔记录。");
    expect(await draft(page, id)).toMatchObject({ body: before.body, revision: before.revision });
  } finally { await restore(); }
});

test("离开作品时提醒：留下、保存离开与不保存离开", async ({ page }) => {
  const id = await setup(page, false), before = await draft(page, id);
  const restore = await failDraftSaves(page);
  await setDraftBody(page, "要保存的灯塔记录。");
  await page.getByRole("button", { name: /^更换当前作品：/ }).click();
  const dialog = page.getByRole("dialog", { name: "草稿还没保存", exact: true });
  for (const name of ["留在这里", "保存并离开", "不保存，直接离开"]) await expect(dialog.getByRole("button", { name, exact: true })).toBeVisible();
  await shot(page, "leave-dialog");
  await dialog.getByRole("button", { name: "留在这里", exact: true }).click();
  expect(await readDraftBody(page)).toBe("要保存的灯塔记录。");
  await page.getByRole("button", { name: /^更换当前作品：/ }).click();
  await restore();
  await dialog.getByRole("button", { name: "保存并离开", exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  expect(await draft(page, id)).toMatchObject({ body: "要保存的灯塔记录。", revision: before.revision + 1 });
  await page.goto(`/projects/${id}/workspace`);
  await setDraftBody(page, "明确放弃的另一份记录。");
  await page.getByRole("button", { name: /^更换当前作品：/ }).click();
  await dialog.getByRole("button", { name: "不保存，直接离开", exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  expect(await draft(page, id)).toMatchObject({ body: "要保存的灯塔记录。", revision: before.revision + 1 });

});

test("保存失败时保存并离开不离开", async ({ page }) => {
  const id = await setup(page, false), before = await draft(page, id);
  const restore = await failDraftSaves(page);
  try {
    await setDraftBody(page, "断网时不能丢掉的记录。");
    await page.getByRole("button", { name: /^更换当前作品：/ }).click();
    const dialog = page.getByRole("dialog", { name: "草稿还没保存", exact: true });
    await dialog.getByRole("button", { name: "保存并离开", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText("没保存成功，还没离开。");
    await expect(page).toHaveURL(new RegExp(`/projects/${id}/workspace$`));
    expect(await draft(page, id)).toMatchObject({ body: before.body, revision: before.revision });
  } finally { await restore(); }
});

test("关闭或刷新页面：beforeunload 提醒", async ({ page }) => {
  const id = await setup(page, false), before = await draft(page, id);
  const restore = await failDraftSaves(page);
  try {
    await setDraftBody(page, "刷新前尚未保存的记录。");
    let kind = "";
    page.once("dialog", async dialog => { kind = dialog.type(); await dialog.accept(); });
    await page.reload();
    expect(kind).toBe("beforeunload");
    expect(await draft(page, id)).toMatchObject({ body: before.body, revision: before.revision });
    await expect(page.getByRole("dialog", { name: "这台设备上有没保存的草稿", exact: true })).toBeVisible();
  } finally { await restore(); }
});
