import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testIgnore: [
    "**/legacy-gap-independent.spec.ts",
    "**/legacy-gap-independent-round2.spec.ts",
    "**/legacy-gap-round3-brief.spec.ts",
    "**/g02-controller.spec.ts",
    "**/g02-controller-post-v4.spec.ts",
  ],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 8_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:3000",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
