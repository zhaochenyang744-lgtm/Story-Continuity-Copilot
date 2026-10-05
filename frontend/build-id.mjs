import { createHash } from "node:crypto";
import { lstat, readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const BUILD_ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;
export const SOURCE_BUILD_ID_FILES = Object.freeze([
  "build-id.mjs",
  "build-origin.mjs",
  "next.config.mjs",
  "package-lock.json",
  "package.json",
  "public-config.mjs",
  "tsconfig.json",
]);
export const SOURCE_BUILD_ID_DIRECTORIES = Object.freeze(["app"]);

export function optionalBuildId(value) {
  if (value === undefined) return undefined;
  if (!BUILD_ID_PATTERN.test(value)) {
    throw new Error("NEXT_BUILD_ID_INVALID: expected 1-64 lowercase ASCII letters, digits, or hyphens");
  }
  return value;
}

function appendFramed(hash, value) {
  const bytes = Buffer.isBuffer(value) ? value : Buffer.from(value, "utf8");
  const length = Buffer.alloc(8);
  length.writeBigUInt64BE(BigInt(bytes.length));
  hash.update(length);
  hash.update(bytes);
}

export function sourceBuildIdFromEntries(entries) {
  const normalized = entries.map(({ relativePath, bytes }) => {
    const name = relativePath.replaceAll("\\", "/");
    if (!name || name.startsWith("/") || name.includes("../") || /^[A-Za-z]:/.test(name)) {
      throw new Error("SOURCE_BUILD_ID_PATH_INVALID");
    }
    return { relativePath: name, bytes: Buffer.from(bytes) };
  }).sort((left, right) => left.relativePath.localeCompare(right.relativePath, "en"));
  if (!normalized.length || new Set(normalized.map(({ relativePath }) => relativePath)).size !== normalized.length) {
    throw new Error("SOURCE_BUILD_ID_INPUT_INVALID");
  }
  const hash = createHash("sha256");
  hash.update("story-continuity-source-build-id-v1\0", "utf8");
  for (const entry of normalized) {
    appendFramed(hash, entry.relativePath);
    appendFramed(hash, entry.bytes);
  }
  return optionalBuildId(`s13v4-${hash.digest("hex").slice(0, 32)}`);
}

async function collectDirectory(root, relativeDirectory, entries) {
  const directory = path.join(root, relativeDirectory);
  for (const item of await readdir(directory, { withFileTypes: true })) {
    const relativePath = path.posix.join(relativeDirectory.replaceAll("\\", "/"), item.name);
    if (item.isSymbolicLink()) throw new Error(`SOURCE_BUILD_ID_SYMLINK_FORBIDDEN:${relativePath}`);
    if (item.isDirectory()) {
      await collectDirectory(root, relativePath, entries);
    } else if (item.isFile()) {
      entries.push({ relativePath, bytes: await readFile(path.join(root, relativePath)) });
    } else {
      throw new Error(`SOURCE_BUILD_ID_INPUT_TYPE_FORBIDDEN:${relativePath}`);
    }
  }
}

export async function computeSourceBuildId(root) {
  const resolvedRoot = path.resolve(root);
  const entries = [];
  for (const relativePath of SOURCE_BUILD_ID_FILES) {
    const inputPath = path.join(resolvedRoot, relativePath);
    const stat = await lstat(inputPath);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`SOURCE_BUILD_ID_FILE_INVALID:${relativePath}`);
    entries.push({ relativePath, bytes: await readFile(inputPath) });
  }
  for (const relativeDirectory of SOURCE_BUILD_ID_DIRECTORIES) {
    const stat = await lstat(path.join(resolvedRoot, relativeDirectory));
    if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error(`SOURCE_BUILD_ID_DIRECTORY_INVALID:${relativeDirectory}`);
    await collectDirectory(resolvedRoot, relativeDirectory, entries);
  }
  return sourceBuildIdFromEntries(entries);
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  if (process.argv.length !== 3) throw new Error("usage: node build-id.mjs <frontend-root>");
  process.stdout.write(`${await computeSourceBuildId(process.argv[2])}\n`);
}
