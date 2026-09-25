# M4 administrative API

All routes are under /api/v1. Human Owner/Admin session required. Mutations require Origin, CSRF and recent authentication. Existing service-account scopes do not grant integration administration.

| Route | Purpose |
| --- | --- |
| GET/POST /integrations | List safe configuration / create |
| GET/PUT /integrations/{id} | Read safe configuration / versioned update |
| PUT /integrations/{id}/credential | Replace encrypted bundle; no readback |
| POST /integrations/{id}/credential/revoke | Remove bundle and invalidate version |
| GET/POST /integrations/{id}/probes | Recent discovery results / explicitly queue |
| GET/POST /model-profiles | List/create Ollama profiles |
| PUT /model-profiles/{id} | Versioned profile update |
| GET/POST /agents | List/create agent configurations |
| PUT /agents/{id} | Versioned configuration update |
| GET/PUT /projects/{id}/integration | Read/set discovered repository and routing |

Creation expects expected_version=0; updates require the current version. Provider is immutable on a connection. Destination changes remove credentials. Probe result metadata binds connection_version, state, page, timestamps, duration and fixed error code; results are not agent readiness.

Public output projections omit all ciphertext, tokens and signing secrets. Credential rotation is local; no automatic provider revocation occurs. A valid signature primitive does not create an HTTP webhook endpoint. No generation, agent execution, Git write, merge or deployment route exists in M4.
