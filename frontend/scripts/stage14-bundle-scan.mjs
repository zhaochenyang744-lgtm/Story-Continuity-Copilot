import { createHash } from "node:crypto";
import { readdir, readFile, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { firstPartyIdentities, identityVariants } from "./stage13-v4-policy.mjs";

const frontendRootFiles = new Set([
  "build-id.mjs",
  "build-origin.mjs",
  "next.config.mjs",
  "next-env.d.ts",
  "package-lock.json",
  "package.json",
  "public-config.mjs",
  "tsconfig.json",
]);
const frontendRootDirectories = new Set(["app", "public"]);
const forbiddenNativeExtensions = new Set([".dll", ".dylib", ".exe", ".node", ".pdb", ".so"]);

async function filesBelow(root) {
  const files = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const full = path.join(root, entry.name);
    if (entry.isSymbolicLink()) throw new Error("STAGE14_BUNDLE_LINK_FORBIDDEN");
    if (entry.isDirectory()) files.push(...await filesBelow(full));
    else if (entry.isFile()) files.push(full);
    else throw new Error("STAGE14_BUNDLE_SPECIAL_FILE_FORBIDDEN");
  }
  return files;
}

function count(bytes, value) {
  if (!value) return 0;
  let hits = 0;
  let offset = 0;
  const target = Buffer.from(value, "utf8");
  while ((offset = bytes.indexOf(target, offset)) !== -1) {
    hits += 1;
    offset += target.length;
  }
  return hits;
}

