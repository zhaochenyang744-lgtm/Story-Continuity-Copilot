import { createServer } from "node:http";
import next from "next";

const hostname = "127.0.0.1";
const port = 3072;
if (process.env.NEXT_DIST_DIR !== ".next-stage12-v2-impl") {
  throw new Error("Stage 12 V2 production server requires the isolated dist directory");
}
if (process.env.BACKEND_ORIGIN !== "http://127.0.0.1:8072") {
  throw new Error("Stage 12 V2 production server requires the injected-stub origin");
}

const application = next({ dev: false, hostname, port, dir: process.cwd() });
const handle = application.getRequestHandler();
await application.prepare();
createServer((request, response) => handle(request, response)).listen(
  port,
  hostname,
  () => process.stdout.write(`Stage 12 V2 frontend ready on http://${hostname}:${port}\n`),
);
