# Linux systemd deployment

Use the M4 handoff and its foundation procedure for ordering; current schema head is 0002. Code/virtualenv: `/opt/nachtlabs`. Protected config/credentials: `/etc/nachtlabs`. Writable state: `/var/lib/nachtlabs/{api,worker,web}`. Logs: journald. API/web bind to loopback 8000/3000; Nginx terminates TLS and proxies `/api/` directly to FastAPI.

Installation requires resolved `/opt/nachtlabs`, provisions non-root users and copies three units, but does not start them. Configuration refuses to overwrite existing credential files. PostgreSQL roles start without passwords; assign through interactive psql `\password`. The schema owner runs migrations, then reviewed grants are applied against the explicitly selected database.

Systemd reads EnvironmentFile as manager; web receives no master key/DB connection. API/worker only read their required files. Keep installed code and virtualenv root-owned and non-writable by service users. Verify the Node executable location.

Updates: drain email, back up, retain source/locks, install/build reviewed source, migrate under the owner role, review grants, restart and check readiness. No implicit migrations or package updates run during service startup. Do not blindly downgrade schemas. The operator manages local snapshots/file transfer, with no remote Git/CI or containers.

Current full-source handoff: milestone-10-handoff.md. The installer also provisions an executor unit but does not start or qualify it. API/worker/web remain non-root; the separate root broker and its transient DynamicUser jobs require executor-qualification.md before use.
