import { defineConfig } from "@playwright/test";
import path from "node:path";
import os from "node:os";
if (!process.env.E2E_BASE_URL) throw new Error("E2E_BASE_URL is required");
export default defineConfig({
  testDir: "./e2e", testMatch: ["maintenance.spec.ts", "v140-frontend.spec.ts"],
  fullyParallel: false, workers: 1, retries: 0, timeout: 150_000,
  expect: { timeout: 15_000 },
  outputDir: process.env.E2E_OUTPUT_DIR ?? path.join(os.tmpdir(), "story-maintenance-browser"),
  reporter: [["list"], ["json", { outputFile: process.env.E2E_JSON_REPORT }]],
  use: { baseURL: process.env.E2E_BASE_URL, headless: true, trace: "retain-on-failure", screenshot: "only-on-failure" },
});
