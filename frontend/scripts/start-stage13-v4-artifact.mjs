import { existsSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { scanStage13V4Artifact, stage13V4Profiles } from "./stage13-v4-policy.mjs";

const [artifactDir, profileName, ...firstPartyRoots] = process.argv.slice(2);
const profile = stage13V4Profiles[profileName];
if (!artifactDir || !profile) throw new Error("usage: node scripts/start-stage13-v4-artifact.mjs <artifact-dir> <v4impl|v4pm3> [first-party-root ...]");
if (existsSync(profile.genericRoot)) throw new Error("STAGE13_V4_STAGING_ENTRY_MUST_BE_UNAVAILABLE");
await scanStage13V4Artifact(artifactDir, profileName, firstPartyRoots);
process.env.HOSTNAME = "127.0.0.1";
process.env.PORT = new URL(profile.frontendOrigin).port;
process.chdir(path.resolve(artifactDir));
await import(pathToFileURL(path.join(process.cwd(), "server.js")).href);
