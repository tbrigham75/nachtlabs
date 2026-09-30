/**
 * The NachtLabs API client.
 *
 * Three behaviours here are deliberate and each one exists because getting it
 * wrong is worse than not offering the tool at all:
 *
 *   * Idempotency-Key is derived from a hash of the request body, not from a
 *     timestamp or a random value. The API requires the header and deduplicates
 *     on it, so a client that retries after a timeout must produce the same key
 *     or it silently creates a second run for the same request.
 *   * 429 is retried with backoff rather than surfaced. A polling agent that
 *     treats a rate limit as a failure will either give up or hammer harder.
 *   * Domain errors are translated. The API answers with codes like
 *     mission_required and stale_governance that each mean something specific and
 *     actionable; a bare "HTTP 409" tells a model nothing and invites it to
 *     retry the same impossible thing.
 */

import { createHash } from "node:crypto";
import type { Config } from "./config.js";
import { readToken } from "./config.js";

/** Codes the API returns that a client can act on. Anything else is unexpected. */
const KNOWN_ERRORS = new Set([
  "unauthenticated",
  "forbidden",
  "not_found",
  "scope_required",
  "operator_required",
  "human_required",
  "reauth_required",
  "owner_required",
  "stale_version",
  "stale_governance",
  "idempotency_conflict",
  "idempotency_required",
  "mission_required",
  "baseline_required",
  "baseline_disabled",
  "holdout_required",
  "holdout_unapproved",
  "project_archived",
  "emergency_stop",
  "invalid_credentials",
  "rate_limited",
  "body_too_large",
  "validation",
]);

export interface ApiError extends Error {
  status: number;
  code: string;
  /** Fields the API blamed, when it named them. */
  fields?: string[];
  retryable: boolean;
}

function apiError(status: number, code: string, fields?: string[]): ApiError {
  const messages: Record<string, string> = {
    mission_required:
      "The project has no approved Mission yet. A human has to approve one in the interface.",
    baseline_required:
      "The Mission names no baseline Journeys, or they are not approved. A human has to fix this.",
    baseline_disabled:
      "A baseline Journey is disabled. A human has to enable it.",
    holdout_required:
      "Holdouts were requested but none exist. A human has to approve one.",
    holdout_unapproved:
      "A holdout is required and is not approved. A human has to approve one.",
    project_archived: "The project is archived, so it will not accept work.",
    stale_governance:
      "The project's governance or execution policy changed since this was prepared. Read the current state before retrying.",
    idempotency_conflict:
      "This idempotency key was already used with a different request body. Use a different key only if this really is different work.",
    scope_required: "The API key is missing the scope this call needs.",
    rate_limited:
      "The API key is over its allowance. Wait for the window to pass.",
    emergency_stop: "Factory control has stopped work on this installation.",
  };
  const error = new Error(
    messages[code] ?? `The API refused this request: ${code}`,
  ) as ApiError;
  error.status = status;
  error.code = code;
  if (fields) error.fields = fields;
  // A 5xx or a rate limit is worth another attempt; a 4xx means the request
  // itself is wrong and retrying it produces the same answer.
  error.retryable = status === 429 || status >= 500;
  return error;
}

export interface SubmitWork {
  project_id: string;
  title: string;
  description: string;
  acceptance_criteria: string[];
  priority?: "low" | "normal" | "high" | "urgent";
  target_ref?: string;
  labels?: string[];
  links?: string[];
  dry_run?: boolean;
}

export interface ClientOptions {
  /** Overridable so tests can inject a fetch without a network. */
  fetchImpl?: typeof fetch;
  sleep?: (ms: number) => Promise<void>;
}

const defaultSleep = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms));

export class NachtLabs {
  private readonly config: Config;
  private readonly doFetch: typeof fetch;
  private readonly sleep: (ms: number) => Promise<void>;

  constructor(config: Config, options: ClientOptions = {}) {
    this.config = config;
    this.doFetch = options.fetchImpl ?? fetch;
    this.sleep = options.sleep ?? defaultSleep;
  }

  /**
   * The API key is read per call so rotation does not need a restart. The file is
   * the only place it exists, which is the whole reason this server is the sole
   * client of the API rather than every agent holding its own key.
   */
  private authorization(): string {
    return `Bearer ${readToken(this.config.apiKeyFile)}`;
  }

  private idempotencyKey(body: unknown): string {
    // The API accepts 8-200 characters. A content hash is stable across retries
    // and distinct across different requests, which is exactly the property the
    // deduplication needs.
    return `mcp-${createHash("sha256").update(JSON.stringify(body)).digest("hex").slice(0, 40)}`;
  }

