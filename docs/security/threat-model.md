# Threat model — Checkpoint A

Assets: password/session/key verifiers, encryption key, MFA seeds, identity links, protected holdouts, role/membership assignments, immutable governance/audit history, SMTP credentials and database state.

Boundaries: browser → proxy → API; API/worker → PostgreSQL with different roles; protected credential files → permitted service identities; worker → configured SMTP. Web has no database/master-key access. No agent or repository code executes yet.

Authored controls include Argon2id, high-entropy random hashed credentials, HttpOnly/Secure/SameSite cookies, Origin/CSRF checks, independent rate-limit transactions, MFA replay protection/recovery, last-Owner locking, explicit project scopes, public schemas, append-only triggers/grants, authenticated encryption, bounded bodies, proxy restrictions and frontend CSP.

Host/database administrators remain trusted. Encryption cannot protect data from a compromised authorized key-holding process. HttpOnly does not prevent XSS from acting as the current user. Backup confidentiality depends on private age identity custody.

M6 must prove native execution isolation before agents can run. Directory separation or a systemd unit alone is not a complete sandbox. Recommend dedicated production hosts/VMs once execution exists. All current controls are source-authored and unverified until operator acceptance.

M4 adds provider-response and outbound-request boundaries: explicit IP pins, hostname TLS, redirect rejection, private-address policy, independent Git network gate, fixed error classifications and write-only credential APIs. These controls require operator security testing; see the integration architecture and compatibility matrix.
