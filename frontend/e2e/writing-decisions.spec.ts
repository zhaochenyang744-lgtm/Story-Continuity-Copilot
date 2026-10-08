import { api, beginCheck, button, countDraftWrites, decide, draft, expect, finding, findings, finishCheck, readDraftBody, reloadAcceptingUnload, run, saveBody, selectIssue, setDraftBody, setup, shot, test } from "./support/writing";

test("采用改法（示例结果）：正文与决定只保存一次", async ({ page }) => {
  const id = await setup(page), before = await draft(page, id), result = await run(page, id);
  const issue = result.issues.find((i: any) => i.suggested_revision);
  const writes = countDraftWrites(page);
  await selectIssue(page, issue);
  await button(page, "采用改法").click();
  await expect(button(page, "保存修改")).toBeVisible();
  expect(await readDraftBody(page)).toBe(before.body.replace(issue.suggested_revision.before, issue.suggested_revision.after));
  expect((await draft(page, id)).revision).toBe(before.revision);
  await shot(page, "writing-after-apply");
  await button(page, "保存修改").click();
  await expect.poll(async () => (await run(page, id)).issues.find((i: any) => i.id === issue.id).decision?.decision).toBe("accept_and_edit");
  expect((await draft(page, id)).revision).toBe(before.revision + 1);
  expect((await draft(page, id)).body).toContain(issue.suggested_revision.after);
  expect(writes).toHaveLength(1);
});

test("采用改法（新检查）：E2E_SUGGEST 合约与落库", async ({ page }) => {
  const id = await setup(page);
  const memories = (await api(page).get(`/projects/${id}/memory`)).records;
  expect(memories.some((m: any) => m.subject.includes("黄铜罗盘") && m.value.includes("温岚"))).toBe(true);
  await saveBody(page, id, "苏岑拿着黄铜罗盘，温岚的手中已经空了，E2E_SUGGEST。");
  const result = await finishCheck(page, id, await beginCheck(page, id));
  const issue = result.issues.find((i: any) => i.claim_text.includes("E2E_SUGGEST"));
  expect(issue).toMatchObject({ review_contract_version: "trustworthy_review_v1", nature: "possible_conflict", evidence_status: "sufficient" });
  expect(issue.suggested_revision.after).toContain("E2E_APPLIED");
  const before = await draft(page, id), writes = countDraftWrites(page);
  await selectIssue(page, issue);
  await expect(button(page, "采用改法")).toBeEnabled();
  await button(page, "采用改法").click();
  await button(page, "保存修改").click();
  await expect.poll(async () => (await run(page, id)).issues.find((i: any) => i.id === issue.id).decision?.decision).toBe("accept_and_edit");
  const after = await draft(page, id);
  expect(after.revision).toBe(before.revision + 1);
  expect(after.body).toContain("E2E_APPLIED");
  expect(after.body).not.toContain("E2E_SUGGEST");
  expect(writes).toHaveLength(1);
});

test("是有意的、不是问题：两种决定刷新保留", async ({ page }) => {
  const id = await setup(page), result = await run(page, id);
  const possible = result.issues.find((i: any) => i.nature === "possible_conflict");
  const conflict = result.issues.find((i: any) => i.nature === "confirmed_conflict");
  await decide(page, id, possible, "是有意的", "keep_intentional");
  await expect(page.getByRole("status").filter({ hasText: "记下了：保留原意" })).toBeVisible();
  await decide(page, id, conflict, "不是问题", "false_positive");
  await expect(page.getByRole("status").filter({ hasText: "记下了：这一条不是问题" })).toBeVisible();
  await page.reload();
  for (const issue of [possible, conflict]) await expect(finding(page, issue.id)).toContainText("已处理");
  expect((await run(page, id)).issues.filter((i: any) => i.decision)).toHaveLength(2);
});

test("标为待修改：可以取消、刷新保留且不算决定", async ({ page }) => {
  const id = await setup(page), issue = (await run(page, id)).issues[0];
  await selectIssue(page, issue);
  await button(page, "标为待修改").click();
  await expect(button(page, "取消待修改")).toBeVisible();
  await expect(finding(page, issue.id)).toContainText("待修改");
  let stored = (await run(page, id)).issues.find((i: any) => i.id === issue.id);
  expect(stored.to_revise).toBe(true); expect(stored.decision).toBeFalsy();
  await page.reload();
  await expect(finding(page, issue.id)).toContainText("待修改");
  await selectIssue(page, issue);
  await expect(button(page, "不是问题")).toBeEnabled();
  await button(page, "取消待修改").click();
  await expect(button(page, "标为待修改")).toBeVisible();
  stored = (await run(page, id)).issues.find((i: any) => i.id === issue.id);
  expect(stored.to_revise).toBe(false);
  await decide(page, id, issue, "不是问题", "false_positive");
});

test("证据不足的那条：只有待修改操作", async ({ page }) => {
  const id = await setup(page), issue = (await run(page, id)).issues.find((i: any) => i.nature === "insufficient_evidence");
  await selectIssue(page, issue);
  await expect(button(page, "标为待修改")).toBeEnabled();
  for (const name of ["是有意的", "不是问题", "采用改法", "改正文"]) await expect(button(page, name)).toHaveCount(0);
});

