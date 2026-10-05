import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

function rewritesFrom(manifest) {
  if (Array.isArray(manifest.rewrites)) return manifest.rewrites;
  if (manifest.rewrites && typeof manifest.rewrites === "object") {
    return [
      ...(manifest.rewrites.beforeFiles || []),
      ...(manifest.rewrites.afterFiles || []),
      ...(manifest.rewrites.fallback || []),
    ];
  }
  return [];
}
export function validateApiRewriteManifest(manifest, expectedOrigin) {
  const expectedDestination = `${expectedOrigin}/api/:path*`;
  const rewrites = rewritesFrom(manifest);
  if (
    rewrites.length !== 1 ||
    rewrites[0]?.source !== "/api/:path*" ||
    rewrites[0]?.destination !== expectedDestination
  ) {
    throw new Error(
      `COMPILED_REWRITE_MISMATCH: expected only ${expectedDestination}`,
    );
  }

  const destination = rewrites[0].destination;
  const parsed = new URL(destination.replace(":path*", "probe"));
  if (parsed.origin !== expectedOrigin) {
    throw new Error(`COMPILED_REWRITE_ORIGIN_MISMATCH: ${parsed.origin}`);
  }
  return { destination, rewriteCount: rewrites.length };
}

async function main() {
  const [manifestPath, expectedOrigin] = process.argv.slice(2);
  if (!manifestPath || !expectedOrigin) {
    throw new Error(
      "usage: node scripts/assert-api-rewrite.mjs <routes-manifest.json> <expected-origin>",
    );
  }
  const bytes = await readFile(manifestPath);
  const manifest = JSON.parse(bytes.toString("utf8"));
  const result = validateApiRewriteManifest(manifest, expectedOrigin);
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  process.stdout.write(
    `${JSON.stringify({ manifestPath, sha256, ...result })}\n`,
  );
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
}
