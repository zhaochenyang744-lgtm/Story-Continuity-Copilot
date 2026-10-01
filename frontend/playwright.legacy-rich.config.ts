import { defineConfig } from "@playwright/test";
import common from "./playwright.config";

if (!process.env.E2E_BASE_URL || !process.env.E2E_OUTPUT_DIR) {
  throw new Error("Legacy rich E2E requires an isolated staged frontend");
}

export default defineConfig({
  ...common,
  testMatch: "legacy-rich-suggestion.spec.ts",
  outputDir: process.env.E2E_OUTPUT_DIR,
  reporter: [["list"], ["json", { outputFile: process.env.E2E_JSON_REPORT }]],
});
