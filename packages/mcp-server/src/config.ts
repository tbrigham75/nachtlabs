/**
 * Configuration and credential loading.
 *
 * Two credentials, deliberately kept apart:
 *
 *   * the NachtLabs API key, which is write-scoped and is held only here, on the
 *     machine that runs this server. It is read from a file on every request so
 *     that rotating it is a file swap rather than a redeploy, because rotation on
 *     the NachtLabs side is gated on a fresh human browser session and a deploy
 *     would be a much heavier thing to arrange in an incident.
 *   * this server's own token, which is what a client presents here.
 *
 * Both come from files, never from the environment. An environment variable is
 * visible in `docker inspect` and in the process list, and the API key is the
 * credential that matters: it can submit work.
 */

import { readFileSync } from "node:fs";

export interface Config {
  /** Base URL of the NachtLabs API, without a trailing slash. */
  baseUrl: string;
  /** File holding the NachtLabs API key. Re-read per request, for rotation. */
  apiKeyFile: string;
  /** File holding the bearer token a client must present to this server. */
  mcpTokenFile: string;
  /**
   * Projects this server will act on. Empty means "do not second-guess the key",
   * which is safe because the key is already bound to a set of projects and the
   * API refuses anything else with a 404. Set it to turn a mistake here into a
   * local error naming the config rather than a confusing 404.
   */
  projectIds: string[];
  bind: string;
  port: number;
  /** How often wait_for_run re-reads a run. */
  pollIntervalMs: number;
  /** Upper bound on a single wait_for_run call, so a client cannot hang forever. */
  maxWaitMs: number;
}

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
}

function integer(name: string, fallback: number): number {
  const raw = process.env[name]?.trim();
  if (!raw) return fallback;
  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer, not ${raw}`);
  }
  return parsed;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const previous = process.env;
  process.env = env as NodeJS.ProcessEnv;
  try {
    const baseUrl = required("NACHTLABS_URL").replace(/\/+$/, "");
    if (!/^https?:\/\//.test(baseUrl)) {
      throw new Error(`NACHTLABS_URL must be an http(s) URL, not ${baseUrl}`);
    }
    return {
      baseUrl,
      apiKeyFile: required("NACHTLABS_API_KEY_FILE"),
      mcpTokenFile: required("NACHTLABS_MCP_TOKEN_FILE"),
      projectIds: (process.env.NACHTLABS_PROJECT_IDS ?? "")
        .split(",")
        .map((id) => id.trim())
        .filter(Boolean),
      bind: process.env.NACHTLABS_MCP_BIND?.trim() || "127.0.0.1",
      port: integer("NACHTLABS_MCP_PORT", 3036),
      pollIntervalMs: integer("NACHTLABS_POLL_INTERVAL_MS", 3000),
      maxWaitMs: integer("NACHTLABS_MAX_WAIT_MS", 900_000),
    };
  } finally {
    process.env = previous;
  }
}

/**
 * Read a token from a file, refusing anything that looks wrong rather than
 * sending it upstream. A truncated file during a rotation would otherwise be sent
 * as a credential and produce a 401 that reads as "the key was revoked".
 */
export function readToken(path: string): string {
  let raw: string;
  try {
    raw = readFileSync(path, "utf8");
  } catch (cause) {
    throw new Error(
      `could not read the credential file ${path}: ${(cause as Error).message}`,
    );
  }
  const token = raw.trim();
  if (!token) {
    throw new Error(`the credential file ${path} is empty`);
  }
  if (/\s/.test(token)) {
    throw new Error(
      `the credential file ${path} contains whitespace; it is not a bare token`,
    );
  }
  return token;
}

/** Constant-time compare, so a wrong token cannot be found by timing the answer. */
export function tokensMatch(presented: string, expected: string): boolean {
  if (presented.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < presented.length; i += 1) {
    diff |= presented.charCodeAt(i) ^ expected.charCodeAt(i);
  }
  return diff === 0;
}
