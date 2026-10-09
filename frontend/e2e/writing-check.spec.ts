import { api, beginCheck, button, draft, expect, findings, finishCheck, run, saveBody, selectIssue, setDraftBody, setup, shot, test } from "./support/writing";
import { openTab, sampleWorkId, startVisitor } from "./support/app";

test("示例结果：四条结果、正文编号和前文依据", async ({ page }) => {
  const id = await setup(page), result = await run(page, id);
  expect(result.issues).toHaveLength(4);
  await expect(findings(page).getByText("示例结果", { exact: true })).toBeVisible();
  await expect(findings(page).getByTestId(/^finding-/)).toHaveCount(4);
  for (let n = 1; n <= 4; n++) await expect(page.getByLabel(`第 ${n} 处`, { exact: true })).toBeVisible();
  await shot(page, "writing-sample-results");
  await selectIssue(page, result.issues[0]);
  const ev = result.issues[0].evidence[0];
  await expect(findings(page).getByRole("button", { name: new RegExp(`^第 ${ev.chapter_number} 章`) })).toBeVisible();
  await shot(page, "writing-finding-open");
});

test("检查一次：新 run 完成且结果与接口一致", async ({ page }) => {
  const id = await setup(page), old = await run(page, id);
  const before = await (await page.request.get("/api/test/stage12/stats")).json();
  await saveBody(page, id, "温岚仍握着黄铜罗盘。苏岑在档案室检查手边的纸条。");
  const rid = await beginCheck(page, id);
  expect(rid).not.toBe(old.run_id);
  const result = await finishCheck(page, id, rid);
  expect(result.issues.length).toBeGreaterThan(0);
  await expect(findings(page).getByText("示例结果", { exact: true })).toHaveCount(0);
  const after = await (await page.request.get("/api/test/stage12/stats")).json();
  expect(after.provider_calls).toBeGreaterThan(before.provider_calls);
  expect(after.provider_http_calls).toBe(0);
});

test("检查中：阻塞状态与放行", async ({ page }) => {
  const id = await setup(page);
  await page.request.get("/api/test/stage12/reset");
  await saveBody(page, id, "温岚握着黄铜罗盘，STAGE12_BLOCK。");
  const rid = await beginCheck(page, id);
  try {
    await expect(button(page, "正在检查…")).toBeDisabled();
    await expect(page.getByRole("status", { name: "正在检查这一章", exact: true })).toBeVisible();
    await shot(page, "writing-checking");
  } finally { await page.request.get("/api/test/stage12/release"); }
  await finishCheck(page, id, rid);
});

test("检查失败后重试：保留两次尝试且无半截结果", async ({ page }) => {
  const id = await setup(page);
  await saveBody(page, id, "温岚握着黄铜罗盘，STAGE12_FAIL_ONCE。");
  const first = await beginCheck(page, id);
  const failed = await finishCheck(page, id, first, "failed");
  expect(failed.attempt_number).toBe(1);
  expect(failed.issues).toBeUndefined();
  await expect(findings(page)).toContainText("没有保存任何结果。");
  await expect(findings(page).getByTestId(/^finding-/)).toHaveCount(0);
  await shot(page, "writing-check-failed");
  const second = await beginCheck(page, id, true);
  expect(second).not.toBe(first);
  expect((await finishCheck(page, id, second)).attempt_number).toBe(2);
  expect((await run(page, id, first)).status).toBe("failed");
});

test("超时：可以重试且没有半截结果", async ({ page }) => {
  const id = await setup(page);
  await saveBody(page, id, "温岚握着黄铜罗盘，STAGE12_TIMEOUT。");
  const rid = await beginCheck(page, id);
  await expect.poll(async () => (await run(page, id, rid)).status).toMatch(/^(timed_out|failed)$/);
  expect((await run(page, id, rid)).issues).toBeUndefined();
  await expect(findings(page)).toContainText("没有保存任何结果。");
  await expect(findings(page).getByRole("button", { name: "重新检查", exact: true })).toBeEnabled();
  await expect(findings(page).getByTestId(/^finding-/)).toHaveCount(0);
});

test("检查后又改了草稿：旧结果不能作决定", async ({ page }) => {
  const id = await setup(page);
  await saveBody(page, id, "温岚握着黄铜罗盘。");
  const result = await finishCheck(page, id, await beginCheck(page, id));
  await setDraftBody(page, "温岚握着黄铜罗盘。雨停了。");
  await expect(findings(page)).toContainText("草稿在检查之后改过，下面的结果针对的是先前的正文。");
  await selectIssue(page, result.issues[0]);
  await expect(findings(page).getByRole("button", { name: "是有意的", exact: true })).toBeDisabled();
  await expect(findings(page).getByRole("button", { name: "不是问题", exact: true })).toBeDisabled();
  await button(page, "保存").click();
  await expect(button(page, "保存")).toHaveCount(0);
  await finishCheck(page, id, await beginCheck(page, id));
  await expect(findings(page).getByText("草稿在检查之后改过，下面的结果针对的是先前的正文。", { exact: true })).toHaveCount(0);
});

test("空草稿：禁用检查并提示先写正文", async ({ page }) => {
  const id = await setup(page, false);
  expect((await draft(page, id)).body).toBe("");
  await expect(button(page, "检查这一章")).toBeDisabled();
  await expect(findings(page)).toContainText("先写下正文，再检查。");
});

test("访客的额度：重查消耗一次", async ({ page }) => {
  await startVisitor(page);
  const id = await sampleWorkId(page), before = await api(page).get("/account/usage");
  await openTab(page, id, "workspace");
  await finishCheck(page, id, await beginCheck(page, id));
  const after = await api(page).get("/account/usage");
  expect(after.checks_remaining).toBe(before.checks_remaining - 1);
  await expect(page.getByLabel("草稿第 11 章", { exact: true }).getByText(new RegExp(`还可检查 ${after.checks_remaining} 次`))).toBeVisible();
});

test("访客超长：检查按钮禁用并说明上限", async ({ page }) => {
  await startVisitor(page);
  const id = await sampleWorkId(page), usage = await api(page).get("/account/usage");
  await openTab(page, id, "workspace");
  await saveBody(page, id, "潮".repeat(usage.check_chars_per_check + 1));
  await expect(page.getByText(new RegExp(`访客每次最多 ${usage.check_chars_per_check.toLocaleString()} 字`))).toBeVisible();
  await expect(button(page, "再检查一次")).toBeDisabled();
});
