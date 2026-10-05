import { scanStage13V4Artifact } from "./stage13-v4-policy.mjs";

const [firstArtifact, secondArtifact, profileName, ...firstPartyRoots] = process.argv.slice(2);
if (!firstArtifact || !secondArtifact || !profileName) throw new Error("usage: node scripts/stage13-v4-compare.mjs <first> <second> <profile> [first-party-root ...]");
const first = await scanStage13V4Artifact(firstArtifact, profileName, firstPartyRoots);
const second = await scanStage13V4Artifact(secondArtifact, profileName, firstPartyRoots);
const stableFields = ["fileCount", "fileListSha256", "level2Hits", "level3Hits", "routesSha256", "rewriteDestination"];
for (const field of stableFields) {
  if (JSON.stringify(first[field]) !== JSON.stringify(second[field])) throw new Error(`STAGE13_V4_STABILITY_MISMATCH:${field}`);
}
process.stdout.write(`${JSON.stringify({ profile: profileName, stable: true, fileCount: first.fileCount, fileListSha256: first.fileListSha256, level2Hits: first.level2Hits, level3Hits: first.level3Hits, routesSha256: first.routesSha256 })}\n`);
