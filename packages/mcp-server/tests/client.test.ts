/**
 * The client behaviours that are correctness rather than features.
 *
 * Each test here corresponds to a way an agent could otherwise do real damage:
 * creating a second run for the same request, treating a rate limit as a failure,
 * or reading a state that needs a person as something to retry.
 */

import { mkdtempSync, writeFileSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  loadConfig,
  readToken,
  tokensMatch,
  type Config,
} from "../src/config.js";
import { backoff, NachtLabs } from "../src/nachtlabs.js";
import { classify, isSettled, waitingExplanation } from "../src/state.js";

function credentialFile(contents: string, mode = 0o400): string {
  const dir = mkdtempSync(join(tmpdir(), "mcp-"));
  const path = join(dir, "token");
  writeFileSync(path, contents);
  chmodSync(path, mode);
  return path;
}

function config(over: Partial<Config> = {}): Config {
  return {
    baseUrl: "http://nachtlabs.test",
    apiKeyFile: credentialFile("nl_secret"),
    mcpTokenFile: credentialFile("mcp_secret"),
    projectIds: [],
    bind: "127.0.0.1",
    port: 3036,
    pollIntervalMs: 1,
    maxWaitMs: 5000,
    ...over,
  };
}

interface Call {
  url: string;
  init: RequestInit;
}

function stubFetch(responses: Array<Response | Error>): {
  calls: Call[];
  impl: typeof fetch;
} {
  const calls: Call[] = [];
  let index = 0;
  const impl = (async (url: string | URL | Request, init: RequestInit = {}) => {
    calls.push({ url: String(url), init });
    // The last response repeats, so a test can say "and this keeps failing"
    // without listing the same failure the exact number of times it retries.
    const next =
      responses[Math.min(index, responses.length - 1)] ?? responses.at(-1);
    index += 1;
    if (!next) throw new Error("stubFetch was given no responses");
    if (next instanceof Error) throw next;
    return next.clone();
  }) as unknown as typeof fetch;
  return { calls, impl };
}

/** Header of the nth recorded call, asserted rather than assumed. */
function sent(calls: Call[], index: number, name: string): string | undefined {
  const call = calls[index];
  if (!call) throw new Error(`no call at index ${index}`);
  return (call.init.headers as Record<string, string>)[name];
}

const ok = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

const errBody = (code: string, fields?: string[]) => ({
  error: { code, ...(fields ? { fields } : {}) },
});

const work = {
  project_id: "p1",
  title: "Add a thing",
  description: "It should do the thing properly.",
  acceptance_criteria: ["The thing exists"],
};

describe("idempotency", () => {
  it("derives the same key for the same request and a different one otherwise", async () => {
    const { calls, impl } = stubFetch([ok({ run: { id: "r1" } })]);
    const client = new NachtLabs(config(), { fetchImpl: impl });
    await client.submitWork(work);
    await client.submitWork(work);
    await client.submitWork({ ...work, title: "Something else entirely" });

    const [c0, c1, c2] = calls;
    const first = c0!.init.headers as Record<string, string>;
    const second = c1!.init.headers as Record<string, string>;
    const third = c2!.init.headers as Record<string, string>;
    expect(first["Idempotency-Key"]).toBe(second["Idempotency-Key"]);
    expect(third["Idempotency-Key"]).not.toBe(first["Idempotency-Key"]);
    // The API rejects anything outside 8-200 characters.
    const key = first["Idempotency-Key"] ?? "";
    expect(key.length).toBeGreaterThanOrEqual(8);
    expect(key.length).toBeLessThanOrEqual(200);
  });

  it("sends the key only on submit, not on reads", async () => {
    const { calls, impl } = stubFetch([ok({})]);
    const client = new NachtLabs(config(), { fetchImpl: impl });
    await client.submitWork(work);
    await client.getRun("r1");
    expect(sent(calls, 0, "Idempotency-Key")).toBeTruthy();
    expect(sent(calls, 1, "Idempotency-Key")).toBeUndefined();
  });

  it("retries a lost response without creating a second run", async () => {
    // The request reached the API and the reply was lost. Retrying with the same
    // key is what makes this safe; a random key would submit the work twice.
    const { calls, impl } = stubFetch([
      new Error("socket hang up"),
      ok({ work_request: { id: "w1" }, run: { id: "r1" } }),
    ]);
    const client = new NachtLabs(config(), {
      fetchImpl: impl,
      sleep: async () => {},
    });
    const result = await client.submitWork(work);
    expect((result as { run: { id: string } }).run.id).toBe("r1");
    expect(calls).toHaveLength(2);
    expect(sent(calls, 0, "Idempotency-Key")).toBe(
      sent(calls, 1, "Idempotency-Key"),
    );
  });
});

