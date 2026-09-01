import { defineConfig } from "@playwright/test";
import path from "node:path";
import os from "node:os";

const baseURL = process.env.E2E_BASE_URL;
if (!baseURL) throw new Error("E2E_BASE_URL is required");

export default defineConfig({
  testDir: "./e2e",
  testMatch: process.env.E2E_TEST_MATCH ?? "v120.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  outputDir:
    process.env.E2E_OUTPUT_DIR ??
    path.join(os.tmpdir(), "story-v120-playwright"),
  timeout: 120_000,
  expect: { timeout: 12_000 },
  reporter: [["list"]],
  use: {
    baseURL,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
