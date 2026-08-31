import { lstat, readdir, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { extractAbsoluteLiterals, firstPartyIdentities, identityVariants, level3Tuples, stage13V4Profiles } from "./stage13-v4-policy.mjs";

const TEXT_EXTENSIONS = new Set([".css", ".csv", ".html", ".js", ".json", ".log", ".map", ".md", ".mjs", ".svg", ".txt", ".xml"]);

async function filesBelow(root) {
  const found = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const full = path.join(root, entry.name);
    if (entry.isSymbolicLink()) throw new Error(`STAGE13_V4_RUNTIME_LINK_FORBIDDEN:${entry.name}`);
    if (entry.isDirectory()) found.push(...await filesBelow(full));
    else if (entry.isFile()) found.push(full);
    else throw new Error(`STAGE13_V4_RUNTIME_ENTRY_TYPE_FORBIDDEN:${entry.name}`);
  }
  return found;
}

function pathScanText(buffer, extension) {
  if (TEXT_EXTENSIONS.has(extension.toLowerCase())) return buffer.toString("utf8");
  return (buffer.toString("latin1").match(/[\x20-\x7e]{4,}/g) || []).join("\n");
}

export async function scanStage13V4RuntimeEvidence(evidenceDir, profileName, firstPartyRoots = []) {
  const profile = stage13V4Profiles[profileName];
  if (!evidenceDir || !profile) throw new Error("STAGE13_V4_RUNTIME_PROFILE_INVALID");
  const evidence = path.resolve(evidenceDir);
  const relativeToTemp = path.relative(path.resolve(tmpdir()), evidence);
  if (!relativeToTemp || relativeToTemp.startsWith("..") || path.isAbsolute(relativeToTemp) || !evidence.split(path.sep).some((part) => part.startsWith(profile.tempPrefix))) throw new Error("STAGE13_V4_RUNTIME_EVIDENCE_PROFILE_MISMATCH");
  const evidenceStat = await lstat(evidence);
  if (evidenceStat.isSymbolicLink()) throw new Error("STAGE13_V4_RUNTIME_LINK_FORBIDDEN:evidence-root");
  if (!evidenceStat.isDirectory()) throw new Error("STAGE13_V4_RUNTIME_EVIDENCE_NOT_DIRECTORY");
  const level1Identities = firstPartyIdentities(firstPartyRoots);
  const forbidden = [...level1Identities.flatMap(identityVariants), profile.genericRoot, ...level3Tuples.map((tuple) => tuple.literal), "valid-password-13", "#token=", "/api/test/stage13", "stage13-browser-injected-provider", "capture mailer"];
  const hits = [];
  const files = await filesBelow(evidence);
  for (const file of files) {
    const buffer = await readFile(file);
    const scannedText = pathScanText(buffer, path.extname(file));
    const folded = scannedText.toLocaleLowerCase("en-US");
    const relative = path.relative(evidence, file).replaceAll("/", "\\");
    for (const literal of forbidden) if (literal && folded.includes(literal.toLocaleLowerCase("en-US"))) hits.push({ relative, literal });
    for (const literal of extractAbsoluteLiterals(scannedText)) hits.push({ relative, literal });
    for (const literal of scannedText.match(/stage13v4(?:impl|pm3)[a-z0-9_.-]*@example\.test/gi) || []) hits.push({ relative, literal });
  }
  if (hits.length) throw new Error(`STAGE13_V4_RUNTIME_HIT:${JSON.stringify(hits)}`);
  return { profile: profileName, fileCount: files.length, level0Hits: 0, level1Hits: 0, level4AbsoluteHits: 0 };
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const [evidenceDir, profileName, ...firstPartyRoots] = process.argv.slice(2);
  if (!evidenceDir || !profileName) throw new Error("usage: node scripts/stage13-v4-runtime-scan.mjs <evidence-dir> <v4impl|v4pm3> [first-party-root ...]");
  process.stdout.write(`${JSON.stringify(await scanStage13V4RuntimeEvidence(evidenceDir, profileName, firstPartyRoots))}\n`);
}