describe("rate limiting", () => {
  it("retries a 429 rather than reporting it as a failure", async () => {
    const limited = new Response(JSON.stringify(errBody("rate_limited")), {
      status: 429,
      headers: { "content-type": "application/json", "retry-after": "0" },
    });
    const { calls, impl } = stubFetch([limited, ok({ run: { id: "r1" } })]);
    const client = new NachtLabs(config(), {
      fetchImpl: impl,
      sleep: async () => {},
    });
    const result = await client.submitWork(work);
    expect((result as { run: { id: string } }).run.id).toBe("r1");
    expect(calls).toHaveLength(2);
  });

  it("gives up after repeated throttling and says why", async () => {
    const limited = () =>
      new Response(JSON.stringify(errBody("rate_limited")), {
        status: 429,
        headers: { "content-type": "application/json", "retry-after": "0" },
      });
    const { impl } = stubFetch([
      limited(),
      limited(),
      limited(),
      limited(),
      limited(),
    ]);
    const client = new NachtLabs(config(), {
      fetchImpl: impl,
      sleep: async () => {},
    });
    await expect(client.getRun("r1")).rejects.toMatchObject({
      code: "rate_limited",
    });
  });

  it("does not retry a 4xx, because the request itself is wrong", async () => {
    const { calls, impl } = stubFetch([
      new Response(JSON.stringify(errBody("validation", ["body.title"])), {
        status: 422,
        headers: { "content-type": "application/json" },
      }),
    ]);
    const client = new NachtLabs(config(), {
      fetchImpl: impl,
      sleep: async () => {},
    });
    await expect(client.submitWork(work)).rejects.toMatchObject({
      status: 422,
    });
    expect(calls).toHaveLength(1);
  });

  it("backs off without exceeding the ceiling", () => {
    expect(backoff(1)).toBe(500);
    expect(backoff(2)).toBe(1000);
    expect(backoff(20)).toBe(8000);
  });
});

describe("error translation", () => {
  it("turns a governance code into something a person can act on", async () => {
    const { impl } = stubFetch([
      new Response(JSON.stringify(errBody("mission_required")), {
        status: 409,
        headers: { "content-type": "application/json" },
      }),
    ]);
    const client = new NachtLabs(config(), {
      fetchImpl: impl,
      sleep: async () => {},
    });
    await expect(client.submitWork(work)).rejects.toThrow(/approved Mission/);
  });

  it("preserves the fields the API blamed", async () => {
    const { impl } = stubFetch([
      new Response(JSON.stringify(errBody("validation", ["body.title"])), {
        status: 422,
        headers: { "content-type": "application/json" },
      }),
    ]);
    const client = new NachtLabs(config(), {
      fetchImpl: impl,
      sleep: async () => {},
    });
    await expect(client.submitWork(work)).rejects.toMatchObject({
      fields: ["body.title"],
    });
  });

  it("still reports an unknown code rather than swallowing it", async () => {
    const { impl } = stubFetch([
      new Response(JSON.stringify(errBody("something_new")), {
        status: 418,
        headers: { "content-type": "application/json" },
      }),
    ]);
    const client = new NachtLabs(config(), {
      fetchImpl: impl,
      sleep: async () => {},
    });
    await expect(client.getRun("r1")).rejects.toMatchObject({
      code: "something_new",
    });
  });
});

describe("run states", () => {
  it("treats approval as a wait, not a failure", () => {
    expect(classify("awaiting_approval")).toBe("human_wait");
    expect(classify("awaiting_approval")).not.toBe("failed");
    expect(waitingExplanation({ state: "awaiting_approval" })).toMatch(
      /person must approve/i,
    );
    expect(waitingExplanation({ state: "awaiting_approval" })).toMatch(
      /do not resubmit/i,
    );
  });

  it("settles on states a person has to act on, and keeps waiting otherwise", () => {
    for (const state of [
      "completed",
      "cancelled",
      "rejected",
      "dry_run_complete",
    ]) {
      expect(isSettled({ state })).toBe(true);
    }
    for (const state of [
      "awaiting_approval",
      "awaiting_manual",
      "blocked",
      "human_review",
    ]) {
      expect(isSettled({ state })).toBe(true);
    }
    for (const state of ["queued", "planning", "implementing", "verifying"]) {
      expect(isSettled({ state })).toBe(false);
    }
  });

  it("warns against retrying an uncertain delivery", () => {
    expect(waitingExplanation({ state: "delivery_uncertain" })).toMatch(
      /duplicate/i,
    );
  });
});

