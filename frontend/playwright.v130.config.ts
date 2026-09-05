import { defineConfig } from "@playwright/test";
import { validateV130Harness } from "./v130-harness.mjs";

const harness = validateV130Harness(process.env);

export default defineConfig({
  testDir: "./e2e",
  testMatch: "v130-*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  outputDir: harness.outputDir,
  timeout: 120_000,
  expect: { timeout: 12_000 },
  reporter: [
    ["list"],
    ["json", { outputFile: harness.jsonReport }],
    ["html", { outputFolder: harness.reportDir, open: "never" }],
  ],
  use: {
    baseURL: harness.frontendOrigin,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