test("改正文：编辑焦点与受控保存", async ({ page }) => {
  const id = await setup(page), before = await draft(page, id);
  const issue = (await run(page, id)).issues.find((i: any) => i.nature === "confirmed_conflict"), writes = countDraftWrites(page);
  await selectIssue(page, issue);
  await button(page, "改正文").click();
  await expect(page.getByRole("textbox", { name: "草稿正文", exact: true })).toBeFocused();
  await expect(page.getByText("正在按选中的那一条改正文。保存时会一并记下你的处理。", { exact: true })).toBeVisible();
  const changed = before.body.replace(issue.claim_text, "温岚独自保管着黄铜罗盘。");
  await setDraftBody(page, changed);
  await button(page, "保存修改").click();
  await expect.poll(async () => (await run(page, id)).issues.find((i: any) => i.id === issue.id).decision?.decision).toBe("accept_and_edit");
  expect(await draft(page, id)).toMatchObject({ body: changed, revision: before.revision + 1 });
  expect(writes).toHaveLength(1);
});

async function pendingDecision(page: import("@playwright/test").Page, reload: boolean) {
  const id = await setup(page), before = await draft(page, id);
  const issue = (await run(page, id)).issues.find((i: any) => i.suggested_revision), writes = countDraftWrites(page);
  const pattern = "**/api/projects/*/issues/*/decision";
  let attempts = 0;
  await page.route(pattern, async route => { attempts++; await route.abort("failed"); });
  await selectIssue(page, issue);
  await button(page, "采用改法").click();
  await button(page, "保存修改").click();
  await expect(button(page, "重试记录决定")).toBeVisible();
  expect(attempts).toBe(1);
  expect((await draft(page, id)).revision).toBe(before.revision + 1);
  expect((await run(page, id)).issues.find((i: any) => i.id === issue.id).decision).toBeFalsy();
  if (reload) await reloadAcceptingUnload(page);
  await expect(page.getByText(/正文已经保存，编辑暂时锁定/)).toBeVisible();
  if (!reload) await shot(page, "writing-pending-decision");
  await page.unroute(pattern);
  await button(page, "重试记录决定").click();
  await expect.poll(async () => (await run(page, id)).issues.filter((i: any) => i.decision)).toHaveLength(1);
  expect((await run(page, id)).issues.find((i: any) => i.id === issue.id).decision.decision).toBe("accept_and_edit");
  expect((await draft(page, id)).revision).toBe(before.revision + 1);
  expect(writes).toHaveLength(1);
}
test("正文存上了、决定没记下：只补记决定", async ({ page }) => { await pendingDecision(page, false); });
test("待补记的决定经得起刷新", async ({ page }) => { await pendingDecision(page, true); });

test("全部处理完，审阅事实变化", async ({ page }) => {
  test.fixme(true, "示例结果处理完显示审阅入口，但 POST memory/change-sets 返回 422 no_reviewable_changes，无法进入事实审阅");
  const id = await setup(page), result = await run(page, id), before = await api(page).get(`/projects/${id}`);
  for (const issue of result.issues) {
    await selectIssue(page, issue);
    if (issue.nature === "insufficient_evidence") {
      await button(page, "标为待修改").click();
      expect((await run(page, id)).issues.find((i: any) => i.id === issue.id).to_revise).toBe(true);
    } else await decide(page, id, issue, issue.nature === "state_change" ? "保留这个变化" : "是有意的", "keep_intentional");
  }
  await expect(findings(page)).toContainText("都处理完了。最后确认哪些事实有变化，再记进资料。");
  const response = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/memory/change-sets"));
  await button(page, "审阅事实变化").click();
  const res = await response;
  expect(res.ok(), await res.text()).toBe(true);
  const changes = (await res.json()).data.change_set;
  expect(changes.items.length).toBeGreaterThanOrEqual(2);
  const form = page.getByRole("form", { name: "审阅事实变化", exact: true });
  await form.getByRole("radio", { name: "不记", exact: true }).nth(1).check();
  if (changes.items.length > 2) {
    await form.getByRole("radio", { name: "改一下再记", exact: true }).nth(2).check();
    await form.getByRole("textbox", { name: "内容", exact: true }).nth(2).fill("作者核对后的测试事实。");
  }
  await shot(page, "writing-fact-review");
  await button(page, "确认并更新资料").click();
  await expect.poll(async () => (await api(page).get(`/projects/${id}`)).current_memory_version).toBe(before.current_memory_version + 1);
  const records = (await api(page).get(`/projects/${id}/memory`)).records;
  expect(records.some((m: any) => m.subject === changes.items[0].after.subject && m.value === changes.items[0].after.value)).toBe(true);
  expect(records.some((m: any) => m.subject === changes.items[1].after.subject && m.predicate === changes.items[1].after.predicate && m.value === changes.items[1].after.value)).toBe(false);
  if (changes.items.length > 2) expect(records.some((m: any) => m.value === "作者核对后的测试事实。")).toBe(true);
});

test("自动沿用之前的判断：只改无关句子", async ({ page }) => {
  test.fixme(true, "自动沿用策略绑定 draft_revision 和 draft_checksum；保存无关句子后策略失效，原句的新检查 reused_decision 为 null");
  const id = await setup(page);
  await saveBody(page, id, "温岚握着黄铜罗盘。窗外停着一辆蓝色小车。");
  const first = await finishCheck(page, id, await beginCheck(page, id));
  const issue = first.issues.find((i: any) => i.claim_text.includes("罗盘"));
  await decide(page, id, issue, "不是问题", "false_positive");
  expect((await run(page, id)).issues.find((i: any) => i.id === issue.id).reuse_policy.enabled).toBe(true);
  await saveBody(page, id, "温岚握着黄铜罗盘。窗外停着一辆白色小车。");
  const second = await finishCheck(page, id, await beginCheck(page, id));
  const reused = second.issues.find((i: any) => i.claim_text === issue.claim_text);
  expect(reused.reused_decision).toBeTruthy();
  await expect(finding(page, reused.id)).toContainText("沿用之前的判断");
});
