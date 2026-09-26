CREATE TABLE organizations (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL, singleton integer NOT NULL UNIQUE CHECK (singleton = 1),
 name varchar(120) NOT NULL, require_admin_mfa boolean NOT NULL, version integer NOT NULL
);
CREATE TABLE users (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL, org_id uuid NOT NULL REFERENCES organizations(id),
 email varchar(254) NOT NULL UNIQUE, name varchar(120) NOT NULL, password_hash text NOT NULL,
 role varchar(20) NOT NULL CHECK (role IN ('owner','admin','operator','contributor','viewer')),
 active boolean NOT NULL, theme varchar(30) NOT NULL, mfa_secret text, mfa_pending text,
 mfa_last_step integer NOT NULL, recovery_hashes jsonb NOT NULL, version integer NOT NULL
);
CREATE INDEX ix_users_org_id ON users(org_id);
CREATE TABLE user_sessions (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL, user_id uuid NOT NULL REFERENCES users(id),
 token_hash varchar(64) NOT NULL UNIQUE, csrf_hash varchar(64) NOT NULL,
 expires_at timestamptz NOT NULL, idle_expires_at timestamptz NOT NULL,
 authenticated_at timestamptz NOT NULL, mfa_verified boolean NOT NULL
);
CREATE INDEX ix_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX sessions_expiry ON user_sessions(expires_at);
CREATE TABLE login_challenges (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL, user_id uuid NOT NULL REFERENCES users(id),
 token_hash varchar(64) NOT NULL UNIQUE, expires_at timestamptz NOT NULL
);
CREATE INDEX ix_login_challenges_user_id ON login_challenges(user_id);
CREATE TABLE identity_tokens (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL, org_id uuid NOT NULL REFERENCES organizations(id),
 email varchar(254) NOT NULL, purpose varchar(20) NOT NULL CHECK (purpose IN ('reset','invitation')),
 role varchar(20) NOT NULL, token_hash varchar(64) NOT NULL UNIQUE,
 expires_at timestamptz NOT NULL, consumed_at timestamptz
);
CREATE INDEX ix_identity_tokens_email ON identity_tokens(email);
CREATE TABLE projects (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL, org_id uuid NOT NULL REFERENCES organizations(id),
 name varchar(120) NOT NULL, slug varchar(80) NOT NULL, description text NOT NULL,
 archived boolean NOT NULL, version integer NOT NULL, plan_approval_required boolean NOT NULL,
 delivery_mode varchar(20) NOT NULL, UNIQUE(org_id, slug),
 CHECK (plan_approval_required AND delivery_mode = 'pr_only')
);
CREATE INDEX ix_projects_org_id ON projects(org_id);
CREATE TABLE project_members (
 project_id uuid NOT NULL REFERENCES projects(id), user_id uuid NOT NULL REFERENCES users(id),
 PRIMARY KEY(project_id,user_id)
);
CREATE TABLE governance_documents (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL, project_id uuid NOT NULL REFERENCES projects(id),
 kind varchar(20) NOT NULL CHECK (kind IN ('mission','journey','holdout')), name varchar(120) NOT NULL,
 version integer NOT NULL, approved_version integer, archived boolean NOT NULL,
 CHECK (approved_version IS NULL OR (approved_version > 0 AND approved_version <= version))
);
CREATE INDEX ix_governance_documents_project_id ON governance_documents(project_id);
CREATE UNIQUE INDEX one_mission_per_project ON governance_documents(project_id) WHERE kind = 'mission';
CREATE TABLE governance_versions (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL, document_id uuid NOT NULL REFERENCES governance_documents(id),
 number integer NOT NULL CHECK (number > 0), author_id uuid NOT NULL REFERENCES users(id), content jsonb NOT NULL,
 UNIQUE(document_id,number)
);
CREATE INDEX ix_governance_versions_document_id ON governance_versions(document_id);
CREATE TABLE holdout_contents (
 version_id uuid PRIMARY KEY REFERENCES governance_versions(id), ciphertext text NOT NULL
);
CREATE TABLE governance_approvals (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL, version_id uuid NOT NULL UNIQUE REFERENCES governance_versions(id),
 approver_id uuid NOT NULL REFERENCES users(id)
);
CREATE TABLE service_accounts (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL, org_id uuid NOT NULL REFERENCES organizations(id),
 name varchar(120) NOT NULL, active boolean NOT NULL
);
CREATE INDEX ix_service_accounts_org_id ON service_accounts(org_id);
CREATE TABLE api_keys (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL, service_account_id uuid NOT NULL REFERENCES service_accounts(id),
 name varchar(120) NOT NULL, prefix varchar(16) NOT NULL, token_hash varchar(64) NOT NULL UNIQUE,
 scopes jsonb NOT NULL, project_ids jsonb NOT NULL, expires_at timestamptz, revoked_at timestamptz,
 last_used_at timestamptz, last_source varchar(64)
);
CREATE INDEX ix_api_keys_service_account_id ON api_keys(service_account_id);
CREATE TABLE audit_events (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL, org_id uuid REFERENCES organizations(id),
 project_id uuid REFERENCES projects(id), actor_id varchar(80) NOT NULL, action varchar(100) NOT NULL,
 target varchar(100) NOT NULL, outcome varchar(20) NOT NULL, request_id varchar(36) NOT NULL,
 source varchar(64) NOT NULL, details jsonb NOT NULL
);
CREATE INDEX ix_audit_events_org_id ON audit_events(org_id);
CREATE INDEX ix_audit_events_project_id ON audit_events(project_id);
CREATE INDEX ix_audit_events_action ON audit_events(action);
CREATE INDEX audit_cursor ON audit_events(created_at,id);
CREATE TABLE rate_buckets (key varchar(64) PRIMARY KEY, "window" integer NOT NULL, count integer NOT NULL);
CREATE TABLE mail_jobs (
 id uuid PRIMARY KEY, created_at timestamptz NOT NULL, payload text, state varchar(20) NOT NULL,
 attempts integer NOT NULL, next_attempt_at timestamptz NOT NULL, lease_until timestamptz,
 last_error varchar(80), CHECK(state IN ('pending','sending','sent','failed'))
);
CREATE INDEX ix_mail_jobs_state ON mail_jobs(state);
CREATE TABLE worker_heartbeats (name varchar(80) PRIMARY KEY, seen_at timestamptz NOT NULL, version varchar(20) NOT NULL);

CREATE FUNCTION nachtlabs_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'This NachtLabs record is append-only';
END;
$$;
CREATE TRIGGER immutable_audit BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION nachtlabs_immutable();
CREATE TRIGGER immutable_governance BEFORE UPDATE OR DELETE ON governance_versions FOR EACH ROW EXECUTE FUNCTION nachtlabs_immutable();
CREATE TRIGGER immutable_approvals BEFORE UPDATE OR DELETE ON governance_approvals FOR EACH ROW EXECUTE FUNCTION nachtlabs_immutable();

CREATE FUNCTION nachtlabs_member_tenant() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (SELECT org_id FROM projects WHERE id = NEW.project_id) IS DISTINCT FROM
    (SELECT org_id FROM users WHERE id = NEW.user_id) THEN
   RAISE EXCEPTION 'Project membership organization mismatch';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER membership_tenant BEFORE INSERT OR UPDATE ON project_members FOR EACH ROW EXECUTE FUNCTION nachtlabs_member_tenant();
