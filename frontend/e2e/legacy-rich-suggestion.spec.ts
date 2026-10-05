import { expect, test } from "@playwright/test";
import path from "node:path";

test("real Tiptap keeps uniform marks and list or quote containers; unsafe replacements leave body intact", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/test-writing-tools");
  const editor=page.getByRole("textbox",{name:"富文本测试正文"});
  const choose=page.getByLabel("场景");
  const result=page.getByRole("status");
  const serialized=page.getByTestId("serialized-body");
  for (const [name,selector] of [["bold","strong"],["italic","em"],["list","li strong"],["quote","blockquote em"]] as const) {
    await choose.selectOption(name);
    await expect(editor.locator(selector)).toContainText("旧句");
    await page.getByRole("button",{name:"采用建议"}).click();
    await expect(result).toContainText("已放入未保存正文");
    await expect(editor.locator(selector)).toContainText("新句");
    await expect(editor).not.toContainText("旧句");
  }
  for (const name of ["mixed","newline","crlf","repeatedText","repeatedParagraph"] as const) {
    await choose.selectOption(name);
    const before=await serialized.innerText();
    await page.getByRole("button",{name:"采用建议"}).click();
    await expect(result).toContainText("已拒绝，正文不变，需人工处理");
    await expect(serialized).toHaveText(before);
  }
  const output=process.env.E2E_OUTPUT_DIR;
  if (output) {
    await choose.selectOption("list");
    await page.getByRole("button",{name:"采用建议"}).click();
    await page.screenshot({path:path.join(output,"legacy-rich-suggestion-1440.png"),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(output,"legacy-rich-suggestion-390.png"),fullPage:true});
  }
});
