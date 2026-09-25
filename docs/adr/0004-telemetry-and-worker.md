# ADR 0004: foundation worker and telemetry

Worker duties are encrypted email outbox delivery, expired identity cleanup and heartbeat. PostgreSQL claims/leases and bounded retries implement at-least-once delivery. No workflow execution dispatch exists.

Application logs use JSON request IDs/route templates/timing/safe outcomes; audit is separate durable data. Log exploration, metrics/traces, insights and notification dashboards arrive later. No fabricated operational data fills unfinished screens.
