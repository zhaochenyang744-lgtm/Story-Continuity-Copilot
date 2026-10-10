import type { Page } from "@playwright/test";
import { advanceTour, api, createWorkByApi, expect, openTab, registerAccount, sampleWorkId, setDraftBody } from "./app";
export { api, expect, readDraftBody, setDraftBody, shot, test } from "./app";

export const button = (page: Page, name: string) => page.getByRole("button", { name, exact: true });
export const findings = (page: Page) => page.getByRole("complementary", { name: "检查与回顾", exact: true });
export const finding = (page: Page, id: string) => page.getByTestId(`finding-${id}`);
export async function setup(page: Page, sample = true) {
  await registerAccount(page, "writing");
  const id = sample ? await sampleWorkId(page) : await createWorkByApi(page, { title: "测试灯塔" });
  if (sample) await advanceTour(page, id, 4);
  await openTab(page, id, "workspace");
  await expect(page.getByRole("textbox", { name: "草稿正文", exact: true })).toBeVisible();
  return id;
}
export async function draft(page: Page, id: string) {
  const p = await api(page).get(`/projects/${id}`);
  return api(page).get(`/projects/${id}/drafts/${p.current_draft.id}`);
}
export async function run(page: Page, id: string, runId?: string) {
  const rid = runId ?? (await api(page).get(`/projects/${id}`)).latest_run.run_id;
  return api(page).get(`/projects/${id}/checks/${rid}?include=issues,evidence,metrics`);
}
export async function saveBody(page: Page, id: string, body: string) {
  const before = await draft(page, id);
  await setDraftBody(page, body);
  await button(page, "保存").click();
  await expect.poll(async () => (await draft(page, id)).revision).toBe(before.revision + 1);
  expect((await draft(page, id)).body).toBe(body);
  await expect(button(page, "保存")).toHaveCount(0);
  return draft(page, id);
}
export async function beginCheck(page: Page, id: string, retry = false) {
  const response = page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname.startsWith(`/api/projects/${id}/checks`) && new URL(r.url()).pathname.match(retry ? /\/checks\/[^/]+\/retry$/ : /\/checks$/) !== null);
  await (retry ? findings(page).getByRole("button", { name: "重试", exact: true }) : button(page, (await api(page).get(`/projects/${id}`)).latest_run ? "再检查一次" : "检查这一章")).click();
  const res = await response;
  expect(res.ok(), await res.text()).toBe(true);
  const data = (await res.json()).data;
  return (data.run ?? data).run_id as string;
}
export async function finishCheck(page: Page, id: string, runId: string, status = "completed") {
  await expect.poll(async () => (await run(page, id, runId)).status).toBe(status);
  const result = await run(page, id, runId);
  if (status === "completed") {
    await expect(findings(page).getByTestId(/^finding-/)).toHaveCount(result.issues.length);
    for (const issue of result.issues) await expect(finding(page, issue.id)).toBeVisible();
  }
  return result;
}
export async function selectIssue(page: Page, issue: { id: string }) {
  const row = finding(page, issue.id);
  if (await row.getAttribute("aria-expanded") !== "true") await row.click();
  await expect(row).toHaveAttribute("aria-expanded", "true");
}
export async function decide(page: Page, id: string, issue: { id: string }, label: string, decision: string) {
  await selectIssue(page, issue);
  await findings(page).getByRole("button", { name: label, exact: true }).click();
  await expect.poll(async () => (await run(page, id)).issues.find((i: {id: string}) => i.id === issue.id)?.decision?.decision).toBe(decision);
  await expect(finding(page, issue.id)).toContainText("已处理");
}
export function countDraftWrites(page: Page) {
  const writes: string[] = [];
  page.on("request", r => { if (r.method() === "PATCH" && /\/drafts\/[^/?]+$/.test(r.url())) writes.push(r.url()); });
  return writes;
}
export async function reloadAcceptingUnload(page: Page) {
  page.once("dialog", d => d.accept());
  await page.reload();
}
export async function localDrafts(page: Page, id: string) {
  return page.evaluate(projectId => Object.keys(localStorage).filter(k => k.startsWith("story-continuity:draft:") && k.includes(projectId)).map(k => JSON.parse(localStorage.getItem(k)!)), id);
}
export async function failDraftSaves(page: Page) {
  const pattern = "**/api/projects/*/drafts/*";
  const handler = async (route: import("@playwright/test").Route) => {
    if (route.request().method() === "PATCH") await route.abort("failed");
    else await route.continue();
  };
  await page.route(pattern, handler);
  return () => page.unroute(pattern, handler);
}
