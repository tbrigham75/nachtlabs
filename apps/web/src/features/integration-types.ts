export interface Probe {
  id: string; connection_id: string; connection_version: number; page: number;
  state: "pending" | "running" | "succeeded" | "failed" | "stale";
  created_at: string; finished_at: string | null; error_code: string | null; duration_ms: number | null;
  result: {identity?: string; provider_version?: string; next_page?: number | null;
    repositories?: {provider_id: string; full_name: string; default_branch: string; private: boolean}[];
    models?: {name: string; digest: string | null}[]};
}
export interface Connection {
  id: string; name: string; provider: "github" | "gitea" | "ollama"; base_url: string;
  pinned_addresses: string[]; allow_private: boolean; allow_http: boolean; timeout_seconds: number;
  active: boolean; version: number; credential_present: boolean; credential_version: number;
  network_allowed: boolean; latest_probe: Probe | null; compatibility: string;
}
export interface ModelProfile {
  id: string; name: string; connection_id: string; model: string; role: string;
  temperature: number; active: boolean; version: number;
}
export interface AgentConfig {
  id: string; name: string; provider: "hermes" | "opencode"; executable: string;
  expected_agent_version: string; model_profile_id: string; timeout_seconds: number;
  active: boolean; version: number; tested_version: string | null;
  capabilities: {structured_events: boolean; limitations: string[]};
}
export interface Binding {
  version: number; connection_id: string; probe_id: string; repository_id: string;
  full_name: string; default_branch: string; implementation_agent_id: string | null;
  verifier_agent_id: string | null; require_distinct_models: boolean;
}
