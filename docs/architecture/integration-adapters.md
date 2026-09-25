# Integration adapter map
Read-only GitHub/Gitea repository discovery and Ollama model discovery/chat are in core integrations/providers.py. Pinned transport details are in integrations.md. Agent Invocation contracts are in integrations/agents.py; actual process/cgroup ownership is in execution/sandbox.py and broker.py.

Signed issue-comment webhooks validate raw-body HMAC, exact repository identity, sender, labels, command and delivery fingerprint. They create work only; they cannot approve, execute or expose credentials.

PR reconciliation is in integrations/delivery.py. Trusted local Git orchestration is in execution/delivery.py. Neither is invoked by importing modules or configuring a provider. Model and Git network flags default false; native executor qualification is separately required.

The synthetic DevelopmentAdapter follows the Invocation boundary for a manual development harness and refuses production settings. It does not certify external provider compatibility. All compatibility statuses remain unverified.
