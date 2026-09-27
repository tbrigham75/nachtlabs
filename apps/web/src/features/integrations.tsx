"use client";
import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, write, type User } from "@nachtlabs/api-client";
import { isCleartextOffHost } from "./endpoint-address";
import {
  Action,
  Badge,
  Dialog,
  Empty,
  ErrorNotice,
  Form,
  Heading,
  Loading,
  type Field,
} from "@/components/ui";
import type { Connection, Probe } from "./integration-types";

const providers = ["github", "gitea", "ollama"];
const booleanOptions = [
  { value: "false", label: "No" },
  { value: "true", label: "Yes" },
];
export function IntegrationsScreen({
  user,
  provider,
}: {
  user: User;
  provider?: string;
}) {
  const admin = ["owner", "admin"].includes(user.role);
  const client = useQueryClient();
  const [editing, setEditing] = useState<Connection | null | undefined>();
  const [selected, setSelected] = useState<string>();
  const connections = useQuery({
    queryKey: ["integrations"],
    queryFn: () => api<Connection[]>("/integrations"),
    enabled: admin,
    refetchInterval: 10000,
  });
  const refresh = () =>
    client.invalidateQueries({ queryKey: ["integrations"] });
  if (!admin)
    return (
      <ErrorNotice error={new Error("Owner or Admin access is required")} />
    );
  if (provider === "hermes" || provider === "opencode")
    return (
      <>
        <Heading title={provider === "hermes" ? "Hermes Agent" : "OpenCode"} />
        <Link href={`/agents-models/${provider}`}>
          Manage agent configuration and capabilities →
        </Link>
      </>
    );
  const visible = connections.data?.filter(
    (c) => !providers.includes(provider ?? "") || c.provider === provider,
  );
  return (
    <>
      <Heading
        title="Integrations"
        note="Store connection settings and request bounded server-side discovery. Configuration does not prove compatibility."
      >
        <button className="primary" onClick={() => setEditing(null)}>
          + Add connection
        </button>
      </Heading>
      <div className="tabs">
        <Link href="/integrations">All connections</Link>
        {providers.map((p) => (
          <Link key={p} href={`/integrations/${p}`}>
            {p}
          </Link>
        ))}
        <Link href="/agents-models">Agents & models</Link>
      </div>
      <p className="notice">
        Provider checks require installation-level network permission. Git
        provider access is separately disabled by default. Saving settings sends
        no provider traffic.
      </p>
      <ErrorNotice error={connections.error} />
      {connections.isPending ? (
        <Loading />
      ) : !visible?.length ? (
        <Empty title="No connections configured">
          <p>
            Add a permitted endpoint. Its status remains unverified until an
            explicit check succeeds.
          </p>
        </Empty>
      ) : (
        <div className="grid two">
          {visible.map((c) => (
            <section className="panel" key={c.id}>
              <div className="panel-head">
                <h2>{c.name}</h2>
                <Badge>{c.provider}</Badge>
              </div>
              <p>{c.base_url}</p>
              <ul className="checklist">
                <li>
                  Credentials
                  <Badge>
                    {c.credential_present
                      ? `Stored · version ${c.credential_version}`
                      : "Not stored"}
                  </Badge>
                </li>
                <li>
                  Network policy
                  <Badge>{c.network_allowed ? "Permitted" : "Disabled"}</Badge>
                </li>
                <li>
                  Last connection check
                  <Badge
                    good={
                      c.latest_probe?.state === "succeeded" &&
                      c.latest_probe.connection_version === c.version
                    }
                  >
                    {c.latest_probe
                      ? c.latest_probe.connection_version === c.version
                        ? c.latest_probe.state
                        : "Configuration changed"
                      : "Not run"}
                  </Badge>
                </li>
                <li>
                  Transport
                  <Badge>
                    {isCleartextOffHost(c.base_url, c.pinned_addresses)
                      ? "Cleartext, unprotected"
                      : c.base_url.startsWith("http://")
                        ? "Loopback cleartext"
                        : "TLS"}
                  </Badge>
                </li>
                <li>
                  Agent execution<Badge>Unavailable</Badge>
                </li>
              </ul>
              <div className="actions">
                <button onClick={() => setEditing(c)}>Edit settings</button>
                <button onClick={() => setSelected(c.id)}>
                  Credentials & discovery
                </button>
              </div>
            </section>
          ))}
        </div>
      )}
      {editing !== undefined && (
        <Dialog
          title={editing ? "Edit connection" : "Add connection"}
          close={() => setEditing(undefined)}
        >
          <ConnectionEditor
            value={editing}
            provider={provider}
            save={async (body) => {
              await write(
                editing ? `/integrations/${editing.id}` : "/integrations",
                body,
                editing ? "PUT" : "POST",
              );
              setEditing(undefined);
              await refresh();
            }}
          />
        </Dialog>
      )}
      {selected && (
        <Dialog
          title="Credentials and discovery"
          close={() => setSelected(undefined)}
        >
          <ConnectionDetail identifier={selected} />
        </Dialog>
      )}
    </>
  );
}
function ConnectionEditor({
  value,
  provider,
  save,
}: {
  value: Connection | null;
  provider?: string;
  save: (body: unknown) => Promise<void>;
}) {
  const fields: Field[] = [
    { name: "name", label: "Connection name", required: true, max: 120 },
    {
      name: "provider",
      label: "Provider",
      options: (value ? [value.provider] : providers).map((v) => ({
        value: v,
        label: v,
      })),
    },
    {
      name: "base_url",
      label: "Base origin",
      required: true,
      help: "GitHub: https://api.github.com. Gitea/Ollama: origin only, no path or credentials.",
    },
    {
      name: "address",
      label: "Pinned server IP",
      required: true,
      help: "Administrator-approved numeric IP. TLS still verifies the hostname. An IP change requires an explicit settings update.",
    },
    {
      name: "allow_private",
      label: "Permit this private/loopback address",
      options: booleanOptions,
    },
    {
      name: "allow_http",
      label: "Permit HTTP for this loopback endpoint",
      options: booleanOptions,
      help: "Non-loopback endpoints require HTTPS. Cloud metadata destinations are always rejected.",
    },
    {
      name: "timeout_seconds",
      label: "Per-request timeout (1–30 seconds)",
      type: "number",
      required: true,
    },
    { name: "active", label: "Configuration active", options: booleanOptions },
  ];
  return (
    <>
      <p>
        Changing destination or transport policy removes stored credentials.
        Re-enter them deliberately after saving.
      </p>
      <Form
        fields={fields}
        initial={{
          name: value?.name ?? "",
          provider:
            value?.provider ??
            (providers.includes(provider ?? "") ? provider! : "github"),
          base_url: value?.base_url ?? "https://api.github.com",
          address: value?.pinned_addresses[0] ?? "",
          allow_private: String(value?.allow_private ?? false),
          allow_http: String(value?.allow_http ?? false),
          timeout_seconds: String(value?.timeout_seconds ?? 15),
          active: String(value?.active ?? true),
        }}
        submit={async (v) =>
          save({
            name: v.name,
            provider: v.provider,
            base_url: v.base_url,
            pinned_addresses: [v.address.trim()],
            allow_private: v.allow_private === "true",
            allow_http: v.allow_http === "true",
            timeout_seconds: Number(v.timeout_seconds),
            active: v.active === "true",
            expected_version: value?.version ?? 0,
          })
        }
      />
    </>
  );
}
function ConnectionDetail({ identifier }: { identifier: string }) {
  const client = useQueryClient();
  const connection = useQuery({
    queryKey: ["integration", identifier],
    queryFn: () => api<Connection>(`/integrations/${identifier}`),
    refetchInterval: 5000,
  });
  const probes = useQuery({
    queryKey: ["probes", identifier],
    queryFn: () => api<Probe[]>(`/integrations/${identifier}/probes`),
    refetchInterval: 5000,
  });
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ["integration", identifier] });
    await client.invalidateQueries({ queryKey: ["integrations"] });
    await client.invalidateQueries({ queryKey: ["probes", identifier] });
  };
  if (connection.isPending) return <Loading />;
  if (connection.error) return <ErrorNotice error={connection.error} />;
  const c = connection.data!;
  const queue = async (page = 1) => {
    await write(`/integrations/${identifier}/probes`, {
      expected_version: c.version,
      page,
    });
    await refresh();
  };
  return (
    <>
      <h3>{c.name}</h3>
      <p>
        Tokens are encrypted and cannot be read back. Git connections use a
        narrowly scoped personal access token in this initial adapter. Replacing
        credentials replaces all fields; revoke the old token at its provider
        too.
      </p>
      <Form
        key={c.version}
        fields={[
          {
            name: "token",
            label:
              c.provider === "ollama"
                ? "Optional proxy bearer token"
                : "Provider token",
            type: "password",
          },
          {
            name: "webhook_secret",
            label: "Optional webhook signing secret",
            type: "password",
            help: "Signature primitives only; public webhook intake is not available yet.",
          },
        ]}
        label="Replace stored credentials"
        submit={async (v) => {
          await write(
            `/integrations/${identifier}/credential`,
            {
              token: v.token || null,
              webhook_secret: v.webhook_secret || null,
              expected_version: c.version,
            },
            "PUT",
          );
          await refresh();
        }}
      />
      {c.credential_present && (
        <Action
          danger
          action={async () => {
            if (!window.confirm("Remove all credentials for this connection?"))
              return;
            await write(`/integrations/${identifier}/credential/revoke`, {
              expected_version: c.version,
            });
            await refresh();
          }}
        >
          Revoke stored credentials
        </Action>
      )}
      <h3 style={{ marginTop: 24 }}>Connection checks</h3>
      {c.network_allowed && c.active ? (
        <Action action={() => queue()}>Request connection check</Action>
      ) : (
        <p className="notice">
          Checks are disabled by configuration or installation policy.
        </p>
      )}
      <ErrorNotice error={probes.error} />
      {probes.data?.map((p) => (
        <section className="history-item" key={p.id}>
          <div className="panel-head">
            <strong>{new Date(p.created_at).toLocaleString()}</strong>
            <Badge>
              {p.state} · page {p.page}
            </Badge>
          </div>
          <p>
            {p.error_code ??
              (p.state === "succeeded"
                ? "Discovery completed. Compatibility and execution remain unverified."
                : "Awaiting worker result")}
          </p>
          <small>
            Configuration v{p.connection_version} ·{" "}
            {p.duration_ms === null
              ? "Duration unknown"
              : `${p.duration_ms} ms`}
          </small>
          {p.result.provider_version && (
            <p>Reported provider version: {p.result.provider_version}</p>
          )}
          {!!p.result.repositories?.length && (
            <ul>
              {p.result.repositories.map((r) => (
                <li key={r.provider_id}>
                  {r.full_name} · {r.default_branch}
                </li>
              ))}
            </ul>
          )}
          {!!p.result.models?.length && (
            <ul>
              {p.result.models.map((m) => (
                <li key={m.name}>
                  {m.name}
                  <small>{m.digest ?? "Digest unavailable"}</small>
                </li>
              ))}
            </ul>
          )}
          {p.result.next_page &&
            c.network_allowed &&
            p.connection_version === c.version && (
              <Action action={() => queue(p.result.next_page!)}>
                Discover next page
              </Action>
            )}
        </section>
      ))}
    </>
  );
}
