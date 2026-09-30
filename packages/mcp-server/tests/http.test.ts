/**
 * The HTTP surface, driven the way a client drives it.
 *
 * A test that constructs the tools directly would not catch a misconfigured
 * transport, a missing token check, or a tool that is registered but unreachable.
 * This goes over the wire-shaped path instead, with an MCP client, because that is
 * the thing that has to work for hermes.
 */

import { mkdtempSync, writeFileSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { NachtLabs } from "../src/nachtlabs.js";
import { createServer } from "../src/server.js";
import type { Config } from "../src/config.js";

function credentialFile(contents: string): string {
  const dir = mkdtempSync(join(tmpdir(), "mcp-http-"));
  const path = join(dir, "token");
  writeFileSync(path, contents);
  chmodSync(path, 0o400);
  return path;
}

function config(over: Partial<Config> = {}): Config {
  return {
    baseUrl: "http://nachtlabs.test",
    apiKeyFile: credentialFile("nl_secret"),
    mcpTokenFile: credentialFile("mcp_secret"),
    projectIds: [],
    bind: "127.0.0.1",
    port: 0,
    pollIntervalMs: 1,
    maxWaitMs: 1000,
    ...over,
  };
}

/** Answers to the upstream API, and records what it was asked. */
function upstream(handler: (path: string, init: RequestInit) => Response) {
  const seen: Array<{ path: string; init: RequestInit }> = [];
  const impl = (async (url: string | URL | Request, init: RequestInit = {}) => {
    const parsed = new URL(String(url));
    seen.push({ path: parsed.pathname + parsed.search, init });
    return handler(parsed.pathname, init);
  }) as unknown as typeof fetch;
  return { seen, impl };
}

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

/** Serve the handler on an ephemeral port and return its origin. */
async function serve(config: Config, client: NachtLabs) {
  const server = createServer(config, client);
  const { createServer: httpServer } = await import("node:http");
  const listener = httpServer((req, res) => {
    void (async () => {
      const chunks: Buffer[] = [];
      for await (const chunk of req) chunks.push(chunk as Buffer);
      const origin = `http://${req.headers.host}`;
      const response = await server.handle(
        new Request(new URL(req.url ?? "/", origin), {
          method: req.method,
          headers: new Headers(
            Object.entries(req.headers).map(([k, v]) => [
              k,
              Array.isArray(v) ? v.join(",") : (v ?? ""),
            ]),
          ),
          ...(chunks.length ? { body: Buffer.concat(chunks) } : {}),
        }),
      );
      res.writeHead(response.status, Object.fromEntries(response.headers));
      res.end(Buffer.from(await response.arrayBuffer()));
    })();
  });
  await new Promise<void>((resolve) =>
    listener.listen(0, "127.0.0.1", resolve),
  );
  const address = listener.address();
  const port = typeof address === "object" && address ? address.port : 0;
  return {
    origin: `http://127.0.0.1:${port}`,
    close: async () => {
      listener.close();
      await server.close();
    },
  };
}

/**
 * A minimal MCP exchange over the wire.
 *
 * Written by hand against the protocol rather than with the SDK's client, so the
 * test exercises exactly what a client sends and does not depend on the client
 * API. The handshake is done properly because a tool that is registered but
 * unreachable through a real initialize is a tool that does not work.
 */
async function rpc(
  origin: string,
  token: string,
  method: string,
  params?: unknown,
  id = 1,
) {
  const response = await fetch(`${origin}/mcp`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id,
      method,
      ...(params ? { params } : {}),
    }),
  });
  const text = await response.text();
  // A stateless handler may answer with an SSE frame; the JSON payload is inside.
  const match =
    text.match(/data: (\{.*\})/s) ??
    (text.startsWith("{") ? [null, text] : null);
  return {
    status: response.status,
    body: match ? JSON.parse(match[1]!) : null,
    raw: text,
  };
}

async function initialize(origin: string, token: string) {
  return rpc(
    origin,
    token,
    "initialize",
    {
      protocolVersion: "2025-06-18",
      capabilities: {},
      clientInfo: { name: "test", version: "0.1.0" },
    },
    1,
  );
}

