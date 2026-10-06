import { expect, test } from "@playwright/test";
import { registerAccount, setDraftBody, tutorialProjectId } from "./support/app";

// v1.6.1: the draft is saved to the server a few seconds after typing stops, without locking the
// editor; a newer revision saved elsewhere pauses autosave instead of being overwritten.
async function openWorkspace(page: import("@playwright/test").Page, prefix: string) {
  await page.setViewportSize({ width: 1440, height: 960 });
  await registerAccount(page, { prefix });
  const projectId = await tutorialProjectId(page);
  await page.goto(`/projects/${projectId}/workspace`);
  await expect(page.locator(".workspace-save-summary strong")).toHaveText("已保存");
  return projectId;
}

async function serverDraft(page: import("@playwright/test").Page, projectId: string) {
  const project = await (await page.request.get(`/api/projects/${projectId}`)).json();
  const draftId = project.data.current_draft.id as string;
  return (await (await page.request.get(`/api/projects/${projectId}/drafts/${draftId}`)).json()).data as { id: string; revision: number; body: string; title: string; body_format: string };
}

test("the draft is saved to the server after typing stops", async ({ page }) => {
  const projectId = await openWorkspace(page, "v161auto");
  const before = await serverDraft(page, projectId);
  await setDraftBody(page, "雾钟又响了一次，苏岑把耳朵贴在冰冷的石阶上。");
  await expect(page.locator(".workspace-save-summary strong")).toHaveText("未保存");
  await expect(page.locator(".workspace-save-summary")).toContainText("停笔几秒后会自动保存到服务器");
  await expect(page.locator(".workspace-save-summary strong")).toHaveText("已保存", { timeout: 20_000 });
  const after = await serverDraft(page, projectId);
  expect(after.revision).toBe(before.revision + 1);
  expect(after.body).toContain("雾钟又响了一次");
  // The editor was never locked by the background save.
  await expect(page.locator("#draft-body")).toBeEditable();
});

test("a newer revision saved elsewhere pauses autosave instead of overwriting it", async ({ page }) => {
  const projectId = await openWorkspace(page, "v161conflict");
  const before = await serverDraft(page, projectId);
  // Another device saves first.
  const elsewhere = await page.request.patch(`/api/projects/${projectId}/drafts/${before.id}`, {
    headers: { "Idempotency-Key": crypto.randomUUID(), Origin: new URL(page.url()).origin },
    data: { base_revision: before.revision, title: before.title, body: "另一台设备写下的版本。", body_format: before.body_format },
  });
  expect(elsewhere.status()).toBe(200);
  await setDraftBody(page, "这一台设备上继续写的文字。");
  await expect(page.locator(".workspace-save-summary strong")).toHaveText("自动保存已暂停", { timeout: 20_000 });
  const server = await serverDraft(page, projectId);
  expect(server.body).toBe("另一台设备写下的版本。");
  expect(server.revision).toBe(before.revision + 1);
});
