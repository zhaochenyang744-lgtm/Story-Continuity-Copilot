import { defineConfig } from "@playwright/test";
import { validateStage13Harness } from "./stage13-harness.mjs";

const harness = validateStage13Harness(process.env);

export default defineConfig({
  testDir: "./e2e",
  testMatch: "v110.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  outputDir: harness.outputDir,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: harness.frontendOrigin,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