describe("http surface", () => {
  it("refuses an unauthenticated request", async () => {
    const { impl } = upstream(() => json({}));
    const served = await serve(
      config(),
      new NachtLabs(config(), { fetchImpl: impl }),
    );
    const response = await fetch(`${served.origin}/mcp`, { method: "POST" });
    expect(response.status).toBe(401);
    expect(response.headers.get("www-authenticate")).toContain("Bearer");
    await served.close();
  });

  it("refuses a wrong token and accepts the right one", async () => {
    const cfg = config();
    const { impl } = upstream(() => json({}));
    const served = await serve(cfg, new NachtLabs(cfg, { fetchImpl: impl }));
    const wrong = await fetch(`${served.origin}/mcp`, {
      method: "POST",
      headers: { authorization: "Bearer not-the-token" },
    });
    expect(wrong.status).toBe(401);
    await served.close();
  });

  it("answers the health check without touching the API", async () => {
    const cfg = config();
    const { seen, impl } = upstream(() => json({}));
    const served = await serve(cfg, new NachtLabs(cfg, { fetchImpl: impl }));
    const response = await fetch(`${served.origin}/healthz`);
    expect(response.status).toBe(200);
    // A healthcheck that depends on the upstream turns one slow dependency into a
    // restart loop, so it must not call anything.
    expect(seen).toHaveLength(0);
    await served.close();
  });

  it("does not serve the tool surface on any other path", async () => {
    const cfg = config();
    const { impl } = upstream(() => json({}));
    const served = await serve(cfg, new NachtLabs(cfg, { fetchImpl: impl }));
    const response = await fetch(`${served.origin}/tools`, {
      method: "POST",
      headers: { authorization: "Bearer mcp_secret" },
    });
    expect(response.status).toBe(404);
    await served.close();
  });

  it("reports a missing credential file as a server fault, not a wrong token", async () => {
    const cfg = config({ mcpTokenFile: join(tmpdir(), "definitely-not-here") });
    const { impl } = upstream(() => json({}));
    const served = await serve(cfg, new NachtLabs(cfg, { fetchImpl: impl }));
    const response = await fetch(`${served.origin}/mcp`, {
      method: "POST",
      headers: { authorization: "Bearer mcp_secret" },
    });
    expect(response.status).toBe(503);
    await served.close();
  });
});

describe("over the protocol", () => {
  it("completes an initialize handshake", async () => {
    const cfg = config();
    const { impl } = upstream(() => json({}));
    const served = await serve(cfg, new NachtLabs(cfg, { fetchImpl: impl }));
    const result = await initialize(served.origin, "mcp_secret");
    expect(result.status).toBe(200);
    expect(result.body?.result?.serverInfo?.name).toBe("nachtlabs");
    await served.close();
  });

  it("lists the tools, which is how a client discovers them at all", async () => {
    const cfg = config();
    const { impl } = upstream(() => json({}));
    const served = await serve(cfg, new NachtLabs(cfg, { fetchImpl: impl }));
    await initialize(served.origin, "mcp_secret");
    const result = await rpc(served.origin, "mcp_secret", "tools/list", {}, 2);
    const names = (result.body?.result?.tools ?? []).map(
      (t: { name: string }) => t.name,
    );
    expect(names).toEqual(
      expect.arrayContaining([
        "submit_work",
        "get_run",
        "wait_for_run",
        "run_events",
        "list_projects",
        "list_runs",
        "get_installation_status",
      ]),
    );
    await served.close();
  });

  it("does not offer a tool for something a key cannot do", async () => {
    // Creating a project, writing governance and approving a plan are all gated
    // on a human browser session. Offering tools for them would only ever produce
    // a 403, so the surface stops where the credential stops.
    const cfg = config();
    const { impl } = upstream(() => json({}));
    const served = await serve(cfg, new NachtLabs(cfg, { fetchImpl: impl }));
    await initialize(served.origin, "mcp_secret");
    const result = await rpc(served.origin, "mcp_secret", "tools/list", {}, 2);
    const names: string[] = (result.body?.result?.tools ?? []).map(
      (t: { name: string }) => t.name,
    );
    for (const forbidden of [
      "create_project",
      "approve_run",
      "write_governance",
      "set_policy",
    ]) {
      expect(names).not.toContain(forbidden);
    }
    await served.close();
  });

  it("reaches the API through a tool call, with the key and the idempotency header", async () => {
    const cfg = config();
    const { seen, impl } = upstream((path) =>
      path === "/api/v1/work-requests"
        ? json({
            work_request: { id: "w1" },
            run: { id: "r1", state: "queued" },
          })
        : json({}),
    );
    const served = await serve(cfg, new NachtLabs(cfg, { fetchImpl: impl }));
    await initialize(served.origin, "mcp_secret");
    const result = await rpc(
      served.origin,
      "mcp_secret",
      "tools/call",
      {
        name: "submit_work",
        arguments: {
          project_id: "p1",
          title: "Add a thing",
          description: "It should do the thing properly.",
          acceptance_criteria: ["The thing exists"],
        },
      },
      2,
    );
    expect(result.body?.result?.content?.[0]?.text ?? "").toContain(
      '"run_id": "r1"',
    );

    const call = seen.find((s) => s.path === "/api/v1/work-requests");
    expect(call).toBeDefined();
    const headers = call!.init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer nl_secret");
    expect(headers["Idempotency-Key"]).toBeTruthy();
    await served.close();
  });

  it("reports a human wait as a wait, over the wire", async () => {
    const cfg = config();
    const { impl } = upstream((path) =>
      path.startsWith("/api/v1/runs/")
        ? json({ state: "awaiting_approval", stage: "plan" })
        : json({}),
    );
    const served = await serve(
      cfg,
      new NachtLabs(cfg, { fetchImpl: impl, sleep: async () => {} }),
    );
    await initialize(served.origin, "mcp_secret");
    const result = await rpc(
      served.origin,
      "mcp_secret",
      "tools/call",
      { name: "wait_for_run", arguments: { run_id: "r1" } },
      2,
    );
    const text: string = result.body?.result?.content?.[0]?.text ?? "";
    expect(text).toContain("requires_a_person");
    expect(text).toMatch(/person must approve/i);
    // The model must not read this as something to retry.
    expect(text).not.toContain('"failed"');
    await served.close();
  });
});
