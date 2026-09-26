"use client";
import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, write, type User } from "@nachtlabs/api-client";
import {
  Badge,
  Dialog,
  Empty,
  ErrorNotice,
  Form,
  Heading,
  Loading,
} from "@/components/ui";
import type {
  AgentConfig,
  Connection,
  ModelProfile,
} from "./integration-types";

export function AgentsModelsScreen({
  user,
  provider,
}: {
  user: User;
  provider?: string;
}) {
  const admin = ["owner", "admin"].includes(user.role),
    client = useQueryClient();
  const [model, setModel] = useState<ModelProfile | null | undefined>();
  const [agent, setAgent] = useState<AgentConfig | null | undefined>();
  const profiles = useQuery({
    queryKey: ["model-profiles"],
    queryFn: () => api<ModelProfile[]>("/model-profiles"),
    enabled: admin,
  });
  const agents = useQuery({
    queryKey: ["agents"],
    queryFn: () => api<AgentConfig[]>("/agents"),
    enabled: admin,
  });
  const connections = useQuery({
    queryKey: ["integrations"],
    queryFn: () => api<Connection[]>("/integrations"),
    enabled: admin,
  });
  if (!admin)
    return (
      <ErrorNotice error={new Error("Owner or Admin access is required")} />
    );
  const endpoints =
    connections.data?.filter((c) => c.provider === "ollama" && c.active) ?? [];
  const choices = profiles.data?.filter((p) => p.active) ?? [];
  const visible = agents.data?.filter(
    (a) =>
      !["hermes", "opencode"].includes(provider ?? "") ||
      a.provider === provider,
  );
  return (
    <>
      <Heading
        title="Agents & models"
        note="Configure explicit implementation and verifier profiles. No executable is invoked by this screen."
      />
      <div className="tabs">
        <Link href="/agents-models">All</Link>
        <Link href="/agents-models/hermes">Hermes</Link>
        <Link href="/agents-models/opencode">OpenCode</Link>
        <Link href="/integrations/ollama">Ollama connections</Link>
      </div>
      <p className="notice warning">
        Expected agent versions are operator configuration, not tested versions.
        Execution and compatibility remain unverified. Concurrency is limited to
        one in the initial design.
      </p>
      <ErrorNotice
        error={profiles.error || agents.error || connections.error}
      />
      <div className="panel-head">
        <h2>Model profiles</h2>
        <button disabled={!endpoints.length} onClick={() => setModel(null)}>
          + Model profile
        </button>
      </div>
      {!endpoints.length && (
        <p>
          Create an active Ollama connection first. Discover models there or
          enter the exact model identifier from your installation.
        </p>
      )}
      {profiles.isPending ? (
        <Loading />
      ) : (
        <div className="grid two">
          {profiles.data?.map((p) => (
            <section className="panel" key={p.id}>
              <div className="panel-head">
                <h3>{p.name}</h3>
                <Badge>{p.role}</Badge>
              </div>
              <p>{p.model}</p>
              <small>
                Temperature {p.temperature} ·{" "}
                {p.active ? "Active configuration" : "Disabled"}
              </small>
              <button onClick={() => setModel(p)}>Edit profile</button>
            </section>
          ))}
        </div>
      )}
      <div className="panel-head">
        <h2>Agent configurations</h2>
        <button disabled={!choices.length} onClick={() => setAgent(null)}>
          + Agent
        </button>
      </div>
      {!visible?.length ? (
        <Empty title="No agent configured">
          <p>
            Choose a model profile, executable location, timeout, and expected
            installed version.
          </p>
        </Empty>
      ) : (
        <div className="grid two">
          {visible.map((a) => (
            <section className="panel" key={a.id}>
              <div className="panel-head">
                <h3>{a.name}</h3>
                <Badge>{a.provider}</Badge>
              </div>
              <p>{a.executable}</p>
              <ul className="checklist">
                <li>
                  Expected version<span>{a.expected_agent_version}</span>
                </li>
                <li>
                  Tested version<Badge>Not tested</Badge>
                </li>
                <li>
                  Event contract
                  <span>
                    {a.capabilities.structured_events
                      ? "JSON events"
                      : "Opaque output"}
                  </span>
                </li>
                <li>
                  Timeout<span>{a.timeout_seconds}s</span>
                </li>
                <li>
                  Execution<Badge>Separate qualification required</Badge>
                </li>
              </ul>
              <ul>
                {a.capabilities.limitations.map((v) => (
                  <li key={v}>{v}</li>
                ))}
              </ul>
              <button onClick={() => setAgent(a)}>Edit agent</button>
            </section>
          ))}
        </div>
      )}
      {model !== undefined && (
        <Dialog
          title={model ? "Edit model profile" : "Create model profile"}
          close={() => setModel(undefined)}
        >
          <Form
            initial={{
              name: model?.name ?? "",
              connection_id: model?.connection_id ?? endpoints[0]?.id ?? "",
              model: model?.model ?? "",
              role: model?.role ?? "implementation",
              temperature: String(model?.temperature ?? 0.2),
              active: String(model?.active ?? true),
            }}
            fields={[
              { name: "name", label: "Profile name", required: true, max: 120 },
              {
                name: "connection_id",
                label: "Ollama connection",
                required: true,
                options: endpoints.map((c) => ({ value: c.id, label: c.name })),
              },
              {
                name: "model",
                label: "Exact model identifier",
                required: true,
                max: 256,
              },
              {
                name: "role",
                label: "Routing role",
                options: ["implementation", "verifier", "planning"].map(
                  (value) => ({ value, label: value }),
                ),
              },
              {
                name: "temperature",
                label: "Temperature (0–2)",
                type: "number",
                required: true,
              },
              {
                name: "active",
                label: "Configuration state",
                options: [
                  { value: "true", label: "Active" },
                  { value: "false", label: "Disabled" },
                ],
              },
            ]}
            submit={async (v) => {
              await write(
                model ? `/model-profiles/${model.id}` : "/model-profiles",
                {
                  ...v,
                  temperature: Number(v.temperature),
                  active: v.active === "true",
                  expected_version: model?.version ?? 0,
                },
                model ? "PUT" : "POST",
              );
              setModel(undefined);
              await client.invalidateQueries({ queryKey: ["model-profiles"] });
            }}
          />
        </Dialog>
      )}
      {agent !== undefined && (
        <Dialog
          title={agent ? "Edit agent" : "Create agent"}
          close={() => setAgent(undefined)}
        >
          <Form
            initial={{
              name: agent?.name ?? "",
              provider:
                agent?.provider ??
                (provider === "hermes" ? "hermes" : "opencode"),
              executable: agent?.executable ?? "/usr/local/bin/opencode",
              expected_agent_version: agent?.expected_agent_version ?? "",
              model_profile_id: agent?.model_profile_id ?? choices[0]?.id ?? "",
              timeout_seconds: String(agent?.timeout_seconds ?? 300),
              active: String(agent?.active ?? true),
            }}
            fields={[
              { name: "name", label: "Agent name", required: true, max: 120 },
              {
                name: "provider",
                label: "Provider",
                options: ["opencode", "hermes"].map((value) => ({
                  value,
                  label: value,
                })),
              },
              {
                name: "executable",
                label: "Absolute Linux executable path",
                required: true,
                help: "Root-owned installation; this path is stored, never executed by the API.",
              },
              {
                name: "expected_agent_version",
                label: "Expected installed version",
                required: true,
                max: 80,
              },
              {
                name: "model_profile_id",
                label: "Model profile",
                required: true,
                options: choices.map((p) => ({
                  value: p.id,
                  label: `${p.name} · ${p.role}`,
                })),
              },
              {
                name: "timeout_seconds",
                label: "Timeout (10–3600 seconds)",
                type: "number",
                required: true,
              },
              {
                name: "active",
                label: "Configuration state",
                options: [
                  { value: "true", label: "Active" },
                  { value: "false", label: "Disabled" },
                ],
              },
            ]}
            submit={async (v) => {
              await write(
                agent ? `/agents/${agent.id}` : "/agents",
                {
                  ...v,
                  timeout_seconds: Number(v.timeout_seconds),
                  active: v.active === "true",
                  expected_version: agent?.version ?? 0,
                },
                agent ? "PUT" : "POST",
              );
              setAgent(undefined);
              await client.invalidateQueries({ queryKey: ["agents"] });
            }}
          />
        </Dialog>
      )}
    </>
  );
}
