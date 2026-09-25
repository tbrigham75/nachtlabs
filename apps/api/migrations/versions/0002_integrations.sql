CREATE TABLE integration_connections (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL, org_id uuid NOT NULL REFERENCES organizations(id),
 name varchar(120) NOT NULL, provider varchar(20) NOT NULL CHECK(provider IN ('github','gitea','ollama')),
 base_url varchar(512) NOT NULL, pinned_addresses jsonb NOT NULL, allow_private boolean NOT NULL,
 allow_http boolean NOT NULL, timeout_seconds integer NOT NULL CHECK(timeout_seconds BETWEEN 1 AND 30),
 credential text, credential_version integer NOT NULL, active boolean NOT NULL, version integer NOT NULL
);
CREATE INDEX ix_integration_connections_org_id ON integration_connections(org_id);
CREATE TABLE integration_probes (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL, connection_id uuid NOT NULL REFERENCES integration_connections(id),
 connection_version integer NOT NULL, requested_by uuid NOT NULL REFERENCES users(id),
 page integer NOT NULL CHECK(page BETWEEN 1 AND 100),
 state varchar(20) NOT NULL CHECK(state IN ('pending','running','succeeded','failed','stale')),
 lease_id uuid, lease_until timestamptz, finished_at timestamptz, result jsonb NOT NULL,
 error_code varchar(80), duration_ms integer
);
CREATE INDEX ix_integration_probes_connection_id ON integration_probes(connection_id);
CREATE UNIQUE INDEX one_active_probe ON integration_probes(connection_id) WHERE state IN ('pending','running');
CREATE TABLE model_profiles (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL, org_id uuid NOT NULL REFERENCES organizations(id),
 connection_id uuid NOT NULL REFERENCES integration_connections(id), name varchar(120) NOT NULL,
 model varchar(256) NOT NULL, temperature double precision NOT NULL CHECK(temperature BETWEEN 0 AND 2),
 role varchar(20) NOT NULL CHECK(role IN ('implementation','verifier','planning')),
 active boolean NOT NULL, version integer NOT NULL
);
CREATE INDEX ix_model_profiles_org_id ON model_profiles(org_id);
CREATE TABLE agent_configurations (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL, org_id uuid NOT NULL REFERENCES organizations(id),
 name varchar(120) NOT NULL, provider varchar(20) NOT NULL CHECK(provider IN ('hermes','opencode')),
 executable varchar(512) NOT NULL, expected_version varchar(80) NOT NULL,
 model_profile_id uuid NOT NULL REFERENCES model_profiles(id),
 timeout_seconds integer NOT NULL CHECK(timeout_seconds BETWEEN 10 AND 3600), active boolean NOT NULL, version integer NOT NULL
);
CREATE INDEX ix_agent_configurations_org_id ON agent_configurations(org_id);
CREATE TABLE project_integrations (
 project_id uuid PRIMARY KEY REFERENCES projects(id), connection_id uuid NOT NULL REFERENCES integration_connections(id),
 repository_id varchar(256) NOT NULL, full_name varchar(256) NOT NULL, default_branch varchar(256) NOT NULL,
 probe_id uuid NOT NULL REFERENCES integration_probes(id),
 implementation_agent_id uuid REFERENCES agent_configurations(id), verifier_agent_id uuid REFERENCES agent_configurations(id),
 require_distinct_models boolean NOT NULL, version integer NOT NULL
);
