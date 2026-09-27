/** Authored transport/types. generated.d.ts is created from OpenAPI at Linux handoff. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId?: string,
  ) {
    super(message);
  }
}
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const csrf =
    typeof document === "undefined"
      ? ""
      : (document.cookie
          .split("; ")
          .find((v) => v.startsWith("nachtlabs_csrf="))
          ?.split("=")[1] ?? "");
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": decodeURIComponent(csrf),
      ...init.headers,
    },
  });
  const data = await response.json().catch(() => {
    throw new ApiError(
      response.status,
      "invalid_response",
      "The server returned an unreadable response. Retry or contact your administrator.",
    );
  });
  if (!response.ok)
    throw new ApiError(
      response.status,
      data.error?.code ?? "http_error",
      data.error?.message ?? "Request failed",
      data.error?.request_id,
    );
  return data as T;
}
export const write = <T>(path: string, body: unknown = {}, method = "POST") =>
  api<T>(path, { method, body: JSON.stringify(body) });
export type Role = "owner" | "admin" | "operator" | "contributor" | "viewer";
export type Theme =
  | "midnight"
  | "graphite"
  | "canvas"
  | "forest"
  | "nordic"
  | "solarized"
  | "system";
/** GET /auth/preflight. Reports whether a mutating request from this origin would
 * be accepted, without creating an account to find out. `setup_token_required`
 * is the only way the interface can know to ask for the one-time token. */
export interface SetupPreflight {
  origin: string | null;
  expected: string;
  origin_accepted: boolean;
  setup_token_required: boolean;
  initialized: boolean;
  hint: string | null;
}
/** GET /llm-readiness. Derived setup state for the model/agent chain.
 *
 * The four states the architecture keeps apart stay apart: a saved connection
 * is not a working one, a successful discovery is not a compatibility proof, and
 * `execution_available` reflects a root-owned qualification the API cannot see,
 * so it is always false here. */
export interface LlmReadiness {
  provider_network_enabled: boolean;
  connection: {
    id: string;
    name: string;
    active: boolean;
    version: number;
    loopback_pinned: boolean;
  } | null;
  connection_count: number;
  discovery: {
    state:
      | "not_run"
      | "pending"
      | "running"
      | "succeeded"
      | "failed"
      | "stale"
      | "expired";
    models: { name: string; digest: string | null }[];
    checked_at: string | null;
  };
  implementation_profile: { id: string; model: string } | null;
  verifier_profile: { id: string; model: string } | null;
  planning_profile: { id: string; model: string } | null;
  agent: {
    id: string;
    name: string;
    provider: string;
    executable: string;
  } | null;
  distinct_models: boolean;
  execution_available: boolean;
  complete: boolean;
}
export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
  active: boolean;
  theme: Theme;
  mfa_enabled: boolean;
  version: number;
  organization?: string;
  mfa_required?: boolean;
}
export interface Project {
  id: string;
  name: string;
  slug: string;
  description: string;
  archived: boolean;
  version: number;
  delivery_mode: string;
  execution_enabled: boolean;
  readiness?: Record<string, boolean>;
}
export interface Governance {
  id: string;
  name: string;
  kind: "mission" | "journey" | "holdout";
  version: number;
  latest_version: number;
  approved_version: number | null;
  content: Record<string, unknown>;
  author_id: string;
  created_at: string;
  approved_at: string | null;
}
export interface Key {
  id: string;
  name: string;
  prefix: string;
  service_account_id: string;
  scopes: string[];
  project_ids: string[];
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  raw_key?: string;
}
export interface Audit {
  id: string;
  created_at: string;
  actor: string;
  action: string;
  target: string;
  outcome: string;
  request_id: string;
  project_id: string | null;
  details: Record<string, unknown>;
}
