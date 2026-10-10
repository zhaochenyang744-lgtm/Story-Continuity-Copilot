import { defineConfig } from "@playwright/test";
import common from "./playwright.config";

for (const name of ["E2E_BASE_URL", "E2E_OUTPUT_DIR", "E2E_JSON_REPORT", "E2E_SCREENSHOTS_DIR", "E2E_ACCOUNT_PREFIX"]) {
  if (!process.env[name]) throw new Error(`v170 E2E requires the runner environment (${name} is missing); start it with npm run test:e2e`);
}

export default defineConfig({
  ...common,
  outputDir: process.env.E2E_OUTPUT_DIR,
  reporter: [["list"], ["json", { outputFile: process.env.E2E_JSON_REPORT }]],
  projects: [
    {
      name: "v170",
      testMatch: "**/*.spec.ts",
      use: { viewport: { width: 1440, height: 960 } },
    },
  ],
});
