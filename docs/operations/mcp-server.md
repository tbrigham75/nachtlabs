# Running the MCP server

An external agent (hermes) talks to NachtLabs over MCP through this server. It is
not part of the NachtLabs stack: it runs on its own host and is the only client of
the API.

## Why it is separate

The credential that can submit work is a bearer API key. If every agent held one,
each agent would hold a write-scoped credential for the installation. This server
holds it instead, so:

- the NachtLabs API key exists on exactly one machine and never travels to an agent,
- an agent holds only this server's token, so its blast radius is whatever these
  tools can do and no more,
- rotating the API key and revoking this surface are independent acts.

The tools stop where the credential stops. There is deliberately no tool for
creating a project, writing governance, approving a plan or setting the execution
policy: those need a human browser session, and a test asserts none is offered.

## What it exposes

| Tool | Purpose |
| --- | --- |
| `submit_work` | Create a work request against a branch and start a run |
| `get_run` | One run's state, stage and error code |
| `wait_for_run` | Block until the run settles or needs a person |
| `run_events` | Cursor-paginated event feed |
| `list_projects` | Projects the key can see |
| `list_runs` | A project's recent runs |
| `get_readiness` | Whether provider checks are enabled |

## Deploying

Build and run on the host that will serve the agent:

```bash
docker build -f Dockerfile.mcp -t nachtlabs/mcp:local .
```

Write both credentials as files. **Not environment variables**: an environment
variable is visible in `docker inspect` and in the process list, and one of these
is write-scoped.

```bash
install -d -m 0700 /etc/nachtlabs-mcp
printf '%s' 'nl_...' > /etc/nachtlabs-mcp/api-key
printf '%s' "$(openssl rand -hex 32)" > /etc/nachtlabs-mcp/mcp-token
chmod 0400 /etc/nachtlabs-mcp/api-key /etc/nachtlabs-mcp/mcp-token
```

`nl_...` is the NachtLabs API key, created by an Owner in the browser. The second
is this server's own token; give it to hermes and to nobody else.

```bash
docker run -d --name nachtlabs-mcp \\
  -p 3036:3036 \\
  -e NACHTLABS_URL=http://192.168.2.38:3035 \\
  -e NACHTLABS_API_KEY_FILE=/run/secrets/api-key \\
  -e NACHTLABS_MCP_TOKEN_FILE=/run/secrets/mcp-token \\
  -e NACHTLABS_PROJECT_IDS=<project-uuid> \\
  -v /etc/nachtlabs-mcp/api-key:/run/secrets/api-key:ro \\
  -v /etc/nachtlabs-mcp/mcp-token:/run/secrets/mcp-token:ro \\
  nachtlabs/mcp:local
```

`NACHTLABS_PROJECT_IDS` is optional. The API key is already bound to a set of
projects and refuses anything else with a 404; setting it turns a mistake into a
local error naming the configuration.

### The bind address

The image sets `NACHTLABS_MCP_BIND=0.0.0.0`, overriding a code default of
`127.0.0.1`. The code default is right on a bare host and wrong in a container: a
published port reaches the container's interfaces, not its loopback, so leaving it
alone produces a server that starts, logs that it is listening, and answers
nothing.

**This means every host that can reach the port can submit work with the
credentials this container holds.** If the machine has more than one interface,
set `NACHTLABS_MCP_BIND` to a single address. On a shared network, put it behind
TLS: the token is a bearer credential and is currently carried in the clear.

### The `Host` header

The API's `TrustedHostMiddleware` does not apply in the usual way behind the
container stack: the interface rewrites the internal request to `api:8000`, so the
client's `Host` never reaches the check. A bearer request therefore works from any
address the port is reachable on. Do not read a working bearer call as evidence
that host filtering is in force — it is not.

## Verifying

```bash
curl -s http://127.0.0.1:3036/healthz            # 200, and touches nothing upstream
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:3036/mcp   # 401
curl -s -X POST http://127.0.0.1:3036/mcp \\
  -H "Authorization: Bearer $(cat /etc/nachtlabs-mcp/mcp-token)" \\
  -H 'Content-Type: application/json' \\
  -H 'accept: application/json, text/event-stream' \\
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

`tools/list` should answer with seven tools. A 401 on the second call is correct: no
token was presented.

## Rotating

**This server's token** — replace the file and restart. Nothing upstream changes.

**The NachtLabs API key** — rotation is gated on a fresh human browser session, so
it cannot be automated from here. Create the new key in the interface, write it to
`/etc/nachtlabs-mcp/api-key`, restart the container, then revoke the old key. The
file is re-read per request, so the restart is only needed to pick up a change in
the *path*, not the value; a plain file swap is enough.

Both files are re-read per request, so a rotation does not require a rebuild.

## Diagnosing

| Symptom | Cause |
| --- | --- |
| 401 on everything | Wrong MCP token, or the file is missing and returns 503 instead |
| 403 `scope_required` | The API key lacks the scope; needs `work_requests:create` to submit |
| 404 on a project | Not bound to this key. Check `list_projects`. |
| 409 `mission_required` / `baseline_required` | A person must approve a Mission or Journey in the interface |
| Run sits in `awaiting_approval` | Expected. A human must approve the plan; do not resubmit |
| 429 | The key is over 300 requests per five minutes. The client backs off on its own. |

A run reaching `blocked` rather than `completed` is usually not a fault here: an
unqualified or absent executor stops it. See `docs/operations/executor-qualification.md`.
