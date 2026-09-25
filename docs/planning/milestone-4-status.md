# Milestone 4 authoring handoff

Handoff: **m4-source-2026-09-25**. M1–M4 source is authored. **No execution checks have run.** Stop before M5.

The operator extended the earlier Checkpoint A boundary and requested a source review followed by M4 under the same Windows/PowerShell, Linux-target, no-testing and local-only Git conditions. The earlier Checkpoint A reports are historical, not current scope.

| Requirement | Source implementation | Verification |
| --- | --- | --- |
| Re-review M1–M3 | [Findings and corrections](source-review-m4.md) | Source inspection only |
| Encrypted integration credentials | Write-only replacement/revocation, destination-bound context, lifecycle/use audit | NOT RUN |
| Encryption-key rotation | Previous-key decryption, offline transactional rewrap, recovery files, updated snapshots | NOT RUN |
| GitHub/Gitea | Typed repository discovery/lookup, paginated queue and project selection | NOT RUN; remote access prohibited |
| Ollama | Version/models discovery; internal bounded chat contract with nullable usage | NOT RUN |
| Endpoint security | Exact numeric IP pin, hostname TLS verification, private-CA setting, no redirects/proxies, bounded data/time | NOT RUN |
| Hermes/OpenCode | Separate capabilities, invocation specifications, event normalization, runner cancellation/results | NOT RUN; no restricted runner yet |
| Agent/model profiles | Admin CRUD, role routing, expected versions/timeouts, distinct-model policy | NOT RUN |
| UI/API | Integrations, Agents & Models, project selection; public schemas and version conflicts | NOT RUN |
| Worker | Explicit discovery queue, configuration-bound results, interrupted-job failure | NOT RUN |
| Webhooks | Raw-body HMAC verification and delivery/body fingerprint primitives | NOT RUN; intake deferred |
| Test definitions | Synthetic provider/endpoint/signature/agent contracts, PostgreSQL credential/access/queue guards | AUTHORED; NOT RUN |

## Deliberate boundaries

- All installed-agent tested versions are unknown. Documentation review is not compatibility proof.
- Hermes output remains opaque; complete tool-event visibility and containment require pinned-release acceptance.
- OpenCode uses documented JSON output and a protected attached request file; exact release semantics remain untested.
- Neither API nor worker starts agents or performs Git clone/fetch/commit/push/PR operations. No M5 workflow or M6 executor was added.
- GitHub initially uses narrow PATs against api.github.com. App/OAuth installation-token exchange and GitHub Enterprise are not implemented. Gitea supports custom HTTPS origins; subpath hosting is not implemented.
- One explicit pinned IP per origin is intentional. IP changes require configuration review and credential re-entry; no automatic DNS fallback.
- HTTP is restricted to explicitly approved loopback endpoints. Remote private services require HTTPS.
- Provider checks are off by default. Git checks also require a separate switch that must remain off under the current organization restriction.
- Ollama generation is an internal adapter contract, with no public generation/agent-dispatch endpoint.
- Provider-token replacement/revocation is local. Revoke old provider tokens at the provider when permitted; local removal cannot invalidate them elsewhere.
- Rotation is offline maintenance. Restarting with inconsistent key configuration will fail decryption.
- Dependency locks, generated OpenAPI/types, compiler compatibility, schema drift, accessibility, security and runtime behavior remain pending.

See [operator handoff](../operations/milestone-4-handoff.md) and [compatibility matrix](../integrations/compatibility.md). No Git initialization, commits, remotes, pushes, or live provider calls were performed.
