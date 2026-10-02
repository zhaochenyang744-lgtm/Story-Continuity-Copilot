import { expect, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import path from "node:path";

type DraftOptions = { immersive?: boolean };
type ProjectOptions = { kind?: "小说" | "短篇" | "剧本" | "散文" | "其他"; customKind?: string; summary?: string };

// Register a unique author through the current registration form.
export async function registerAccount(page: Page, { prefix }: { prefix: string }) {
  const stem = prefix.toLowerCase().replace(/[^a-z0-9_.-]/g, "").slice(0, 20);
  if (!stem) throw new Error("An ASCII account prefix is required");
  const account = `${stem}${randomUUID().replaceAll("-", "")}`;
  const password = `safe-${randomUUID()}`;
  await page.goto("/register");
  await page.getByLabel("账号", { exact: true }).fill(account);
  await page.getByLabel("显示名称", { exact: true }).fill("E2E 作者");
  await page.getByLabel("恢复邮箱", { exact: true }).fill(`${account}@example.test`);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事", exact: true })).toBeVisible();
  return { account, password };
}

// Read the account's isolated tutorial project from the onboarding API.
export async function tutorialProjectId(page: Page): Promise<string> {
  const response = await page.request.get("/api/onboarding");
  expect(response.ok(), "GET /api/onboarding").toBe(true);
  const payload = await response.json();
  const id = payload.data?.tutorial?.project_id;
  expect(id).toEqual(expect.any(String));
  expect(id.length).toBeGreaterThan(0);
  return id;
}

async function createdProjectId(page: Page): Promise<string> {
  await expect(page).toHaveURL(/\/projects\/[^/]+\/overview(?:[?#].*)?$/);
  return new URL(page.url()).pathname.split("/")[2];
}

// Create a real project using the current title, type and summary controls.
export async function createProject(page: Page, title: string, opts: ProjectOptions = {}) {
  await page.goto("/projects/new");
  await page.getByRole("textbox", { name: /作品名称/ }).fill(title);
  await page.getByRole("radio", { name: opts.kind ?? "小说", exact: true }).check();
  if (opts.kind === "其他" && opts.customKind !== undefined) {
    await page.getByRole("textbox", { name: "其他作品类型", exact: true }).fill(opts.customKind);
  }
  if (opts.summary !== undefined) await page.getByRole("textbox", { name: /简介/ }).fill(opts.summary);
  await page.locator("button.design-create-button").click();
  return createdProjectId(page);
}

// Enter paragraphs with real browser input events, including empty paragraphs.
export async function setDraftBody(page: Page, text: string, { immersive = false }: DraftOptions = {}) {
  const editor = page.locator(immersive ? "#immersive-draft-body" : "#draft-body");
  await expect(editor).toHaveAttribute("contenteditable", "true");
  await editor.fill("");
  const lines = text.replaceAll("\r\n", "\n").split("\n");
  for (const [index, line] of lines.entries()) {
    if (index) await editor.press("Enter");
    if (line) await page.keyboard.insertText(line);
  }
  await expect.poll(() => readDraftBody(page, { immersive })).toBe(lines.join("\n"));
}

// Join rendered paragraph text with newlines without using textarea values.
export async function readDraftBody(page: Page, { immersive = false }: DraftOptions = {}) {
  const editor = page.locator(immersive ? "#immersive-draft-body" : "#draft-body");
  await expect(editor).toBeVisible();
  return editor.evaluate((element) => {
    const text = (node: Node): string => {
      if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
      if (node instanceof HTMLBRElement) return node.classList.contains("ProseMirror-trailingBreak") ? "" : "\n";
      return Array.from(node.childNodes).map(text).join("");
    };
    return Array.from(element.children).map(text).join("\n");
  });
}

// Resolve a fixture relative to this support file, independent of shell cwd.
export function fixturePath(name: string): string {
  const root = path.resolve(__dirname, "..", "fixtures");
  const resolved = path.resolve(root, name);
  const relative = path.relative(root, resolved);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("Fixture must be inside e2e/fixtures");
  return resolved;
}

// Import a Markdown fixture through preview, confirmation and project creation.
export async function importMarkdown(page: Page, fixtureName: string, title: string) {
  await page.goto("/projects/import");
  await page.locator('input[name="file"]').setInputFiles(fixturePath(fixtureName));
  await page.getByRole("button", { name: "发送并预览章节", exact: true }).click();
  await expect(page.getByRole("heading", { name: "章节预览", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "继续确认", exact: true }).click();
  await page.getByRole("textbox", { name: /^作品名/ }).fill(title);
  await page.getByRole("button", { name: "确认导入", exact: true }).click();
  return createdProjectId(page);
}