  private async request<T>(
    method: "GET" | "POST",
    path: string,
    options: {
      body?: unknown;
      idempotent?: boolean;
      query?: Record<string, string>;
    } = {},
  ): Promise<T> {
    const url = new URL(`${this.config.baseUrl}${path}`);
    for (const [key, value] of Object.entries(options.query ?? {})) {
      url.searchParams.set(key, value);
    }
    const headers: Record<string, string> = {
      Authorization: this.authorization(),
    };
    if (options.body !== undefined)
      headers["Content-Type"] = "application/json";
    if (options.idempotent)
      headers["Idempotency-Key"] = this.idempotencyKey(options.body);

    let attempt = 0;
    for (;;) {
      attempt += 1;
      let response: Response;
      try {
        response = await this.doFetch(url, {
          method,
          headers,
          body:
            options.body === undefined
              ? undefined
              : JSON.stringify(options.body),
        });
      } catch (cause) {
        // A network failure is indistinguishable from a request that reached the
        // API and was lost, which is exactly the case the idempotency key covers,
        // so this is retried.
        if (attempt < 4) {
          await this.sleep(backoff(attempt));
          continue;
        }
        // Node's fetch reports every transport problem as "fetch failed", with
        // the real reason attached as a cause. A model handed that cannot act on
        // it: it does not say which host, or whether the port is closed, or that a
        // name did not resolve. Say all of it.
        const reason = describeCause(cause);
        const failure = new Error(
          `Could not reach the NachtLabs API at ${url.origin} after ${attempt} attempts: ${reason}. ` +
            `Check NACHTLABS_URL, and that this host can route to it.`,
        ) as ApiError;
        failure.status = 0;
        failure.code = "unreachable";
        failure.retryable = false;
        throw failure;
      }
      if (response.ok) return (await response.json()) as T;

      const payload = (await response.json().catch(() => ({}))) as {
        error?: { code?: string; fields?: string[] };
      };
      const code = payload.error?.code ?? "unknown";
      const error = apiError(response.status, code, payload.error?.fields);
      if (error.retryable && attempt < 4) {
        // Honour the server's own advice when it gives any, so several clients
        // sharing a key do not resynchronise into a thundering herd.
        const retryAfter = Number(response.headers.get("retry-after"));
        await this.sleep(
          Number.isFinite(retryAfter) && retryAfter > 0
            ? retryAfter * 1000
            : backoff(attempt),
        );
        continue;
      }
      throw error;
    }
  }

  submitWork(body: SubmitWork) {
    return this.request<{ work_request: unknown; run: unknown }>(
      "POST",
      "/api/v1/work-requests",
      {
        body,
        idempotent: true,
      },
    );
  }

  getRun(runId: string) {
    return this.request<{
      state: string;
      stage?: string;
      error_code?: string;
      [k: string]: unknown;
    }>("GET", `/api/v1/runs/${runId}`);
  }

  listRuns(projectId: string, limit = 25) {
    return this.request<unknown>("GET", "/api/v1/runs", {
      query: { project_id: projectId, limit: String(limit) },
    });
  }

  runEvents(runId: string, after = 0) {
    return this.request<{ items: unknown[]; latest: number }>(
      "GET",
      `/api/v1/runs/${runId}/events`,
      { query: { after: String(after) } },
    );
  }

  listProjects() {
    return this.request<unknown>("GET", "/api/v1/projects");
  }

  /*
    Not /llm-readiness. That endpoint is human_admin()-gated, so a service account
    receives 403 forbidden and the tool could never succeed -- which is exactly the
    mistake this server's tool list was assembled to avoid. It shipped anyway, and
    only the live suite against a real key caught it: a stubbed API happily
    answers anything. /overview reports the same thing an agent can act on (worker
    liveness, and whether execution is available) behind projects:read.
  */
  overview() {
    return this.request<unknown>("GET", "/api/v1/overview");
  }

  /** Refuse an out-of-scope project locally, so a mistake names the config. */
  assertProjectAllowed(projectId: string): void {
    if (
      this.config.projectIds.length &&
      !this.config.projectIds.includes(projectId)
    ) {
      throw new Error(
        `This server is not configured for project ${projectId}. Allowed: ${this.config.projectIds.join(", ")}`,
      );
    }
  }

  get pollIntervalMs(): number {
    return this.config.pollIntervalMs;
  }

  get maxWaitMs(): number {
    return this.config.maxWaitMs;
  }

  /** Exposed for the wait loop, which needs to share the client's backoff. */
  get backoff(): (attempt: number) => number {
    return backoff;
  }

  get wait(): (ms: number) => Promise<void> {
    return this.sleep;
  }
}

export function backoff(attempt: number): number {
  return Math.min(500 * 2 ** (attempt - 1), 8000);
}

export { KNOWN_ERRORS };

/**
 * Node reports every transport problem as `fetch failed` and hides the reason in
 * a `cause`. The reason is what tells an operator whether the host is wrong, the
 * port is closed, or a name did not resolve, so it is worth digging out.
 */
function describeCause(cause: unknown): string {
  const err = cause as { cause?: unknown; message?: string };
  const inner = err?.cause as { code?: string; message?: string } | undefined;
  if (inner?.code === "ECONNREFUSED")
    return "the connection was refused, so nothing is listening on that port";
  if (inner?.code === "ENOTFOUND" || inner?.code === "EAI_AGAIN")
    return "the host name did not resolve";
  if (inner?.code === "ETIMEDOUT" || inner?.code === "UND_ERR_CONNECT_TIMEOUT")
    return "the connection timed out";
  if (inner?.code === "ECONNRESET") return "the connection was reset";
  if (inner?.message) return inner.message;
  return err?.message ?? "an unknown transport error";
}
