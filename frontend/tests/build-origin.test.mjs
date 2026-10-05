import assert from "node:assert/strict";
import test from "node:test";

import { validateBackendOrigin } from "../build-origin.mjs";
import { validateApiRewriteManifest } from "../scripts/assert-api-rewrite.mjs";

test("production origin is explicit and canonical", () => {
  assert.throws(
    () => validateBackendOrigin(undefined, { required: true }),
    /BACKEND_ORIGIN_REQUIRED/,
  );
  assert.equal(
    validateBackendOrigin("http://127.0.0.1:8072", { required: true }),
    "http://127.0.0.1:8072",
  );
});
test("invalid schemes, paths, queries, fragments, and credentials fail closed", () => {
  for (const value of [
    "ftp://127.0.0.1:8072",
    "http://127.0.0.1:8072/",
    "http://127.0.0.1:8072/path",
    "http://127.0.0.1:8072?query=1",
    "http://127.0.0.1:8072#fragment",
    "http://user:secret@127.0.0.1:8072",
    "not-an-origin",
  ]) {
    assert.throws(
      () => validateBackendOrigin(value, { required: true }),
      /BACKEND_ORIGIN_INVALID/,
      value,
    );
  }
});

test("compiled manifest accepts exactly one API rewrite to the expected origin", () => {
  const manifest = {
    rewrites: [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8072/api/:path*",
      },
    ],
  };
  assert.deepEqual(
    validateApiRewriteManifest(manifest, "http://127.0.0.1:8072"),
    {
      destination: "http://127.0.0.1:8072/api/:path*",
      rewriteCount: 1,
    },
  );
  assert.throws(
    () => validateApiRewriteManifest(manifest, "http://127.0.0.1:8000"),
    /COMPILED_REWRITE_MISMATCH/,
  );
  assert.throws(
    () =>
      validateApiRewriteManifest(
        {
          rewrites: [
            ...manifest.rewrites,
            { source: "/other", destination: "https://example.com/other" },
          ],
        },
        "http://127.0.0.1:8072",
      ),
    /COMPILED_REWRITE_MISMATCH/,
  );
});
