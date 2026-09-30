/**
 * Entry point.
 *
 * Node's http server is adapted to the Web-standard Request/Response the MCP
 * handler takes, so the package depends on nothing but the runtime and the SDK.
 * The conversion is here rather than in a framework because a stateless JSON-RPC
 * endpoint does not need one, and every dependency is one more thing to keep
 * patched on a machine that holds a write-scoped credential.
 */

import { createServer as createHttpServer } from "node:http";
import { loadConfig } from "./config.js";
import { NachtLabs } from "./nachtlabs.js";
import { createServer } from "./server.js";

async function readBody(
  req: import("node:http").IncomingMessage,
): Promise<Buffer> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks);
}

/**
 * Convert a Node request into the Web-standard Request the handler takes.
 *
 * The body is read to a Buffer first and handed over as that Buffer, rather than
 * streaming `req` through. An IncomingMessage is not a Web ReadableStream, and
 * passing it directly both violates the Web API and leaves the stream already
 * consumed, which fails at the far end as "Response body object should not be
 * disturbed or locked" rather than anything that points here.
 */
function toWebRequest(
  req: import("node:http").IncomingMessage,
  origin: string,
  body: Buffer,
): Request {
  const url = new URL(req.url ?? "/", origin);
  const headers = new Headers();
  for (const [key, value] of Object.entries(req.headers)) {
    if (value === undefined) continue;
    if (Array.isArray(value)) value.forEach((v) => headers.append(key, v));
    else headers.set(key, value);
  }
  const method = req.method ?? "GET";
  const hasBody = method !== "GET" && method !== "HEAD" && body.length > 0;
  // Content-Length describes the stream that has already been consumed, so it is
  // corrected rather than passed on.
  headers.delete("content-length");
  return new Request(url, {
    method,
    headers,
    ...(hasBody ? { body } : {}),
  });
}

async function main(): Promise<void> {
  const config = loadConfig();
  const client = new NachtLabs(config);
  const server = createServer(config, client);

  const http = createHttpServer((req, res) => {
    void (async () => {
      try {
        const origin = `http://${req.headers.host ?? "localhost"}`;
        const body = await readBody(req);
        const response = await server.handle(toWebRequest(req, origin, body));
        res.writeHead(response.status, Object.fromEntries(response.headers));
        res.end(Buffer.from(await response.arrayBuffer()));
      } catch (cause) {
        res.writeHead(500, { "content-type": "application/json" });
        res.end(
          JSON.stringify({
            error: { code: "internal", message: (cause as Error).message },
          }),
        );
      }
    })();
  });

  http.listen(config.port, config.bind, () => {
    // Never print a token, and never print one with the address.
    console.log(
      `nachtlabs-mcp listening on http://${config.bind}:${config.port}/mcp`,
    );
    console.log(`upstream ${config.baseUrl}`);
  });

  for (const signal of ["SIGINT", "SIGTERM"] as const) {
    process.on(signal, () => {
      http.close(() => void server.close().then(() => process.exit(0)));
    });
  }
}

main().catch((cause: Error) => {
  console.error(`nachtlabs-mcp: ${cause.message}`);
  process.exit(1);
});
