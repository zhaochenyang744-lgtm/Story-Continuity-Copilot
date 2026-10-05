import { cp, mkdir, mkdtemp } from "node:fs/promises";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const frontendRoot = path.resolve(import.meta.dirname, "..");
const productionRoute = path.join(frontendRoot, "app", "test-writing-tools", "page.tsx");
if (existsSync(productionRoute)) {
  throw new Error("Remove app/test-writing-tools before staging the browser fixture");
}

const stage = await mkdtemp(path.join(tmpdir(), "story-rich-suggestion-e2e-"));
for (const directory of ["app", "public"]) {
  await cp(path.join(frontendRoot, directory), path.join(stage, directory), { recursive: true, errorOnExist: true });
}
for (const file of ["package.json", "package-lock.json", "next.config.mjs", "tsconfig.json", "next-env.d.ts", "build-id.mjs", "build-origin.mjs", "public-config.mjs"]) {
  await cp(path.join(frontendRoot, file), path.join(stage, file), { errorOnExist: true });
}

const support = path.join(stage, "e2e", "support");
const route = path.join(stage, "app", "test-writing-tools");
await mkdir(support, { recursive: true });
await mkdir(route, { recursive: true });
await cp(path.join(frontendRoot, "e2e", "support", "RichSuggestionHarness.tsx"), path.join(support, "RichSuggestionHarness.tsx"));
await cp(path.join(frontendRoot, "e2e", "support", "RichSuggestionPage.tsx"), path.join(route, "page.tsx"));
// Turbopack rejects a node_modules link that resolves outside the staged root.
await cp(path.join(frontendRoot, "node_modules"), path.join(stage, "node_modules"), { recursive: true, dereference: true, errorOnExist: true });

console.log(JSON.stringify({ stage, testRoute: path.join(route, "page.tsx"), productionRouteAbsent: !existsSync(productionRoute) }));
