import assert from "node:assert/strict";
import test from "node:test";

import { validatePublicConfig } from "../public-config.mjs";

test("production mode must be explicit", () => {
  assert.throws(() => validatePublicConfig({}, { required: true }), /PUBLIC_APP_MODE_REQUIRED/);
  assert.throws(() => validatePublicConfig({ PUBLIC_APP_MODE: "0" }, { required: true }), /PUBLIC_BASE_URL_REQUIRED/);
});

test("public mode requires canonical https", () => {
  assert.throws(() => validatePublicConfig({ PUBLIC_APP_MODE: "1", PUBLIC_BASE_URL: "http://example.test" }), /PUBLIC_BASE_URL_INVALID/);
  assert.deepEqual(validatePublicConfig({ PUBLIC_APP_MODE: "1", PUBLIC_BASE_URL: "https://example.test" }), {
    publicMode: true,
    publicBaseUrl: "https://example.test",
  });
});

test("local mode is restricted to explicit loopback port", () => {
  assert.throws(() => validatePublicConfig({ PUBLIC_APP_MODE: "0", PUBLIC_BASE_URL: "http://localhost:3080" }), /PUBLIC_BASE_URL_INVALID/);
  assert.deepEqual(validatePublicConfig({ PUBLIC_APP_MODE: "0", PUBLIC_BASE_URL: "http://127.0.0.1:3080" }), {
    publicMode: false,
    publicBaseUrl: "http://127.0.0.1:3080",
  });
});
