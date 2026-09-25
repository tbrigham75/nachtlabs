/** Authored transport/types. generated.d.ts is created from OpenAPI at Linux handoff. */
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public requestId?: string) { super(message); }
}
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const csrf = typeof document === "undefined" ? "" : document.cookie.split("; ").find(v => v.startsWith("nachtlabs_csrf="))?.split("=")[1] ?? "";
  const response = await fetch(`/api/v1${path}`, {
    ...init, credentials: "same-origin", cache: "no-store",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": decodeURIComponent(csrf), ...init.headers },
  });
  const data = await response.json().catch(() => { throw new ApiError(response.status, "invalid_response", "The server returned an unreadable response. Retry or contact your administrator."); });
  if (!response.ok) throw new ApiError(response.status, data.error?.code ?? "http_error", data.error?.message ?? "Request failed", data.error?.request_id);
  return data as T;
}
export const write = <T>(path: string, body: unknown = {}, method = "POST") => api<T>(path, {method, body: JSON.stringify(body)});
export type Role = "owner" | "admin" | "operator" | "contributor" | "viewer";
export type Theme = "midnight" | "graphite" | "canvas" | "forest" | "nordic" | "solarized" | "system";
export interface User { id: string; email: string; name: string; role: Role; active: boolean; theme: Theme; mfa_enabled: boolean; version: number; organization?: string; mfa_required?: boolean; }
export interface Project { id: string; name: string; slug: string; description: string; archived: boolean; version: number; delivery_mode: string; execution_enabled: boolean; readiness?: Record<string, boolean>; }
export interface Governance { id: string; name: string; kind: "mission" | "journey" | "holdout"; version: number; latest_version: number; approved_version: number | null; content: Record<string, unknown>; author_id: string; created_at: string; approved_at: string | null; }
export interface Key { id: string; name: string; prefix: string; service_account_id: string; scopes: string[]; project_ids: string[]; expires_at: string | null; revoked_at: string | null; last_used_at: string | null; raw_key?: string; }
export interface Audit { id: string; created_at: string; actor: string; action: string; target: string; outcome: string; request_id: string; project_id: string | null; details: Record<string, unknown>; }
