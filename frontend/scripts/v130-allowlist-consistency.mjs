import { execFileSync } from "node:child_process";
import {
  existsSync,
  lstatSync,
  readFileSync,
  readdirSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
export const DEFAULT_REPO_ROOT = path.resolve(scriptDir, "../..");
export const IMPLICIT_METADATA_PATH = "docs/v1.3.0-release-allowlist.json";

export const REQUIRED_PROTECTED_DECLARATIONS = Object.freeze([
  ".env",
  ".env.*",
  ".env*",
  "backend/evidence/",
  "evaluation/results/devdiag-*",
  "frontend/evidence/",
  "test-results/",
  "frontend/AGENTS.md",
  "frontend/CLAUDE.md",
  "runtime/**/*.sqlite*",
  "runtime/**/*.db",
  "**/playwright-report/",
  "**/screenshots/",
  "**/.last-run.json",
  "**/test-failed-*.png",
  "**/trace.zip",
]);

function fail(message) {
  throw new Error(`[v1.3 allowlist consistency] ${message}`);
}

function assertArray(manifest, key) {
  if (!Array.isArray(manifest[key])) {
    fail(`${key} must be an array`);
  }
  return manifest[key];
}

function normalizeManifestPath(value) {
  if (typeof value !== "string" || value.length === 0) {
    fail("allowlist entries must be non-empty strings");
  }
  if (value.includes("\\")) {
    fail(`allowlist path must use forward slashes: ${value}`);
  }
  if (/^[A-Za-z]:/.test(value) || value.startsWith("/") || value.includes("\0")) {
    fail(`allowlist path is absolute or invalid: ${value}`);
  }

  const directory = value.endsWith("/");
  const trimmed = directory ? value.slice(0, -1) : value;
  const segments = trimmed.split("/");
  if (!trimmed || segments.some((segment) => !segment || segment === "." || segment === "..")) {
    fail(`allowlist path escapes or is not normalized: ${value}`);
  }
  if (/[?*\[\]]/.test(trimmed)) {
    fail(`wildcards are not allowed in product_files or verification_files: ${value}`);
  }
  if (!(trimmed === "README.md" || /^(backend|frontend|docs)\//.test(trimmed))) {
    fail(`unknown top-level allowlist path: ${value}`);
  }
  return { value, trimmed, directory };
}

function normalizeChangedPath(value) {
  if (typeof value !== "string" || value.length === 0) {
    fail("changed paths must be non-empty strings");
  }
  const normalized = value.replaceAll("\\", "/").replace(/^\.\//, "");
  if (/^[A-Za-z]:/.test(normalized) || normalized.startsWith("/")) {
    fail(`changed path is outside the repository: ${value}`);
  }
  const segments = normalized.split("/");
  if (segments.some((segment) => !segment || segment === "." || segment === "..")) {
    fail(`changed path escapes or is not normalized: ${value}`);
  }
  return normalized;
}

export function isProtectedRepositoryPath(value) {
  const repositoryPath = value.replaceAll("\\", "/").replace(/^\.\//, "").replace(/\/$/, "");
  const basename = repositoryPath.split("/").at(-1) ?? "";

  if (repositoryPath.split("/").some((segment) => /^\.env/.test(segment))) return true;
  if (basename === "AGENTS.md" || basename === "CLAUDE.md") return true;
  if (/(^|\/)evidence(\/|$)/.test(repositoryPath)) return true;
  if (/(^|\/)test-results(\/|$)/.test(repositoryPath)) return true;
  if (basename.startsWith("devdiag-")) return true;
  if (/(^|\/)runtime\/.*\.(?:db|sqlite|sqlite3)(?:-(?:wal|shm))?$/i.test(repositoryPath)) return true;
  if (/(^|\/)playwright-report(\/|$)/.test(repositoryPath)) return true;
  if (/(^|\/)screenshots?(\/|$)/.test(repositoryPath)) return true;
  if (basename === ".last-run.json" || basename === "last-run.json") return true;
  if (/^test-failed-\d+\.png$/i.test(basename)) return true;
  if (basename === "trace.zip") return true;
  return false;
}

function assertKnownChangedTopLevel(repositoryPath) {
  if (repositoryPath === "README.md" || /^(backend|frontend|docs)\//.test(repositoryPath)) return;
  fail(`unknown top-level changed path: ${repositoryPath}`);
}

function assertProtectedDeclarations(manifest) {
  const declarations = assertArray(manifest, "protected_local_evidence");
  const seen = new Set();
  for (const declaration of declarations) {
    if (typeof declaration !== "string" || declaration.length === 0) {
      fail("protected_local_evidence entries must be non-empty strings");
    }
    if (seen.has(declaration)) fail(`duplicate protected_local_evidence entry: ${declaration}`);
    seen.add(declaration);
  }
  for (const required of REQUIRED_PROTECTED_DECLARATIONS) {
    if (!seen.has(required)) fail(`missing required protected_local_evidence entry: ${required}`);
  }
}

function assertEntryExists(repoRoot, entry) {
  const target = path.resolve(repoRoot, ...entry.trimmed.split("/"));
  const relative = path.relative(repoRoot, target);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    fail(`allowlist path resolves outside repository: ${entry.value}`);
  }
  if (!existsSync(target)) fail(`allowlist path does not exist: ${entry.value}`);
  const stats = lstatSync(target);
  if (stats.isSymbolicLink()) fail(`allowlist path must not be a symlink: ${entry.value}`);
  if (entry.directory && !stats.isDirectory()) fail(`directory allowlist entry is not a directory: ${entry.value}`);
  if (!entry.directory && !stats.isFile()) fail(`file allowlist entry is not a file: ${entry.value}`);
}

function entryCoversPath(entry, repositoryPath) {
  return entry.directory
    ? repositoryPath.startsWith(`${entry.trimmed}/`)
    : repositoryPath === entry.trimmed;
}

function assertDirectoryContentsAreReleaseSafe(repoRoot, entry) {
  if (!entry.directory) return;
  const directoryRoot = path.resolve(repoRoot, ...entry.trimmed.split("/"));
  const pending = [{ absolute: directoryRoot, repositoryPath: entry.trimmed }];

  while (pending.length > 0) {
    const current = pending.pop();
    for (const child of readdirSync(current.absolute, { withFileTypes: true })) {
      const childRepositoryPath = `${current.repositoryPath}/${child.name}`;
      const childAbsolutePath = path.join(current.absolute, child.name);
      if (isProtectedRepositoryPath(childRepositoryPath)) {
        fail(`allowlisted directory contains protected local path: ${childRepositoryPath}`);
      }
      const stats = lstatSync(childAbsolutePath);
      if (stats.isSymbolicLink()) {
        fail(`allowlisted directory contains symlink: ${childRepositoryPath}`);
      }
      if (stats.isDirectory()) {
        pending.push({ absolute: childAbsolutePath, repositoryPath: childRepositoryPath });
      }
    }
  }
}

export function validateAllowlist({ manifest, repoRoot, changedPaths }) {
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
    fail("manifest must be a JSON object");
  }
  if (!repoRoot || !path.isAbsolute(repoRoot)) fail("repoRoot must be absolute");
  if (!Array.isArray(changedPaths)) fail("changedPaths must be an array");

  assertProtectedDeclarations(manifest);
  const rawEntries = [
    ...assertArray(manifest, "product_files"),
    ...assertArray(manifest, "verification_files"),
  ];
  const entries = rawEntries.map(normalizeManifestPath);
  const seen = new Set();
  for (const entry of entries) {
    if (seen.has(entry.value)) fail(`duplicate allowlist entry: ${entry.value}`);
    seen.add(entry.value);
    if (entry.trimmed === IMPLICIT_METADATA_PATH) {
      fail(`${IMPLICIT_METADATA_PATH} is implicit metadata and must not list itself`);
    }
    if (isProtectedRepositoryPath(entry.trimmed)) {
      fail(`protected local path must not be allowlisted: ${entry.value}`);
    }
    assertEntryExists(repoRoot, entry);
    assertDirectoryContentsAreReleaseSafe(repoRoot, entry);
  }

  const normalizedChanges = [...new Set(changedPaths.map(normalizeChangedPath))].sort();
  const relevantChanges = [];
  for (const repositoryPath of normalizedChanges) {
    if (repositoryPath === IMPLICIT_METADATA_PATH) continue;
    if (isProtectedRepositoryPath(repositoryPath)) {
      if (entries.some((entry) => entryCoversPath(entry, repositoryPath))) {
        fail(`protected changed path is covered by an allowlist entry: ${repositoryPath}`);
      }
      continue;
    }
    assertKnownChangedTopLevel(repositoryPath);
    relevantChanges.push(repositoryPath);
  }

  const missing = relevantChanges.filter((repositoryPath) => !entries.some((entry) => entryCoversPath(entry, repositoryPath)));
  if (missing.length > 0) {
    fail(`changed release-relevant paths are not allowlisted:\n${missing.map((item) => `- ${item}`).join("\n")}`);
  }

  return {
    allowlist_entries: entries.length,
    changed_paths: normalizedChanges.length,
    release_relevant_changes: relevantChanges.length,
    protected_or_implicit_changes: normalizedChanges.length - relevantChanges.length,
  };
}

function gitPaths(repoRoot, args) {
  const output = execFileSync("git", args, {
    cwd: repoRoot,
    encoding: "utf8",
    maxBuffer: 16 * 1024 * 1024,
    windowsHide: true,
  });
  return output.split("\0").filter(Boolean);
}

export function collectRepositoryChanges(repoRoot = DEFAULT_REPO_ROOT) {
  return [...new Set([
    ...gitPaths(repoRoot, ["diff", "--name-only", "-z"]),
    ...gitPaths(repoRoot, ["diff", "--cached", "--name-only", "-z"]),
    ...gitPaths(repoRoot, ["ls-files", "--others", "--exclude-standard", "-z"]),
  ])].sort();
}

// A historical v1.3 record never expands to describe later maintenance changes.
// The current source manifest has exact files (including literal Next route
// brackets) and a separate non-packaged verification inventory.
export function validateMaintenanceManifest({ manifest, repoRoot, changedPaths }) {
  if (manifest?.schema !== "story-continuity-maintenance-source-v1"
      || !Array.isArray(manifest.include) || !Array.isArray(manifest.verification_files)) {
    fail("invalid current maintenance manifest");
  }
  const exactPath = (value) => {
    if (typeof value !== "string" || !value || /[\\:*?"<>|\0]/.test(value)
        || value.split("/").some((part) => !part || part === "." || part === "..")) {
      fail("current manifest needs normalized exact paths");
    }
    return value;
  };
  const targets = new Set();
  for (const entry of manifest.include) {
    const target = exactPath(entry.target);
    if (targets.has(target.toLowerCase()) || isProtectedRepositoryPath(target)) {
      fail("duplicate or protected current package target");
    }
    targets.add(target.toLowerCase());
  }
  const names = [...manifest.include.map((entry) => entry.source), ...manifest.verification_files].map(exactPath);
  const seen = new Set();
  for (const name of names) {
    if (!(name === "README.md" || /^(backend|frontend|docs|deployment)\//.test(name))) {
      fail("unknown current manifest source root");
    }
    if (seen.has(name.toLowerCase()) || isProtectedRepositoryPath(name)) {
      fail("duplicate or protected current manifest source");
    }
    seen.add(name.toLowerCase());
    let target = repoRoot;
    for (const part of name.split("/")) {
      target = path.join(target, part);
      if (!existsSync(target) || lstatSync(target).isSymbolicLink()) {
        fail(`current manifest file is missing or linked: ${name}`);
      }
    }
    if (!lstatSync(target).isFile()) fail(`current manifest entries must be exact files: ${name}`);
  }
  const changes = [...new Set(changedPaths.map(normalizeChangedPath))];
  const relevant = changes.filter((name) => name !== IMPLICIT_METADATA_PATH && !isProtectedRepositoryPath(name));
  const missing = relevant.filter((name) => !seen.has(name.toLowerCase()));
  if (missing.length) fail(`current maintenance changes are not allowlisted:\n${missing.join("\n")}`);
  return { scope: "current_maintenance", allowlist_entries: names.length, changed_paths: changes.length,
    release_relevant_changes: relevant.length, protected_or_implicit_changes: changes.length - relevant.length };
}

export function validateRepository({
  repoRoot = DEFAULT_REPO_ROOT,
  manifestPath = path.join(repoRoot, ...IMPLICIT_METADATA_PATH.split("/")),
  changedPaths = collectRepositoryChanges(repoRoot),
} = {}) {
  let manifest;
  try {
    manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  } catch (error) {
    fail(`cannot read valid allowlist JSON at ${manifestPath}: ${error instanceof Error ? error.message : String(error)}`);
  }
  if (manifest.historical_scope && manifest.current_manifest) {
    const relative = normalizeManifestPath(manifest.current_manifest);
    if (relative.directory || !relative.trimmed.startsWith("docs/")) fail("invalid current manifest pointer");
    assertEntryExists(repoRoot, relative);
    const current = JSON.parse(readFileSync(path.join(repoRoot, relative.trimmed), "utf8"));
    return validateMaintenanceManifest({ manifest: current, repoRoot, changedPaths });
  }
  return validateAllowlist({ manifest, repoRoot, changedPaths });
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  try {
    const result = validateRepository();
    process.stdout.write(`${JSON.stringify({ status: "passed", ...result }, null, 2)}\n`);
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}