describe("project scoping", () => {
  it("refuses a project this server is not configured for", () => {
    const client = new NachtLabs(config({ projectIds: ["p1"] }));
    expect(() => client.assertProjectAllowed("p2")).toThrow(
      /not configured for project p2/,
    );
    expect(() => client.assertProjectAllowed("p1")).not.toThrow();
  });

  it("defers to the key when no allowlist is configured", () => {
    const client = new NachtLabs(config());
    expect(() => client.assertProjectAllowed("anything")).not.toThrow();
  });
});

describe("credentials", () => {
  it("re-reads the key per request so rotation needs no restart", async () => {
    const keyFile = credentialFile("nl_first");
    const { calls, impl } = stubFetch([
      ok({ run: { id: "r1" } }),
      ok({ run: { id: "r2" } }),
    ]);
    const client = new NachtLabs(config({ apiKeyFile: keyFile }), {
      fetchImpl: impl,
    });

    await client.submitWork(work);
    // An operator rotating the key replaces the file, so make it writable again
    // the way a real swap would be done by something that owns it.
    chmodSync(keyFile, 0o600);
    writeFileSync(keyFile, "nl_second");
    await client.submitWork(work);

    expect(sent(calls, 0, "Authorization")).toBe("Bearer nl_first");
    expect(sent(calls, 1, "Authorization")).toBe("Bearer nl_second");
  });

  it("refuses a credential file that is empty or holds whitespace", () => {
    expect(() => readToken(credentialFile("   \n"))).toThrow(/empty/);
    expect(() => readToken(credentialFile("nl_a nl_b"))).toThrow(/whitespace/);
    expect(readToken(credentialFile("nl_ok\n"))).toBe("nl_ok");
  });

  it("compares tokens without short-circuiting on length alone", () => {
    expect(tokensMatch("abc", "abc")).toBe(true);
    expect(tokensMatch("abc", "abd")).toBe(false);
    expect(tokensMatch("abc", "abcd")).toBe(false);
  });

  it("requires the settings it cannot work without", () => {
    expect(() => loadConfig({})).toThrow(/NACHTLABS_URL/);
    expect(() =>
      loadConfig({ NACHTLABS_URL: "http://x", NACHTLABS_API_KEY_FILE: "/a" }),
    ).toThrow(/NACHTLABS_MCP_TOKEN_FILE/);
    expect(() => loadConfig({ NACHTLABS_URL: "ftp://x" })).toThrow(/http/);
  });

  it("binds to loopback unless told otherwise", () => {
    const c = loadConfig({
      NACHTLABS_URL: "http://nachtlabs.test",
      NACHTLABS_API_KEY_FILE: "/a",
      NACHTLABS_MCP_TOKEN_FILE: "/b",
    });
    expect(c.bind).toBe("127.0.0.1");
  });
});

describe("unreachable upstream", () => {
  it("names the host and the reason instead of 'fetch failed'", async () => {
    // Node reports every transport problem as "fetch failed", which tells an
    // operator nothing they can act on. The message has to say which host, and
    // whether the port was closed or the name failed, or it cannot be fixed from
    // the outside.
    const refused = new TypeError("fetch failed");
    Object.assign(refused, { cause: { code: "ECONNREFUSED" } });
    const { impl } = stubFetch([refused]);
    const client = new NachtLabs(config(), {
      fetchImpl: impl,
      sleep: async () => {},
    });
    await expect(client.listProjects()).rejects.toThrow(
      /connection was refused/,
    );
    await expect(client.listProjects()).rejects.toThrow(/nachtlabs\.test/);
  });

  it("reports an unresolvable name as such", async () => {
    const noDns = new TypeError("fetch failed");
    Object.assign(noDns, { cause: { code: "ENOTFOUND" } });
    const { impl } = stubFetch([noDns]);
    const client = new NachtLabs(config(), {
      fetchImpl: impl,
      sleep: async () => {},
    });
    await expect(client.listProjects()).rejects.toThrow(/did not resolve/);
  });

  it("retries a transport failure before giving up", async () => {
    const refused = new TypeError("fetch failed");
    Object.assign(refused, { cause: { code: "ECONNREFUSED" } });
    const { calls, impl } = stubFetch([refused, ok({ items: [] })]);
    const client = new NachtLabs(config(), {
      fetchImpl: impl,
      sleep: async () => {},
    });
    await client.listProjects();
    // A transport failure may be a request that reached the API and was lost, so
    // it is worth another attempt rather than being reported immediately.
    expect(calls).toHaveLength(2);
  });
});
