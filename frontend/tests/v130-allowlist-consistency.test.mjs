import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  IMPLICIT_METADATA_PATH,
  REQUIRED_PROTECTED_DECLARATIONS,
  validateAllowlist,
  validateRepository,
} from "../scripts/v130-allowlist-consistency.mjs";

const fixtureRoots = [];

function fixture() {
  const root = mkdtempSync(path.join(os.tmpdir(), "story-v130-allowlist-test-"));
  fixtureRoots.push(root);
  for (const repositoryPath of [
    "README.md",
    "backend/app/main.py",
    "frontend/app/page.tsx",
    "frontend/public/assets/brand/mark.svg",
    "docs/v1.3.0-product.md",
    IMPLICIT_METADATA_PATH,
  ]) {
    const target = path.join(root, ...repositoryPath.split("/"));
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, `${repositoryPath}\n`, "utf8");
  }
  return root;
}

function manifest(overrides = {}) {
  return {
    product_files: [
      "README.md",
      "backend/app/main.py",
      "frontend/app/page.tsx",
      "frontend/public/assets/brand/",
      "docs/v1.3.0-product.md",
    ],
    verification_files: [],
    protected_local_evidence: [...REQUIRED_PROTECTED_DECLARATIONS],
    ...overrides,
  };
}

test.after(() => {
  for (const root of fixtureRoots) rmSync(root, { recursive: true, force: true });
});

test("exact files, directory prefixes, protected paths, and implicit metadata are handled deterministically", () => {
  const repoRoot = fixture();
  const result = validateAllowlist({
    manifest: manifest(),
    repoRoot,
    changedPaths: [
      "README.md",
      "backend/app/main.py",
      "frontend/public/assets/brand/mark.svg",
      IMPLICIT_METADATA_PATH,
      ".envrc",
      "frontend/AGENTS.md",
      "frontend/CLAUDE.md",
      "backend/evidence/local-report.md",
      "evaluation/results/devdiag-private.json",
      "frontend/evidence/screenshots/page.png",
      "test-results/trace.zip",
      "backend/runtime/data/demo.sqlite3",
      "frontend/playwright-report/index.html",
      "frontend/.last-run.json",
      "frontend/test-failed-1.png",
    ],
  });
  assert.equal(result.release_relevant_changes, 3);
  assert.equal(result.protected_or_implicit_changes, 12);
});

test("missing allowlist paths fail closed", () => {
  const repoRoot = fixture();
  assert.throws(() => validateAllowlist({
    manifest: manifest({ product_files: ["backend/app/missing.py"] }),
    repoRoot,
    changedPaths: [],
  }), /allowlist path does not exist: backend\/app\/missing\.py/);
});

test("changed release-relevant paths omitted from the allowlist fail closed", () => {
  const repoRoot = fixture();
  assert.throws(() => validateAllowlist({
    manifest: manifest({ product_files: ["README.md"] }),
    repoRoot,
    changedPaths: ["README.md", "frontend/app/page.tsx"],
  }), /changed release-relevant paths are not allowlisted:[\s\S]*frontend\/app\/page\.tsx/);
});

test("absolute and traversal entries fail closed", () => {
  const repoRoot = fixture();
  for (const invalid of ["C:/private/file.txt", "../private/file.txt", "/private/file.txt"]) {
    assert.throws(() => validateAllowlist({
      manifest: manifest({ product_files: [invalid] }),
      repoRoot,
      changedPaths: [],
    }), /allowlist path (?:is absolute or invalid|escapes or is not normalized)/);
  }
});

test("duplicates across product and verification lists fail closed", () => {
  const repoRoot = fixture();
  assert.throws(() => validateAllowlist({
    manifest: manifest({
      product_files: ["README.md"],
      verification_files: ["README.md"],
    }),
    repoRoot,
    changedPaths: [],
  }), /duplicate allowlist entry: README\.md/);
});

test("protected local files cannot be allowlisted", () => {
  const repoRoot = fixture();
  assert.throws(() => validateAllowlist({
    manifest: manifest({ product_files: ["frontend/AGENTS.md"] }),
    repoRoot,
    changedPaths: [],
  }), /protected local path must not be allowlisted: frontend\/AGENTS\.md/);
});

test("an allowlisted directory containing a protected file fails even with a clean change set", () => {
  const repoRoot = fixture();
  const protectedFile = path.join(repoRoot, "frontend", "public", "assets", "brand", ".env");
  writeFileSync(protectedFile, "fixture only\n", "utf8");
  assert.throws(() => validateAllowlist({
    manifest: manifest(),
    repoRoot,
    changedPaths: [],
  }), /allowlisted directory contains protected local path: frontend\/public\/assets\/brand\/\.env/);
});

test("a protected changed descendant cannot hide under an allowlisted directory prefix", () => {
  const repoRoot = fixture();
  assert.throws(() => validateAllowlist({
    manifest: manifest(),
    repoRoot,
    changedPaths: ["frontend/public/assets/brand/.env.local"],
  }), /protected changed path is covered by an allowlist entry: frontend\/public\/assets\/brand\/\.env\.local/);
});

test("normal files inside an allowlisted brand directory remain valid", () => {
  const repoRoot = fixture();
  const result = validateAllowlist({
    manifest: manifest(),
    repoRoot,
    changedPaths: ["frontend/public/assets/brand/mark.svg"],
  });
  assert.equal(result.release_relevant_changes, 1);
});

test("unknown top-level allowlist and changed paths fail closed", () => {
  const repoRoot = fixture();
  assert.throws(() => validateAllowlist({
    manifest: manifest({ product_files: ["evaluation/report.json"] }),
    repoRoot,
    changedPaths: [],
  }), /unknown top-level allowlist path: evaluation\/report\.json/);
  assert.throws(() => validateAllowlist({
    manifest: manifest(),
    repoRoot,
    changedPaths: ["misc/unknown.txt"],
  }), /unknown top-level changed path: misc\/unknown\.txt/);
});

test("required protected declarations cannot be weakened by manifest edits", () => {
  const repoRoot = fixture();
  assert.throws(() => validateAllowlist({
    manifest: manifest({ protected_local_evidence: [".env"] }),
    repoRoot,
    changedPaths: [],
  }), /missing required protected_local_evidence entry/);
});

test("the allowlist document is implicit metadata and must not list itself", () => {
  const repoRoot = fixture();
  assert.throws(() => validateAllowlist({
    manifest: manifest({ product_files: [IMPLICIT_METADATA_PATH] }),
    repoRoot,
    changedPaths: [IMPLICIT_METADATA_PATH],
  }), /is implicit metadata and must not list itself/);
});

test("current release-candidate repository changes match the canonical allowlist", () => {
  const result = validateRepository();
  assert.ok(result.release_relevant_changes > 0);
  assert.ok(result.allowlist_entries > 0);
});
