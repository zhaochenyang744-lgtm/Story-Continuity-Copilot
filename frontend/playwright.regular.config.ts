import { defineConfig } from "@playwright/test";
import common from "./playwright.config";

if (!process.env.E2E_BASE_URL || !process.env.E2E_OUTPUT_DIR) {
  throw new Error("Regular E2E requires an isolated runner environment");
}

export default defineConfig({
  ...common,
  outputDir: process.env.E2E_OUTPUT_DIR,
  reporter: [["list"], ["json", { outputFile: process.env.E2E_JSON_REPORT }]],
  projects: [
    {
      name: "regular",
      testMatch: ["auth-entry.spec.ts", "controlled-edit-run.spec.ts", "review-entry.spec.ts", "stage5.spec.ts", "stage8.spec.ts", "stage9.spec.ts", "stage11[i-l].spec.ts", "support/app.smoke.spec.ts"],
    },
    {
      name: "v120",
      testMatch: "v120.spec.ts",
      timeout: 120_000,
      expect: { timeout: 12_000 },
    },
    {
      name: "v110",
      testMatch: "v110.spec.ts",
      // Preserve the v110 configuration's existing timeout settings. Its specs
      // can share the regular stub; only its original config loads stage13.
      timeout: 120_000,
      expect: { timeout: 10_000 },
    },
  ],
});
