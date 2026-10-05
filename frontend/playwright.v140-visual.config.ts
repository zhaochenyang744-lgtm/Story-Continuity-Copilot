import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";

const baseURL = process.env.E2E_BASE_URL;
if (!baseURL) throw new Error("E2E_BASE_URL is required");

export default defineConfig({
  testDir: "./e2e",
  testMatch: ["v140-frontend.spec.ts", "v140-visual.spec.ts"],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 150_000,
  expect: { timeout: 15_000 },
  outputDir: process.env.E2E_OUTPUT_DIR ?? path.join(os.tmpdir(), "story-v140-visual-playwright"),
  reporter: process.env.E2E_JSON_REPORT
    ? [["list"], ["json", { outputFile: process.env.E2E_JSON_REPORT }]]
    : [["list"]],
  use: {
    baseURL,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
