# Acceptance matrix

Source: Original Prompt, section 21. Every runtime result remains NOT RUN. Record the source snapshot, date, operator, relevant milestone and evidence before changing a status. Remote-provider items remain subject to the organization restriction.

| # | Original acceptance requirement | Result | Evidence / defect |
|---|---|---|---|
| 1 | An operator installs and runs NachtLabs on Linux as native services. | NOT RUN | |
| 2 | No Docker, Docker Compose, Kubernetes, or container runtime is required. | NOT RUN | |
| 3 | PostgreSQL, API, worker, and web services are installed and managed through documented Linux/systemd procedures. | NOT RUN | |
| 4 | The developer creates the first account, which becomes Owner. | NOT RUN | |
| 5 | The Owner can sign in securely. | NOT RUN | |
| 6 | The Owner can select any of the six complete themes. | NOT RUN | |
| 7 | The Owner creates a project Mission with scope, non-goals, constraints, and a required validation baseline. | NOT RUN | |
| 8 | The Owner creates at least one Validation Journey for the project. | NOT RUN | |
| 9 | The Owner configures a local or remote Ollama endpoint and successfully tests connectivity. | NOT RUN | |
| 10 | The Owner configures at least one coding-agent adapter: Hermes Agent or OpenCode. | NOT RUN | |
| 11 | The Owner connects GitHub or self-hosted Gitea. | NOT RUN | |
| 12 | The Owner selects a repository and creates a NachtLabs project. | NOT RUN | |
| 13 | The Owner configures a safe validation command for the project. | NOT RUN | |
| 14 | The Owner creates one small bounded work request through the web UI. | NOT RUN | |
| 15 | NachtLabs performs intake validation, Mission/scope assessment, and repository discovery. | NOT RUN | |
| 16 | NachtLabs creates and displays a plan with affected files, risks, test plan, acceptance-criteria mapping, Mission alignment, and affected Validation Journeys. | NOT RUN | |
| 17 | The Owner approves the plan. | NOT RUN | |
| 18 | NachtLabs creates an isolated Linux workspace and feature branch. | NOT RUN | |
| 19 | NachtLabs invokes the configured agent adapter to make a small safe change, such as a documentation or tightly scoped code change. | NOT RUN | |
| 20 | NachtLabs runs configured checks, a secret scan, and at least one required Validation Journey. | NOT RUN | |
| 21 | NachtLabs invokes an independently configured verifier stage and displays its structured result. | NOT RUN | |
| 22 | NachtLabs records command evidence, logs, tool calls, model/agent data, artifacts, Git evidence, commit/push outcomes, Mission assessment, Validation Journey evidence, verifier findings, and state transitions. | NOT RUN | |
| 23 | NachtLabs creates a target-repository commit, pushes the feature branch, and opens a real GitHub or Gitea pull request. | NOT RUN | |
| 24 | NachtLabs displays PR link/status in run details. | NOT RUN | |
| 25 | NachtLabs records immutable audit events for all material actions. | NOT RUN | |
| 26 | Monitoring & Insights displays correlated run and system logs. | NOT RUN | |
| 27 | A deliberately induced non-sensitive test failure or unavailable test endpoint produces a visible incident/alert. | NOT RUN | |
| 28 | NachtLabs groups related errors and generates an evidence-backed remediation recommendation. | NOT RUN | |
| 29 | The recommendation requires human approval before any configuration-changing action. | NOT RUN | |
| 30 | The UI clearly distinguishes verified evidence from inferred root cause/recommendation. | NOT RUN | |
| 31 | A manually triggered regression run can execute a configured Validation Journey and display results. | NOT RUN | |
| 32 | NachtLabs services run under documented non-root systemd service accounts with defined filesystem restrictions and health checks. | NOT RUN | |
| 33 | The NachtLabs repository itself remains uncommitted/unpushed unless the operator explicitly asks for those actions. | NOT RUN | |

Item 32: API/worker/web remain non-root; the additional executor broker is privileged and requires explicit qualification of its separate job sandboxes. Review this boundary during security acceptance.
Item 22: Hermes telemetry is opaque and raw command output is deliberately omitted; record the accepted evidence/observability limits.
Item 33: no Git initialization, commit or remote operation was performed during authoring; retain that boundary during testing.
