import { createHash } from "node:crypto";
import { readdir, readFile, stat } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

export const stage13V4Profiles = Object.freeze({
  v4impl: Object.freeze({
    frontendOrigin: "http://127.0.0.1:3084",
    backendOrigin: "http://127.0.0.1:8084",
    distDir: ".next-stage13-v4-impl",
    tempPrefix: "story-stage13-v4-impl-",
    genericRoot: "V:\\",
    genericCounts: Object.freeze({ "server.js": 3, ".next-stage13-v4-impl\\required-server-files.json": 4 }),
  }),
  v4pm3: Object.freeze({
    frontendOrigin: "http://127.0.0.1:3085",
    backendOrigin: "http://127.0.0.1:8085",
    distDir: ".next-stage13-v4-pm3",
    tempPrefix: "story-stage13-v4-pm3-",
    genericRoot: "W:\\",
    genericCounts: Object.freeze({ "server.js": 3, ".next-stage13-v4-pm3\\required-server-files.json": 4 }),
  }),
});

export const level3Tuples = Object.freeze([
  Object.freeze({ literal: String.raw`D:\a\sharp\sharp\src\build\Release\sharp-win32-x64-0.35.3.pdb`, packageName: "@img/sharp-win32-x64", version: "0.35.3", relative: "node_modules\\@img\\sharp-win32-x64\\lib\\sharp-win32-x64-0.35.3.node", count: 1, sha256: "45DBB968DFF27A1E8D8870D2A34E6F5418FA2A1A4FE27A7ED13AB2FB3F895468" }),
  Object.freeze({ literal: String.raw`C:\\path\\to\\file`, packageName: "next", version: "16.3.3", relative: "node_modules\\next\\dist\\lib\\find-config.js", count: 1, sha256: "C47CC064EC1F5F09133A4A13C22FFD0BCC1AAFD46A0D28B5FA6227A95586F71A" }),
  Object.freeze({ literal: "/Users/foo/", packageName: "next", version: "16.3.3", relative: "node_modules\\next\\dist\\server\\patch-error-inspect.js", count: 1, sha256: "7827C52811C9E79838881EC81DC22933682D26E36500D75F5E2184732317914B" }),
  Object.freeze({ literal: String.raw`C:\Users\foo\APP\.next\server\chunks\ssr\[root-of-the-server]__2934a0._.js`, packageName: "next", version: "16.3.3", relative: "node_modules\\next\\dist\\server\\patch-error-inspect.js", count: 1, sha256: "7827C52811C9E79838881EC81DC22933682D26E36500D75F5E2184732317914B" }),
]);

export function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex").toUpperCase();
}

export function countLiteral(bytes, literal) {
  const target = Buffer.from(literal, "utf8");
  let count = 0;
  let offset = 0;
  while ((offset = bytes.indexOf(target, offset)) !== -1) {
    count += 1;
    offset += target.length;
  }
  return count;
}

async function filesBelow(root) {
  const found = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const full = path.join(root, entry.name);
    if (entry.isSymbolicLink()) throw new Error(`STAGE13_V4_ARTIFACT_SYMLINK:${entry.name}`);
    if (entry.isDirectory()) found.push(...await filesBelow(full));
    else if (entry.isFile()) found.push(full);
  }
  return found;
}

function relativeFile(root, file) {
  return path.relative(root, file).replaceAll("/", "\\");
}

function unicodeEscape(value, { all = false, uppercase = false } = {}) {
  let escaped = "";
  for (let index = 0; index < value.length; index += 1) {
    const codeUnit = value.charCodeAt(index);
    if (all || codeUnit < 0x20 || codeUnit > 0x7e) {
      const hex = codeUnit.toString(16).padStart(4, "0");
      escaped += `\\u${uppercase ? hex.toUpperCase() : hex}`;
    } else {
      escaped += value[index];
    }
  }
  return escaped;
}

export function identityVariants(value) {
  if (!value) return [];
  const slash = value.replaceAll("\\", "/");
  const backslash = value.replaceAll("/", "\\");
  const bases = [value, slash, backslash, JSON.stringify(value).slice(1, -1), JSON.stringify(backslash).slice(1, -1)];
  return [...new Set(bases.flatMap((base) => [
    base,
    unicodeEscape(base),
    unicodeEscape(base, { uppercase: true }),
    unicodeEscape(base, { all: true }),
    unicodeEscape(base, { all: true, uppercase: true }),
  ]))];
}

