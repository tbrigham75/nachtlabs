CREATE TABLE project_policies (
 project_id uuid PRIMARY KEY REFERENCES projects(id),
 version integer NOT NULL,
 configuration jsonb NOT NULL
);
CREATE TABLE workflow_definitions (
 id uuid PRIMARY KEY,
 created_at timestamptz NOT NULL,
 org_id uuid NOT NULL REFERENCES organizations(id),
 name varchar(120) NOT NULL,
 version integer NOT NULL,
 configuration jsonb NOT NULL,
 UNIQUE (org_id, name, version)
);
CREATE INDEX ix_workflow_definitions_org_id ON workflow_definitions(org_id);
CREATE TABLE work_requests (
 id uuid PRIMARY KEY,
 created_at timestamptz NOT NULL,
 org_id uuid NOT NULL REFERENCES organizations(id),
 project_id uuid NOT NULL REFERENCES projects(id),
 actor varchar(80) NOT NULL,
 source varchar(20) NOT NULL,
 title varchar(200) NOT NULL,
 description text NOT NULL,
 criteria jsonb NOT NULL,
 metadata_json jsonb NOT NULL,
 target_ref varchar(256) NOT NULL,
 workflow_id uuid REFERENCES workflow_definitions(id),
 idempotency_key varchar(64) NOT NULL,
 request_hash varchar(64) NOT NULL,
 status varchar(30) NOT NULL,
 UNIQUE (project_id, actor, idempotency_key)
);
CREATE INDEX ix_work_requests_org_id ON work_requests(org_id);
CREATE INDEX ix_work_requests_project_id ON work_requests(project_id);
CREATE TABLE runs (
 id uuid PRIMARY KEY,
 created_at timestamptz NOT NULL,
 request_id uuid NOT NULL REFERENCES work_requests(id),
 project_id uuid NOT NULL REFERENCES projects(id),
 kind varchar(20) NOT NULL,
 state varchar(40) NOT NULL,
 stage varchar(40) NOT NULL,
 version integer NOT NULL,
 event_seq integer NOT NULL,
 snapshot jsonb NOT NULL,
 plan jsonb NOT NULL,
 plan_digest varchar(64),
 base_commit varchar(64),
 candidate varchar(64),
 attempt integer NOT NULL,
 lease_id uuid,
 lease_until timestamptz,
 cancel_requested boolean NOT NULL,
 error_code varchar(80),
 updated_at timestamptz NOT NULL,
 delivery jsonb NOT NULL
);
CREATE INDEX ix_runs_request_id ON runs(request_id);
CREATE INDEX ix_runs_project_id ON runs(project_id);
CREATE TABLE run_events (
 id uuid PRIMARY KEY,
 created_at timestamptz NOT NULL,
 run_id uuid NOT NULL REFERENCES runs(id),
 sequence integer NOT NULL,
 category varchar(80) NOT NULL,
 severity varchar(20) NOT NULL,
 stage varchar(40) NOT NULL,
 details jsonb NOT NULL,
 UNIQUE (run_id, sequence)
);
CREATE INDEX ix_run_events_run_id ON run_events(run_id);
CREATE TABLE run_approvals (
 id uuid PRIMARY KEY,
 created_at timestamptz NOT NULL,
 run_id uuid NOT NULL REFERENCES runs(id),
 digest varchar(64) NOT NULL,
 decision varchar(30) NOT NULL,
 user_id uuid NOT NULL REFERENCES users(id),
 reason text NOT NULL,
 expires_at timestamptz NOT NULL
);
CREATE INDEX ix_run_approvals_run_id ON run_approvals(run_id);
CREATE TABLE run_evidence (
 id uuid PRIMARY KEY,
 created_at timestamptz NOT NULL,
 run_id uuid NOT NULL REFERENCES runs(id),
 candidate varchar(64) NOT NULL,
 name varchar(160) NOT NULL,
 kind varchar(30) NOT NULL,
 status varchar(30) NOT NULL,
 protected boolean NOT NULL,
 payload text NOT NULL,
 content_hash varchar(64) NOT NULL,
 actor varchar(80) NOT NULL
);
CREATE INDEX ix_run_evidence_run_id ON run_evidence(run_id);
CREATE TABLE executor_jobs (
 id uuid PRIMARY KEY,
 created_at timestamptz NOT NULL,
 run_id uuid NOT NULL REFERENCES runs(id),
 stage varchar(40) NOT NULL,
 attempt integer NOT NULL,
 state varchar(30) NOT NULL,
 specification jsonb NOT NULL,
 spec_hash varchar(64) NOT NULL,
 result text,
 lease_id uuid,
 lease_until timestamptz,
 unit_name varchar(100),
 finished_at timestamptz,
 UNIQUE (run_id, stage, attempt)
);
CREATE INDEX ix_executor_jobs_run_id ON executor_jobs(run_id);
CREATE TABLE webhook_bindings (
 id uuid PRIMARY KEY,
 created_at timestamptz NOT NULL,
 project_id uuid NOT NULL UNIQUE REFERENCES projects(id),
 connection_id uuid NOT NULL REFERENCES integration_connections(id),
 enabled boolean NOT NULL,
 actors jsonb NOT NULL,
 labels jsonb NOT NULL,
 commands jsonb NOT NULL,
 version integer NOT NULL
);
CREATE TABLE webhook_receipts (
 id uuid PRIMARY KEY,
 created_at timestamptz NOT NULL,
 binding_id uuid NOT NULL REFERENCES webhook_bindings(id),
 delivery_key varchar(64) NOT NULL UNIQUE,
 payload_hash varchar(64) NOT NULL,
 status varchar(30) NOT NULL,
 request_id uuid REFERENCES work_requests(id)
);
CREATE INDEX ix_webhook_receipts_binding_id ON webhook_receipts(binding_id);
CREATE TABLE factory_controls (
 org_id uuid PRIMARY KEY REFERENCES organizations(id),
 emergency_stop boolean NOT NULL,
 version integer NOT NULL
);
CREATE TABLE incidents (
 id uuid PRIMARY KEY,
 created_at timestamptz NOT NULL,
 org_id uuid NOT NULL REFERENCES organizations(id),
 project_id uuid REFERENCES projects(id),
 fingerprint varchar(64) NOT NULL,
 category varchar(80) NOT NULL,
 severity varchar(20) NOT NULL,
 status varchar(20) NOT NULL,
 occurrences integer NOT NULL,
 last_seen timestamptz NOT NULL,
 assigned_to uuid REFERENCES users(id),
 snoozed_until timestamptz,
 version integer NOT NULL,
 evidence_refs jsonb NOT NULL,
 UNIQUE (org_id, fingerprint)
);
CREATE INDEX ix_incidents_org_id ON incidents(org_id);
CREATE TABLE incident_events (
 id uuid PRIMARY KEY,
 created_at timestamptz NOT NULL,
 incident_id uuid NOT NULL REFERENCES incidents(id),
 actor varchar(80) NOT NULL,
 action varchar(40) NOT NULL,
 note text NOT NULL
);
CREATE INDEX ix_incident_events_incident_id ON incident_events(incident_id);
CREATE TABLE recommendations (
 id uuid PRIMARY KEY,
 created_at timestamptz NOT NULL,
 incident_id uuid NOT NULL UNIQUE REFERENCES incidents(id),
 status varchar(20) NOT NULL,
 proposal jsonb NOT NULL,
 proposal_hash varchar(64) NOT NULL,
 approved_by uuid REFERENCES users(id),
 expires_at timestamptz,
 applied_version integer,
 version integer NOT NULL
);
CREATE TABLE notifications (
 id uuid PRIMARY KEY,
 created_at timestamptz NOT NULL,
 user_id uuid NOT NULL REFERENCES users(id),
 incident_id uuid NOT NULL REFERENCES incidents(id),
 read_at timestamptz,
 UNIQUE (user_id, incident_id)
);
CREATE INDEX ix_notifications_user_id ON notifications(user_id);
CREATE TABLE saved_searches (
 id uuid PRIMARY KEY,
 created_at timestamptz NOT NULL,
 org_id uuid NOT NULL REFERENCES organizations(id),
 user_id uuid NOT NULL REFERENCES users(id),
 name varchar(120) NOT NULL,
 filters jsonb NOT NULL,
 shared boolean NOT NULL
);
CREATE TABLE retention_policies (
 org_id uuid PRIMARY KEY REFERENCES organizations(id),
 log_days integer NOT NULL,
 artifact_days integer NOT NULL,
 version integer NOT NULL
);
CREATE UNIQUE INDEX one_active_factory_execution ON executor_jobs ((1)) WHERE state IN ('claimed','running');
CREATE TRIGGER immutable_workflow_definitions BEFORE UPDATE OR DELETE ON workflow_definitions FOR EACH ROW EXECUTE FUNCTION nachtlabs_immutable();
CREATE TRIGGER immutable_run_events BEFORE UPDATE OR DELETE ON run_events FOR EACH ROW EXECUTE FUNCTION nachtlabs_immutable();
CREATE TRIGGER immutable_run_approvals BEFORE UPDATE OR DELETE ON run_approvals FOR EACH ROW EXECUTE FUNCTION nachtlabs_immutable();
CREATE TRIGGER immutable_run_evidence BEFORE UPDATE OR DELETE ON run_evidence FOR EACH ROW EXECUTE FUNCTION nachtlabs_immutable();
CREATE TRIGGER immutable_incident_events BEFORE UPDATE OR DELETE ON incident_events FOR EACH ROW EXECUTE FUNCTION nachtlabs_immutable();
CREATE TABLE operational_events (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL,
 org_id uuid NOT NULL REFERENCES organizations(id),
 event_key varchar(160) NOT NULL UNIQUE, service varchar(40) NOT NULL,
 category varchar(80) NOT NULL, severity varchar(20) NOT NULL, details jsonb NOT NULL
);
CREATE INDEX ix_operational_events_org_id ON operational_events(org_id);


