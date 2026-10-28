import { mkdir } from "node:fs/promises";
import path from "node:path";
import type { Page } from "@playwright/test";
import { expect, openTab, registerAccount, sampleWorkId, test } from "./support/app";
import { ask, box, finished, openAssistantTab, tasks, thread, topbarAssistant } from "./support/assistant";
import { askView, serveTasks } from "./support/assistant-mock";
import { ago, askSources, noted, recapView } from "./support/assistant-38a";
import { theme } from "./support/pages";

// The pictures of the 38a delivery report. Taken only when ASSISTANT_SHOTS_DIR is set (nothing to check here); the checks are in assistant-38a.spec.ts.

const directory = process.env.ASSISTANT_SHOTS_DIR;
test.skip(!directory, "pictures are taken only when ASSISTANT_SHOTS_DIR is set");

async function snap(page: Page, name: string) {
  await mkdir(directory!, { recursive: true });
  await page.evaluate(async () => { await document.fonts.ready; });
  await page.screenshot({ path: path.join(directory!, `${name}.png`), animations: "disabled" });
}
/** The assistant on the writing page: the column's tab on a wide window, the 助手 pane of a phone. */
async function showAssistant(page: Page) {
  if ((page.viewportSize()?.width ?? 1440) < 1024) await page.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: "助手", exact: true }).click();
  else await openAssistantTab(page);
}

test("38a 截图：写前回顾（浅色、深色、手机 390、角标浮层）", async ({ page }) => {
  await registerAccount(page, "a38s");
  const id = await sampleWorkId(page);
  await serveTasks(page, () => [recapView("atask-recap-shot", ["本章草稿（写前回顾不看草稿）"])]);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openTab(page, id, "workspace");
  await showAssistant(page);
  await expect(tasks(page).first()).toBeVisible();
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await theme(page, "day");
  await snap(page, "01-写前回顾-浅色");
  await theme(page, "night");
  await snap(page, "02-写前回顾-深色");
  await theme(page, "day");
  const view = tasks(page).first();
  await view.locator("p.a-ri.lead .a-cite > button").click();
  await expect(page.locator(".a-pop mark")).toBeVisible();
  await page.waitForTimeout(300);
  await snap(page, "03-写前回顾-角标浮层-整段和圈出的那一句");
  await page.keyboard.press("Escape");
  await view.locator("li.a-ri", { hasText: "廊桥钥匙" }).locator(".a-cite > button").click();
  await expect(page.locator(".a-pop .w").first()).toBeVisible();
  await snap(page, "04-写前回顾-角标浮层-两个来源各标各的");
  await page.setViewportSize({ width: 390, height: 1500 });
  await page.reload();
  await showAssistant(page);
  await expect(tasks(page).first()).toBeVisible();
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await snap(page, "05-写前回顾-手机390");
});

test("38a 截图：问答回答的「怎么查的」收起和展开；跨章回答分条", async ({ page }) => {
  await registerAccount(page, "a38s");
  const id = await sampleWorkId(page);
  const walk = askView({
    id: "atask-walk-shot", question: "从第 1 章到第 10 章，苏岑对父亲留下的记录的认识发生了哪些变化？", sources: askSources, created_at: ago(30), started_at: ago(28), completed_at: ago(20),
    answer: {
      status: "answered", note: null,
      sentences: [
        { text: "第 1 章苏岑只把它当成父亲的遗物。", refs: ["R1"] },
        { text: "第 2 章他发现月牙裂纹，开始留意罗盘。", refs: ["R2"] },
        { text: "第 7 章他第一次怀疑记录被人改过。", refs: [] },
        { text: "第 10 章他把罗盘交给了温岚，不再确定。", refs: ["R2"] },
      ],
    },
    coverage: { checked: ["第 1–10 章正文", "已确认事实"], not_checked: ["本章草稿"] },
  });
  await serveTasks(page, () => [noted("atask-note-shot", "查过第 1–10 章正文、已确认事实。没有找到罗盘的重量。"), walk]);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openTab(page, id, "overview");
  await topbarAssistant(page).click();
  await expect(thread(page).locator("[data-task]")).toHaveCount(2);
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  const first = tasks(page).first();
  await first.scrollIntoViewIfNeeded();
  await snap(page, "06-问答回答-怎么查的收起");
  await first.getByRole("button", { name: "怎么查的" }).click();
  await expect(first.locator(".a-how")).toBeVisible();
  await snap(page, "07-问答回答-怎么查的展开");
  await tasks(page).nth(1).scrollIntoViewIfNeeded();
  await snap(page, "08-跨章回答分条");
});

test("38a 截图：V04 抽屉改变宽度后、V10 写作页右栏回答完以后", async ({ page }) => {
  await registerAccount(page, "a38s");
  const id = await sampleWorkId(page);
  const views = [1, 2, 3].map((n) => askView({ id: `atask-v04-${n}`, question: `第 ${n} 个问题：罗盘有什么特征？`, created_at: ago(400 - n * 60), started_at: ago(398 - n * 60), completed_at: ago(390 - n * 60) }));
  const stop = await serveTasks(page, () => views);
  await page.setViewportSize({ width: 1280, height: 800 });
  await openTab(page, id, "overview");
  await topbarAssistant(page).click();
  await expect(thread(page).locator("[data-task]")).toHaveCount(3);
  for (const [width, height] of [[390, 844], [768, 1000]] as const) {
    await page.setViewportSize({ width, height });
    await box(page).focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    await snap(page, `09-V04-抽屉改宽度后-${width}`);
  }
  await stop();
  await page.setViewportSize({ width: 1440, height: 900 });
  await openTab(page, id, "workspace");
  await openAssistantTab(page);
  for (const [index, question] of ["E2E_TWO 苏岑知道罗盘被调包了吗？", "E2E_TWO 温岚把罗盘放在哪里？"].entries()) {
    await ask(page, question);
    await finished(page, index + 1);
  }
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await snap(page, "10-V10-写作页右栏回答完以后");
});
