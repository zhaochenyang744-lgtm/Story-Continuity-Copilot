import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";

const baseURL = process.env.E2E_BASE_URL;
if (!baseURL) throw new Error("E2E_BASE_URL is required");

export default defineConfig({
  testDir: "./e2e",
  testMatch: "v140-frontend.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 12_000 },
  outputDir: process.env.E2E_OUTPUT_DIR ?? path.join(os.tmpdir(), "story-v140-playwright"),
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
