# Provider compatibility matrix

**All actual tested versions: NOT TESTED.** Published documentation was consulted while authoring. No installed executable, provider endpoint or remote repository was contacted.

| Provider | Authored contract | Evidence still required | Current state |
| --- | --- | --- | --- |
| GitHub | PAT-authenticated REST user/repos and repository metadata; API version 2022-11-28 | Permitted environment, token permissions, pagination/errors, signature fixtures | Unverified; network disabled |
| Gitea | Token REST /api/v1 user/repos and repository metadata; raw SHA-256 HMAC | Actual server version, private CA, pagination/auth/errors and webhook behavior | Unverified; network disabled |
| Ollama | /api/version, /api/tags, bounded nonstreaming /api/chat | Actual server/model/digest, generation errors/timeouts/usage, proxy auth | Unverified |
| OpenCode | run, JSON events, explicit model and protected attached request file | Exact installed version, input/event grammar, runner timeout/cancel, deny-by-default tools/config | Unverified; execution unavailable |
| Hermes | chat --query-file -, explicit model; opaque-output normalization | Exact version, tool visibility/config isolation, memory/skills/schedules disabled, runner cancel | Unverified; execution unavailable |

The agent's expected version field is operator input. It is never treated as tested/verified. Before M6 execution, the runner must verify the executable and version, install an isolated configuration/home, pin the model/endpoint, deny inherited plugins and credentials, enforce filesystem/network/process limits, and establish observable cancellation. Tool prompts are not containment.

Development fixtures live under core/integration tests. They replace transports with deterministic synthetic responses and must never count as real-provider evidence.

## Primary references

- [OpenCode CLI](https://opencode.ai/docs/cli/): run/model/file/format options.
- [OpenCode permissions](https://opencode.ai/docs/permissions/): release-specific configuration review required.
- [Hermes CLI](https://hermes-agent.nousresearch.com/docs/user-guide/cli/): documented file/stdin single query.
- [Ollama model listing](https://docs.ollama.com/api/tags) and [chat](https://docs.ollama.com/api/chat).
- [GitHub repository REST API](https://docs.github.com/en/rest/repos/repos?apiVersion=2022-11-28).
- [GitHub webhook verification](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries).
- [Gitea API reference](https://docs.gitea.com/api/1.24/) and [webhook signatures](https://docs.gitea.com/usage/repository/webhooks/).

These references inform the authored interfaces; they do not substitute for the operator's compatibility results.

M5–M10 add actual native executor and delivery source. Compatibility remains unverified for every real agent/provider. No authored adapter or qualification receipt template counts as observed compatibility. Follow ../operations/executor-qualification.md before enabling execution.
