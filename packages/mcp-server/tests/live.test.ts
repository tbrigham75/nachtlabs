/**
 * The deployed server, against a real installation.
 *
 * Every other test here uses a stubbed API, which proves the client's own logic
 * but not that a path, a header or a scope name matches what the API actually
 * expects. Those are the mistakes that survive to a deployment: `get_run` on a
 * route that is really `/runs/{id}/work`, or a scope the API never issued.
 *
 * This runs against a deployed MCP server and a real key, and is skipped rather
 * than failed when they are absent, so an ordinary `pnpm test` stays green:
 *
 *   NACHTLABS_MCP_LIVE_URL=http://<host>:3036 \
 *   NACHTLABS_MCP_LIVE_TOKEN_FILE=/etc/nachtlabs-mcp/mcp-token \
 *   NACHTLABS_MCP_LIVE_API_KEY=/etc/nachtlabs-mcp/api-key \
 *   NACHTLABS_MCP_LIVE_PROJECT_ID=<uuid> \
 *   make test-mcp-live
 *
 * The API key is only used to assert the credential's own scopes, never to submit
 * work. Submissions belong to a real project and are covered by the install's own
 * end-to-end suite.
 */

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const URL_BASE = process.env.NACHTLABS_MCP_LIVE_URL?.replace(/\/+$/, "");
const TOKEN_FILE = process.env.NACHTLABS_MCP_LIVE_TOKEN_FILE;
const KEY_FILE = process.env.NACHTLABS_MCP_LIVE_API_KEY;
const PROJECT_ID = process.env.NACHTLABS_MCP_LIVE_PROJECT_ID;

const configured = Boolean(URL_BASE && TOKEN_FILE);

if (!configured) {
  // Not a failure: nobody should have to deploy a server to run the unit suite.
  // eslint-disable-next-line no-console
  console.warn(
    "live MCP tests skipped. Set NACHTLABS_MCP_LIVE_URL and NACHTLABS_MCP_LIVE_TOKEN_FILE.",
  );
}

function base(): string {
  if (!URL_BASE) throw new Error("NACHTLABS_MCP_LIVE_URL is not set");
  return URL_BASE;
}

function token(): string {
  // Asserted rather than asserted-with-`!` at every use: the whole file is
  // skipped unless TOKEN_FILE is set, and a missing file at run time should read
  // as the configuration mistake it is.
  if (!TOKEN_FILE) throw new Error("NACHTLABS_MCP_LIVE_TOKEN_FILE is not set");
  return readFileSync(TOKEN_FILE, "utf8").trim();
}

async function rpc(method: string, params?: unknown, id = 1) {
  const response = await fetch(`${base()}/mcp`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${token()}`,
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
  if (response.status !== 200) {
    return { status: response.status, payload: null, text };
  }
  // A stateless handler answers with an SSE frame; the JSON is the data line.
  const frame = text.match(/^data: (\{.*)/ms)?.[1];
  return {
    status: response.status,
    payload: JSON.parse(frame ?? text),
    text,
  };
}

async function callTool(name: string, args: unknown, id = 2) {
  return rpc("tools/call", { name, arguments: args }, id);
}

describe.skipIf(!configured)("a deployed MCP server", () => {
  it("answers a health check", async () => {
    const response = await fetch(`${base()}/healthz`);
    expect(response.status).toBe(200);
  });

  it("refuses an unauthenticated caller", async () => {
    const response = await fetch(`${base()}/mcp`, { method: "POST" });
    expect(response.status).toBe(401);
  });

  it("advertises the tools", async () => {
    const { payload } = await rpc("tools/list", {});
    const names = (payload?.result?.tools ?? []).map(
      (t: { name: string }) => t.name,
    );
    expect(names).toContain("submit_work");
    expect(names).toContain("wait_for_run");
    expect(names).not.toContain("create_project");
    expect(names).not.toContain("approve_run");
  });

  it("completes a handshake at the protocol version it claims", async () => {
    const { payload } = await rpc("initialize", {
      protocolVersion: "2025-06-18",
      capabilities: {},
      clientInfo: { name: "live-test", version: "0.1.0" },
    });
    expect(payload?.result?.serverInfo?.name).toBe("nachtlabs");
    expect(payload?.result?.protocolVersion).toBeTruthy();
  });

  it("reaches the API with the configured key", async () => {
    const { payload } = await callTool("list_projects", {});
    // A rejected key is a different failure from an unreachable one, and only one
    // of them means this path works. Both are failures here, for different
    // reasons, and the message distinguishes them.
    expect(JSON.stringify(payload ?? {})).not.toContain("unreachable");
    if (JSON.stringify(payload ?? {}).includes("unauthenticated")) {
      throw new Error(
        "The deployed server reached the API but the key was refused. Check the key file " +
          "and that it has not been revoked or expired.",
      );
    }
    expect(payload?.result?.isError).not.toBe(true);
  });

  it.runIf(KEY_FILE && PROJECT_ID)(
    "sees the project the key is bound to",
    async () => {
      const { payload } = await callTool("list_runs", {
        project_id: PROJECT_ID,
        limit: 5,
      });
      if (JSON.stringify(payload ?? {}).includes("not_found")) {
        throw new Error(
          `The key is not bound to project ${PROJECT_ID}, or NACHTLABS_PROJECT_IDS is set to ` +
            `something else. Check the key's project_ids and the server's configuration.`,
        );
      }
      expect(payload?.result?.isError).not.toBe(true);
    },
  );

  it("reports provider readiness rather than pretending an endpoint works", async () => {
    const { payload } = await callTool("get_readiness", {}, 3);
    expect(JSON.stringify(payload ?? {})).not.toContain("unreachable");
    expect(payload?.result?.isError).not.toBe(true);
  });

  it("answers a bad project with a tool error, never a crash or an empty reply", async () => {
    // Whether this is refused locally (when NACHTLABS_PROJECT_IDS is set) or by
    // the key's own project binding, the requirement is the same: the caller gets
    // a readable error rather than an exception, a 500, or silence. Which of the
    // two applies depends on configuration, so neither is asserted here.
    const { payload, text } = await callTool(
      "list_runs",
      { project_id: "not-a-project-id" },
      4,
    );
    expect(text.length).toBeGreaterThan(0);
    const body = JSON.stringify(payload ?? {});
    if (body.includes("unauthenticated")) return; // the key is rejected first
    expect(body).toMatch(/not configured for project|not_found/);
  });
});