export function scanDeployableBytes(bytes, firstPartyRoots = [], secretValues = []) {
  const text = bytes.toString("utf8");
  const folded = text.toLocaleLowerCase("en-US");
  const identities = firstPartyIdentities(firstPartyRoots).flatMap(identityVariants);
  if (identities.some((identity) => identity && folded.includes(identity.toLocaleLowerCase("en-US")))) throw new Error("STAGE14_BUNDLE_LEVEL1_HIT");
  const forbidden = ["story-continuity-poc", "held-out", "valid-password-13", "capture mailer", "/api/test/stage13"];
  if (forbidden.some((literal) => folded.includes(literal.toLocaleLowerCase("en-US")))) throw new Error("STAGE14_BUNDLE_LEVEL0_HIT");
  if (/#token=[A-Za-z0-9_-]{32,}/.test(text)) throw new Error("STAGE14_BUNDLE_LEVEL0_HIT");
  if (/[A-Za-z]:\\(?:Users|Documents)\\/i.test(text) || /\/(?:Users|home)\/[^/]+\//.test(text) || /\\\\[A-Za-z0-9._-]+\\[A-Za-z0-9$._-]+\\/.test(text)) throw new Error("STAGE14_BUNDLE_ABSOLUTE_PATH_HIT");
  if (/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i.test(text)) throw new Error("STAGE14_BUNDLE_EMAIL_HIT");
  if (secretValues.some((value) => value && count(bytes, value))) throw new Error("STAGE14_BUNDLE_SECRET_HIT");
}

export function assertPortableBundlePath(relativePath) {
  const normalized = relativePath.replaceAll("\\", "/");
  const segments = normalized.toLocaleLowerCase("en-US").split("/");
  if (segments.some((segment) => segment === "node_modules" || segment === "frontend-artifact" || segment === ".next" || segment.startsWith(".next-"))) {
    throw new Error("STAGE14_BUNDLE_PREBUILT_FRONTEND_FORBIDDEN");
  }
  if (segments.some((segment) => segment === "tests" || segment === "test-results" || segment === "e2e" || segment === "agents.md" || segment === "claude.md" || segment === ".env" || segment.startsWith(".env."))) {
    throw new Error("STAGE14_BUNDLE_CONTROL_FILE_FORBIDDEN");
  }
  if (segments.some((segment) => segment.includes("win32") || segment.includes("windows"))) throw new Error("STAGE14_BUNDLE_WINDOWS_PATH_FORBIDDEN");
  if (forbiddenNativeExtensions.has(path.extname(normalized).toLocaleLowerCase("en-US"))) throw new Error("STAGE14_BUNDLE_NATIVE_FILE_FORBIDDEN");
}

export function assertPortableBundleBytes(bytes) {
  if (bytes.length >= 2 && bytes[0] === 0x4d && bytes[1] === 0x5a) throw new Error("STAGE14_BUNDLE_PE_BINARY_FORBIDDEN");
  if (bytes.length >= 4 && bytes.subarray(0, 4).equals(Buffer.from([0x7f, 0x45, 0x4c, 0x46]))) throw new Error("STAGE14_BUNDLE_ELF_BINARY_FORBIDDEN");
  const magic = bytes.length >= 4 ? bytes.readUInt32BE(0) : 0;
  if ([0xfeedface, 0xfeedfacf, 0xcefaedfe, 0xcffaedfe, 0xcafebabe, 0xbebafeca].includes(magic)) throw new Error("STAGE14_BUNDLE_MACHO_BINARY_FORBIDDEN");
}

async function validateFrontendSource(sourceRoot) {
  const entries = await readdir(sourceRoot, { withFileTypes: true });
  const presentFiles = new Set();
  let hasApp = false;
  for (const entry of entries) {
    if (entry.isSymbolicLink()) throw new Error("STAGE14_BUNDLE_LINK_FORBIDDEN");
    if (entry.isFile() && frontendRootFiles.has(entry.name)) presentFiles.add(entry.name);
    else if (entry.isDirectory() && frontendRootDirectories.has(entry.name)) {
      if (entry.name === "app") hasApp = true;
    } else {
      throw new Error("STAGE14_FRONTEND_SOURCE_ALLOWLIST_VIOLATION");
    }
  }
  if (!hasApp || [...frontendRootFiles].some((name) => !presentFiles.has(name))) throw new Error("STAGE14_FRONTEND_SOURCE_INCOMPLETE");
  if ((await filesBelow(path.join(sourceRoot, "app"))).length === 0) throw new Error("STAGE14_FRONTEND_SOURCE_INCOMPLETE");
}

function validatePublicBaseUrl(value) {
  let url;
  try { url = new URL(value); } catch { throw new Error("STAGE14_PLATFORM_METADATA_INVALID"); }
  if (url.protocol !== "https:" || url.username || url.password || url.port || url.pathname !== "/" || url.search || url.hash) throw new Error("STAGE14_PLATFORM_METADATA_INVALID");
}

export function validateStage14PlatformMetadata(metadata, profileName) {
  const expectedKeys = ["backendOrigin", "frontendBuild", "profile", "publicBaseUrl", "targetArch", "targetLibc", "targetOs"];
  if (Object.keys(metadata).sort().join("\n") !== expectedKeys.join("\n")) throw new Error("STAGE14_PLATFORM_METADATA_INVALID");
  if (metadata.profile !== profileName || metadata.backendOrigin !== "http://backend:8000" || metadata.targetOs !== "linux" || metadata.targetArch !== "amd64" || metadata.targetLibc !== "musl" || metadata.frontendBuild !== "docker-multistage-source") {
    throw new Error("STAGE14_PLATFORM_METADATA_MISMATCH");
  }
  validatePublicBaseUrl(metadata.publicBaseUrl);
  return metadata;
}

async function validatePlatformMetadata(root, profileName) {
  const metadata = JSON.parse(await readFile(path.join(root, "stage14-platform-metadata.json"), "utf8"));
  return validateStage14PlatformMetadata(metadata, profileName);
}

async function validateBuildContract(root) {
  const dockerfile = await readFile(path.join(root, "deployment", "Dockerfile.frontend"), "utf8");
  const compose = await readFile(path.join(root, "deployment", "compose.yaml"), "utf8");
  const dockerignore = await readFile(path.join(root, ".dockerignore"), "utf8");
  const release = await readFile(path.join(root, "deployment", "release.sh"), "utf8");
  const rollback = await readFile(path.join(root, "deployment", "rollback.sh"), "utf8");
  const verifier = await readFile(path.join(root, "deployment", "verify-frontend-image.sh"), "utf8");
  if ((dockerfile.match(/^FROM --platform=linux\/amd64 node:[^\s]+-alpine[^\s]* AS /gm) || []).length !== 3
    || !/COPY frontend-source\/package\.json frontend-source\/package-lock\.json \.\//.test(dockerfile)
    || !/RUN npm ci/.test(dockerfile)
    || !/COPY frontend-source\/ \.\//.test(dockerfile)
    || !/npm run build/.test(dockerfile)
    || /frontend-artifact/.test(dockerfile)) throw new Error("STAGE14_FRONTEND_DOCKER_CONTRACT_INVALID");
  const backendService = compose.split("\n  backend:\n", 2)[1]?.split("\n  frontend:\n", 1)[0] || "";
  const frontendService = compose.split("\n  frontend:\n", 2)[1]?.split("\n  caddy:\n", 1)[0] || "";
  const caddyService = compose.split("\n  caddy:\n", 2)[1]?.split("\nvolumes:\n", 1)[0] || "";
  if (!/context: \.\./.test(backendService)
    || !/dockerfile: deployment\/Dockerfile\.backend/.test(backendService)
    || !/context: \.\./.test(frontendService)
    || !/dockerfile: deployment\/Dockerfile\.frontend/.test(frontendService)
    || !/args:\s*\n\s+PUBLIC_BASE_URL: https:\/\/\$\{PUBLIC_HOST:\?public host required\}/.test(frontendService)
    || !/\.\/Caddyfile:\/etc\/caddy\/Caddyfile:ro/.test(caddyService)
    || /\.\/deployment\/Caddyfile/.test(caddyService)) throw new Error("STAGE14_FRONTEND_COMPOSE_CONTRACT_INVALID");
  if (!/^!frontend-source\/$/m.test(dockerignore) || !/^!frontend-source\/\*\*$/m.test(dockerignore) || /frontend-artifact/.test(dockerignore)) throw new Error("STAGE14_DOCKERIGNORE_CONTRACT_INVALID");
  if (![release, rollback].every((script) => /verify-frontend-image\.sh/.test(script))) throw new Error("STAGE14_FRONTEND_VERIFY_NOT_ENFORCED");
  if (!/linux\/amd64/.test(verifier) || !/linux\/x64/.test(verifier) || !/musl/.test(verifier) || !/\*\.node/.test(verifier) || !/7f454c46/.test(verifier) || !/sharp-linuxmusl-x64/.test(verifier)) throw new Error("STAGE14_FRONTEND_VERIFY_CONTRACT_INVALID");
}

export async function scanStage14Bundle(bundleRoot, profileName, firstPartyRoots = []) {
  const root = path.resolve(bundleRoot);
  const relativeToTemp = path.relative(path.resolve(tmpdir()), root);
  if (!relativeToTemp || relativeToTemp.startsWith("..") || path.isAbsolute(relativeToTemp)) throw new Error("STAGE14_BUNDLE_OUTSIDE_SYSTEM_TEMP");
  if (!(await stat(root)).isDirectory() || !path.basename(root).startsWith("story-stage14-bundle-")) throw new Error("STAGE14_BUNDLE_ROOT_INVALID");
  const topLevel = await readdir(root);
  const expectedTopLevel = [".dockerignore", "backend", "deployment", "frontend-source", "stage14-platform-metadata.json"];
  if (topLevel.sort().join("\n") !== expectedTopLevel.join("\n")) throw new Error("STAGE14_BUNDLE_TOP_LEVEL_INVALID");
  await validateFrontendSource(path.join(root, "frontend-source"));
  const metadata = await validatePlatformMetadata(root, profileName);
  await validateBuildContract(root);
  const secretValues = ["CONTINUITY_API_KEY", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "RECOVERY_HASH_SECRET"]
    .map((name) => process.env[name]).filter(Boolean);
  const files = (await filesBelow(root)).sort((left, right) => path.relative(root, left).localeCompare(path.relative(root, right), "en"));
  const contentHash = createHash("sha256");
  for (const file of files) {
    const relative = path.relative(root, file).replaceAll("\\", "/");
    const bytes = await readFile(file);
    try {
      assertPortableBundlePath(relative);
      assertPortableBundleBytes(bytes);
      scanDeployableBytes(bytes, firstPartyRoots, secretValues);
    } catch (error) {
      throw new Error(`${error.message}:${relative}`);
    }
    contentHash.update(relative).update("\0").update(createHash("sha256").update(bytes).digest()).update("\n");
  }
  const relative = files.map((file) => path.relative(root, file).replaceAll("\\", "/")).sort();
  const digest = createHash("sha256").update(relative.join("\n")).digest("hex").toUpperCase();
  return {
    fileCount: files.length,
    fileListSha256: digest,
    contentSha256: contentHash.digest("hex").toUpperCase(),
    target: `${metadata.targetOs}/${metadata.targetArch}/${metadata.targetLibc}`,
    frontendBuild: metadata.frontendBuild,
    secretHits: 0,
    identityHits: 0,
    absolutePathHits: 0,
    nativeBinaryHits: 0,
  };
}

async function main() {
  const [bundleRoot, profileName, ...firstPartyRoots] = process.argv.slice(2);
  if (!bundleRoot || !profileName) throw new Error("usage: node scripts/stage14-bundle-scan.mjs <bundle> <profile> [first-party-root ...]");
  process.stdout.write(`${JSON.stringify(await scanStage14Bundle(bundleRoot, profileName, firstPartyRoots))}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => { process.stderr.write(`${error.message}\n`); process.exitCode = 1; });
}
