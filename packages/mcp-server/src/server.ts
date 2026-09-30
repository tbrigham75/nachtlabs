/**
 * The HTTP surface.
 *
 * Stateless on purpose: createMcpHandler builds a fresh server per request, so
 * there is no session store, nothing to keep sticky, and a restart loses nothing.
 * A single client's polling therefore cannot leave anything behind on the server
 * between calls.
 *
 * The token check is on this server, not delegated. This server holds a
 * write-scoped NachtLabs key, so being able to call it is equivalent to being
 * able to submit work. It is a separate credential from the NachtLabs one so that
 * revoking this surface and rotating the API key are independent acts.
 */

import {
  createMcpHandler,
  McpServer,
  verifyBearerToken,
} from "@modelcontextprotocol/server";
import type { Config } from "./config.js";
import { readToken, tokensMatch } from "./config.js";
import type { NachtLabs } from "./nachtlabs.js";
import { registerTools } from "./tools.js";

const NO_STORE = {
  "cache-control": "no-store",
} as const;

export interface Server {
  /** Serve one request. Web-standard in, web-standard out. */
  handle: (request: Request) => Promise<Response>;
  close: () => Promise<void>;
}

export function createServer(config: Config, client: NachtLabs): Server {
  const handler = createMcpHandler(
    () => {
      const server = new McpServer({ name: "nachtlabs", version: "0.1.0" });
      registerTools(server, client);
      return server;
    },
    // No protocol-level sessions: each request is self-contained.
    { legacy: "stateless" },
  );

  return {
    async handle(request: Request): Promise<Response> {
      const url = new URL(request.url);

      if (url.pathname === "/healthz") {
        // Deliberately does not touch the API. A healthcheck that reports on a
        // dependency turns one slow dependency into a restart loop.
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json", ...NO_STORE },
        });
      }

      if (url.pathname !== "/mcp") {
        return new Response("Not found", { status: 404, headers: NO_STORE });
      }

      if (request.method === "OPTIONS") {
        return new Response(null, { status: 204, headers: NO_STORE });
      }

      const header = request.headers.get("authorization") ?? "";
      if (!header.startsWith("Bearer ")) {
        return new Response("Bearer credential required", {
          status: 401,
          headers: {
            "www-authenticate": 'Bearer realm="nachtlabs-mcp"',
            ...NO_STORE,
          },
        });
      }

      // Compare against the on-disk token, so rotating this server's credential
      // is a file swap as well.
      let expected: string;
      let presented: string;
      try {
        expected = readToken(config.mcpTokenFile);
        presented = header.slice("Bearer ".length).trim();
      } catch {
        // A missing or malformed credential file is a server-side problem, not a
        // wrong token, and saying so is the difference between a two-minute fix
        // and an afternoon.
        return new Response("Server credential is not readable", {
          status: 503,
          headers: NO_STORE,
        });
      }

      if (!tokensMatch(presented, expected)) {
        return new Response("Invalid token", {
          status: 401,
          headers: {
            "www-authenticate": 'Bearer error="invalid_token"',
            ...NO_STORE,
          },
        });
      }

      try {
        const response = await handler.fetch(request, {
          authInfo: { token: presented, clientId: "mcp-client", scopes: [] },
        });
        for (const [key, value] of Object.entries(NO_STORE))
          response.headers.set(key, value);
        return response;
      } catch (cause) {
        return new Response(
          JSON.stringify({
            error: { code: "internal", message: (cause as Error).message },
          }),
          {
            status: 500,
            headers: { "content-type": "application/json", ...NO_STORE },
          },
        );
      }
    },
    close: () => handler.close(),
  };
}

export { verifyBearerToken };
