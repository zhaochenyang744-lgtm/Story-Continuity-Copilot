import { defineConfig } from "@playwright/test";

const baseURL = process.env.E2E_BASE_URL;
if (baseURL !== "http://127.0.0.1:3072") {
  throw new Error("Stage 12 V2 requires E2E_BASE_URL=http://127.0.0.1:3072");
}
if (!process.env.E2E_ACCOUNT_PREFIX?.startsWith("stage12v2")) {
  throw new Error("Stage 12 V2 requires an approved stage12v2 account prefix");
}

export default defineConfig({
  testDir: "./e2e",
  testMatch: "stage12.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 8_000 },
  reporter: [["list"]],
  use: {
    baseURL,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
