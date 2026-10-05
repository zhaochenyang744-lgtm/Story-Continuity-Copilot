import { createHash } from "node:crypto";
import { lstat, readFile, readdir, stat } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { validateApiRewriteManifest } from "./assert-api-rewrite.mjs";

const textExtensions = new Set([".css", ".html", ".js", ".json", ".map", ".md", ".mjs", ".txt"]);
const forbidden = [
  { name: "file_uri", pattern: /file:\/\/[A-Za-z]:/i },
  { name: "test_endpoint", pattern: /\/api\/test\//i },
  { name: "test_account", pattern: /@example\.test|browser-e2e-test-provider/i },
  { name: "test_hook", pattern: /\b(?:E2E_|STAGE12_|STAGE13_|V130_HARNESS_)/ },
  { name: "raw_provider_fixture", pattern: /E2E_ANALYSIS_|STAGE12_BLOCK|raw_provider_body/i },
  { name: "secret_material", pattern: /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{16,}/ },
];

async function filesUnder(root) {
  const result = [];
  async function visit(current) {
    const info = await lstat(current);
    if (info.isSymbolicLink()) throw new Error(`V130_RELEASE_LINK_FORBIDDEN:${path.basename(current)}`);
    if (info.isDirectory()) {
      for (const entry of await readdir(current)) await visit(path.join(current, entry));
      return;
    }
    if (info.isFile()) result.push(current);
  }
  await visit(root);
  return result;
}

function scanText(value, relativePath, identities) {
  const folded = value.toLocaleLowerCase();
  for (const identity of identities.filter(Boolean)) {
    const normalized = String(identity).replaceAll("/", "\\").toLocaleLowerCase();
    const escaped = normalized.replaceAll("\\", "\\\\");
    if (folded.includes(normalized) || folded.includes(escaped)) {
      throw new Error(`V130_RELEASE_IDENTITY_HIT:${relativePath}`);
    }
  }
  for (const rule of forbidden) {
    if (rule.pattern.test(value)) throw new Error(`V130_RELEASE_${rule.name.toUpperCase()}:${relativePath}`);
  }
}

export async function scanV130ReleaseArtifact(artifactRoot, { distDir, backendOrigin, identities = [] }) {
  const root = path.resolve(artifactRoot);
  const required = [
    "server.js",
    path.join(distDir, "routes-manifest.json"),
    path.join(distDir, "static"),
    "public",
  ];
  for (const relativePath of required) await stat(path.join(root, relativePath));
  const manifestPath = path.join(root, distDir, "routes-manifest.json");
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  const rewrite = validateApiRewriteManifest(manifest, backendOrigin);
  const files = await filesUnder(root);
  let scannedTextFiles = 0;
  let scannedBytes = 0;
  const digest = createHash("sha256");
  for (const file of files.sort()) {
    const relativePath = path.relative(root, file).replaceAll("\\", "/");
    const bytes = await readFile(file);
    digest.update(relativePath).update("\0").update(bytes);
    if (!textExtensions.has(path.extname(file).toLocaleLowerCase())) continue;
    scannedTextFiles += 1;
    scannedBytes += bytes.length;
    scanText(bytes.toString("utf8"), relativePath, identities);
  }
  return {
    status: "passed",
    artifact_sha256: digest.digest("hex"),
    file_count: files.length,
    scanned_text_files: scannedTextFiles,
    scanned_text_bytes: scannedBytes,
    rewrite,
    provider_http_calls: 0,
    smtp_external_calls: 0,
    external_network_calls: 0,
  };
}

async function main() {
  const [artifactRoot, distDir, backendOrigin, ...identities] = process.argv.slice(2);
  if (!artifactRoot || !distDir || !backendOrigin) {
    throw new Error("usage: node scripts/v130-release-scan.mjs <artifact> <dist> <backend-origin> [identity ...]");
  }
  process.stdout.write(`${JSON.stringify(await scanV130ReleaseArtifact(artifactRoot, { distDir, backendOrigin, identities }))}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
}