export function firstPartyIdentities(firstPartyRoots = []) {
  const home = path.resolve(homedir());
  const identities = [
    home,
    path.basename(home),
    "Story-Continuity-Copilot",
    "story-continuity-web-demo",
    "story-continuity-web-demo-frontend",
    ...firstPartyRoots,
  ];
  for (const root of firstPartyRoots) {
    if (!path.isAbsolute(root)) continue;
    const resolved = path.resolve(root);
    const relativeToHome = path.relative(home, resolved);
    if (!relativeToHome || relativeToHome.startsWith("..") || path.isAbsolute(relativeToHome)) continue;
    const parts = relativeToHome.split(path.sep).filter(Boolean);
    if (parts.length >= 2) identities.push(path.join(parts[0], parts[1]));
    for (const part of parts) {
      if (/[^\x00-\x7f]/.test(part) || /story[-_]/i.test(part)) identities.push(part);
    }
    if (parts.at(-1)?.toLocaleLowerCase("en-US") === "frontend" && parts.length >= 2) {
      identities.push(`${parts.at(-2)}-frontend`);
    }
  }
  return [...new Set(identities.filter(Boolean))];
}

export function extractAbsoluteLiterals(text) {
  const patterns = [
    /(?<![A-Za-z0-9])[A-Za-z]:\\+(?:[^\\\x00\r\n"'`]+\\+)+[^\\\x00\r\n"'`]*/g,
    /(?<!\\)\\\\[A-Za-z0-9._-]+\\[A-Za-z0-9.$_-]+(?:\\[^\\\x00\r\n"'`]*)*/g,
    /\/(?:Users|home)\/[A-Za-z0-9._-]+\//g,
    /(?<![A-Za-z0-9])[A-Z]:\\+(?=["'])/g,
  ];
  return patterns.flatMap((pattern) => text.match(pattern) || []);
}

function packagePath(artifact, packageName) {
  return packageName === "next"
    ? path.join(artifact, "node_modules", "next", "package.json")
    : path.join(artifact, "node_modules", "@img", "sharp-win32-x64", "package.json");
}

export async function scanStage13V4Artifact(artifactDir, profileName, firstPartyRoots = []) {
  const profile = stage13V4Profiles[profileName];
  if (!profile) throw new Error("STAGE13_V4_PROFILE_INVALID");
  const artifact = path.resolve(artifactDir);
  const relativeToTemp = path.relative(path.resolve(tmpdir()), artifact);
  if (!relativeToTemp || relativeToTemp.startsWith("..") || path.isAbsolute(relativeToTemp)) throw new Error("STAGE13_V4_ARTIFACT_OUTSIDE_SYSTEM_TEMP");
  if (!artifact.split(path.sep).some((part) => part.startsWith(profile.tempPrefix))) throw new Error("STAGE13_V4_ARTIFACT_PROFILE_MISMATCH");
  if (!(await stat(artifact)).isDirectory()) throw new Error("STAGE13_V4_ARTIFACT_NOT_DIRECTORY");

  const level0Literals = ["valid-password-13", "#token=", "stage13-browser-injected-provider", "capture mailer", "/api/test/stage13"];
  const level1Identities = firstPartyIdentities(firstPartyRoots);
  const level1Literals = level1Identities.flatMap(identityVariants).filter((value, index, values) => value && values.indexOf(value) === index);
  const files = await filesBelow(artifact);
  const level0Hits = [];
  const level1Hits = [];
  const level2Hits = [];
  const level3Hits = [];
  const unknownAbsoluteHits = [];

  for (const file of files) {
    const bytes = await readFile(file);
    const text = bytes.toString("utf8");
    const folded = text.toLocaleLowerCase("en-US");
    const relative = relativeFile(artifact, file);
    for (const literal of level0Literals) {
      const count = countLiteral(bytes, literal);
      if (count) level0Hits.push({ relative, literal, count });
    }
    const recoveryEmails = text.match(/stage13v4(?:impl|pm3)[a-z0-9_.-]*@example\.test/gi) || [];
    for (const literal of recoveryEmails) level0Hits.push({ relative, literal, count: 1 });
    for (const literal of level1Literals) {
      const count = folded.split(literal.toLocaleLowerCase("en-US")).length - 1;
      if (count) level1Hits.push({ relative, literal, count });
    }
    const genericCount = countLiteral(bytes, profile.genericRoot);
    if (genericCount) level2Hits.push({ relative, literal: profile.genericRoot, count: genericCount, sha256: sha256(bytes) });
    for (const tuple of level3Tuples) {
      const count = countLiteral(bytes, tuple.literal);
      if (count) level3Hits.push({ relative, literal: tuple.literal, count, sha256: sha256(bytes), packageName: tuple.packageName, version: tuple.version });
    }
    for (const literal of extractAbsoluteLiterals(text)) {
      const isLevel2 = relative in profile.genericCounts && literal.startsWith(profile.genericRoot);
      const isLevel3 = level3Tuples.some((tuple) => tuple.relative === relative && tuple.literal === literal);
      if (!isLevel2 && !isLevel3) unknownAbsoluteHits.push({ relative, literal });
    }
  }

  if (level0Hits.length) throw new Error(`STAGE13_V4_LEVEL0_HIT:${JSON.stringify(level0Hits)}`);
  if (level1Hits.length) throw new Error(`STAGE13_V4_LEVEL1_HIT:${JSON.stringify(level1Hits)}`);
  const expectedLevel2 = Object.entries(profile.genericCounts).sort(([a], [b]) => a.localeCompare(b));
  const actualLevel2 = level2Hits.map(({ relative, count }) => [relative, count]).sort(([a], [b]) => a.localeCompare(b));
  if (JSON.stringify(expectedLevel2) !== JSON.stringify(actualLevel2)) throw new Error(`STAGE13_V4_LEVEL2_MISMATCH:${JSON.stringify(level2Hits)}`);
  if (unknownAbsoluteHits.length) throw new Error(`STAGE13_V4_UNKNOWN_ABSOLUTE:${JSON.stringify(unknownAbsoluteHits)}`);

  const expectedLevel3 = [...level3Tuples].sort((a, b) => `${a.relative}:${a.literal}`.localeCompare(`${b.relative}:${b.literal}`));
  const actualLevel3 = level3Hits.sort((a, b) => `${a.relative}:${a.literal}`.localeCompare(`${b.relative}:${b.literal}`));
  if (actualLevel3.length !== expectedLevel3.length) throw new Error(`STAGE13_V4_LEVEL3_SET_MISMATCH:${JSON.stringify(actualLevel3)}`);
  for (let index = 0; index < expectedLevel3.length; index += 1) {
    const expected = expectedLevel3[index];
    const actual = actualLevel3[index];
    const packageJson = JSON.parse(await readFile(packagePath(artifact, expected.packageName), "utf8"));
    if (actual.relative !== expected.relative || actual.literal !== expected.literal || actual.count !== expected.count || actual.sha256 !== expected.sha256 || packageJson.version !== expected.version) {
      throw new Error(`STAGE13_V4_LEVEL3_TUPLE_MISMATCH:${JSON.stringify({ expected, actual, packageVersion: packageJson.version })}`);
    }
  }

  const rootPackage = JSON.parse(await readFile(path.join(artifact, "package.json"), "utf8"));
  if (rootPackage.name !== "story-continuity-app") throw new Error("STAGE13_V4_PACKAGE_NAME_MISMATCH");
  const routesBytes = await readFile(path.join(artifact, profile.distDir, "routes-manifest.json"));
  const routes = JSON.parse(routesBytes.toString("utf8"));
  const rewrites = [...(routes.rewrites?.beforeFiles || []), ...(routes.rewrites?.afterFiles || []), ...(routes.rewrites?.fallback || [])];
  const expectedDestination = `${profile.backendOrigin}/api/:path*`;
  if (rewrites.length !== 1 || rewrites[0]?.source !== "/api/:path*" || rewrites[0]?.destination !== expectedDestination) throw new Error("STAGE13_V4_REWRITE_MISMATCH");

  const fileList = files.map((file) => relativeFile(artifact, file)).sort();
  return {
    profile: profileName,
    packageName: rootPackage.name,
    fileCount: files.length,
    fileListSha256: sha256(Buffer.from(fileList.join("\n"))),
    level0Hits: [], level1Hits: [], unknownAbsoluteHits: [],
    level2Hits: level2Hits.sort((a, b) => a.relative.localeCompare(b.relative)),
    level3Hits: actualLevel3,
    routesSha256: sha256(routesBytes),
    rewriteDestination: expectedDestination,
  };
}

async function main() {
  const [artifactDir, profileName, ...firstPartyRoots] = process.argv.slice(2);
  if (!artifactDir || !profileName) throw new Error("usage: node scripts/stage13-v4-policy.mjs <artifact-dir> <v4impl|v4pm3> [first-party-root ...]");
  process.stdout.write(`${JSON.stringify(await scanStage13V4Artifact(artifactDir, profileName, firstPartyRoots))}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => { process.stderr.write(`${error.message}\n`); process.exitCode = 1; });
}
