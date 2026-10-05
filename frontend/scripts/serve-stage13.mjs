import { createServer } from "node:http";
import next from "next";
import { validateStage13Harness } from "../stage13-harness.mjs";

const harness = validateStage13Harness(process.env);
const hostname = "127.0.0.1";
const port = harness.frontendPort;

const application = next({ dev: false, hostname, port, dir: process.cwd() });
const handle = application.getRequestHandler();
await application.prepare();
createServer((request, response) => handle(request, response)).listen(port, hostname, () => {
  process.stdout.write(`Stage 13 ${harness.profileName} frontend ready on ${harness.frontendOrigin}\n`);
});
