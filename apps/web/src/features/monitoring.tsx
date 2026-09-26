"use client";
import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, write, type User } from "@nachtlabs/api-client";
import {
  Action,
  Badge,
  Empty,
  ErrorNotice,
  Form,
  Heading,
  Loading,
} from "@/components/ui";
type Incident = {
  id: string;
  category: string;
  status: string;
  severity: string;
  occurrences: number;
  version: number;
  evidence_refs: string[];
  assigned_to: string | null;
  snoozed_until: string | null;
  timeline?: { time: string; actor: string; action: string; note: string }[];
};
export function MonitoringScreen({
  area,
  id,
  user,
}: {
  area: string;
  id?: string;
  user: User;
}) {
  if (area === "incidents" && id) return <IncidentDetail id={id} user={user} />;
  if (area === "notifications")
    return (
      <>
        <Heading title="Notifications" />
        <Notifications />
      </>
    );
  if (area === "recommendations") return <Recommendations />;
  if (area === "logs")
    return <Logs admin={["owner", "admin"].includes(user.role)} />;
  if (area === "retention") return <Retention />;
  return <Dashboard area={area} user={user} />;
}
function Dashboard({ area, user }: { area: string; user: User }) {
  const query = useQuery({
    queryKey: ["monitoring"],
    queryFn: () =>
      api<{ states: Record<string, number>; incidents: Incident[] }>(
        "/monitoring",
      ),
    refetchInterval: 30000,
  });
  const incidents = useQuery({
    queryKey: ["incidents"],
    queryFn: () => api<Incident[]>("/incidents"),
    refetchInterval: 30000,
  });
  const control = useQuery({
    queryKey: ["factory-control"],
    queryFn: () =>
      api<{ version: number; emergency_stop: boolean }>("/factory-control"),
    enabled: ["owner", "admin"].includes(user.role),
  });
  const client = useQueryClient();
  return (
    <>
      <Heading
        title={area === "incidents" ? "Incidents" : "Monitoring"}
        note="Durable run states and deduplicated incidents. Scheduled regressions remain disabled."
      />
      <nav className="tabs">
        <Link href="/monitoring">Overview</Link>
        <Link href="/logs">Logs</Link>
        <Link href="/incidents">Incidents</Link>
        {["owner", "admin"].includes(user.role) && (
          <>
            <Link href="/recommendations">Recommendations</Link>
            <Link href="/retention">Retention</Link>
          </>
        )}
      </nav>
      <ErrorNotice error={query.error || incidents.error || control.error} />
      {area !== "incidents" && (
        <div className="grid two">
          {Object.entries(query.data?.states ?? {}).map(([state, count]) => (
            <section className="panel" key={state}>
              <h2>{count}</h2>
              <p>{state.replaceAll("_", " ")}</p>
            </section>
          ))}
        </div>
      )}
      {control.data && (
        <section className="panel">
          <h2>Factory control</h2>
          <Badge>
            {control.data.emergency_stop
              ? "Emergency stop active"
              : "Intake enabled"}
          </Badge>
          <Action
            danger={!control.data.emergency_stop}
            action={async () => {
              await write(
                "/factory-control",
                {
                  expected_version: control.data!.version,
                  emergency_stop: !control.data!.emergency_stop,
                },
                "PUT",
              );
              await client.invalidateQueries({ queryKey: ["factory-control"] });
            }}
          >
            {control.data.emergency_stop
              ? "Release emergency stop"
              : "Stop factory execution"}
          </Action>
          <p>Releasing the stop does not restart cancelled runs.</p>
        </section>
      )}
      {!incidents.data?.length ? (
        <Empty title="No incidents recorded" />
      ) : (
        <section className="panel table-wrap">
          <table>
            <thead>
              <tr>
                <th>Incident</th>
                <th>Status</th>
                <th>Occurrences</th>
              </tr>
            </thead>
            <tbody>
              {incidents.data.map((v) => (
                <tr key={v.id}>
                  <td>
                    <Link href={"/incidents/" + v.id}>
                      {v.category.replaceAll("_", " ")}
                    </Link>
                  </td>
                  <td>
                    <Badge>{v.status}</Badge>
                  </td>
                  <td>{v.occurrences}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}
function IncidentDetail({ id, user }: { id: string; user: User }) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["incident", id],
    queryFn: () => api<Incident>("/incidents/" + id),
  });
  if (query.isPending) return <Loading />;
  if (query.error) return <ErrorNotice error={query.error} />;
  const value = query.data!;
  return (
    <>
      <Heading
        title={value.category.replaceAll("_", " ")}
        note={value.status}
      />
      <section className="panel">
        <h2>Evidence references</h2>
        {value.evidence_refs.map((v) => (
          <p key={v}>
            {v.startsWith("probe:") ? (
              <Link href="/integrations">{v}</Link>
            ) : (
              <Link href={"/runs/" + v.split(":")[0]}>{v}</Link>
            )}
          </p>
        ))}
        {["owner", "admin"].includes(user.role) && (
          <Form
            key={value.version}
            initial={{ action: "acknowledge", snooze_hours: "1" }}
            fields={[
              {
                name: "action",
                label: "Action",
                options: [
                  "acknowledge",
                  "resolve",
                  "reopen",
                  "assign",
                  "snooze",
                  "note",
                ].map((v) => ({ value: v, label: v })),
              },
              {
                name: "note",
                label: "Investigation note",
                type: "textarea",
                required: true,
                min: 3,
                max: 2000,
              },
              {
                name: "assigned_to",
                label: "Assignee user ID",
                help: "For assignment: an active Owner or Admin ID. Leave blank to clear assignment.",
              },
              { name: "snooze_hours", label: "Snooze hours", type: "number" },
            ]}
            submit={async (v) => {
              await write(`/incidents/${id}/actions`, {
                ...v,
                assigned_to: v.assigned_to || null,
                snooze_hours: Number(v.snooze_hours),
                version: value.version,
              });
              await client.invalidateQueries({ queryKey: ["incident", id] });
            }}
          />
        )}
        <h2>Timeline</h2>
        <ol>
          {value.timeline?.map((v, i) => (
            <li key={i}>
              <strong>{v.action}</strong>
              <p>{v.note}</p>
              <small>
                {v.time} · {v.actor}
              </small>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}
export function Notifications() {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["notifications"],
    queryFn: () =>
      api<
        { id: string; incident_id: string; category: string; read: boolean }[]
      >("/notifications"),
    refetchInterval: 30000,
  });
  return (
    <>
      <ErrorNotice error={query.error} />
      {query.isPending ? (
        <Loading />
      ) : !query.data?.length ? (
        <Empty title="No notifications" />
      ) : (
        <ul className="checklist">
          {query.data.map((v) => (
            <li key={v.id}>
              <Link href={"/incidents/" + v.incident_id}>
                {v.category.replaceAll("_", " ")}
              </Link>
              {v.read ? (
                <Badge>Read</Badge>
              ) : (
                <Action
                  action={async () => {
                    await write("/notifications/" + v.id + "/read");
                    await client.invalidateQueries({
                      queryKey: ["notifications"],
                    });
                  }}
                >
                  Mark read
                </Action>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
function Recommendations() {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["recommendations"],
    queryFn: () =>
      api<
        {
          id: string;
          status: string;
          version: number;
          digest: string;
          proposal: unknown;
        }[]
      >("/recommendations"),
  });
  return (
    <>
      <Heading
        title="Recommendations"
        note="Review the proposed change, approve it, then apply it. Changed policies invalidate the recommendation."
      />
      <ErrorNotice error={query.error} />
      {!query.data?.length && (
        <Empty title="No deterministic recommendations available" />
      )}
      {query.data?.map((v) => (
        <section className="panel" key={v.id}>
          <Badge>{v.status}</Badge>
          <pre>{JSON.stringify(v.proposal, null, 2)}</pre>
          {["new", "approved", "applied"].includes(v.status) && (
            <Form
              key={v.version}
              label="Record action"
              fields={[
                {
                  name: "action",
                  label: "Action",
                  options: (v.status === "new"
                    ? ["approve", "reject"]
                    : v.status === "approved"
                      ? ["apply", "reject"]
                      : ["rollback"]
                  ).map((action) => ({ value: action, label: action })),
                },
                {
                  name: "reason",
                  label: "Reason",
                  type: "textarea",
                  required: true,
                  min: 3,
                  max: 2000,
                },
              ]}
              submit={async (body) => {
                await write(`/recommendations/${v.id}/actions`, {
                  ...body,
                  version: v.version,
                  digest: v.digest,
                });
                await client.invalidateQueries({
                  queryKey: ["recommendations"],
                });
              }}
            />
          )}
        </section>
      ))}
    </>
  );
}
function Logs({ admin }: { admin: boolean }) {
  const [system, setSystem] = useState(false);
  const [filters, setFilters] = useState({
    severity: "",
    stage: "",
    project_id: "",
  });
  const [before, setBefore] = useState("");
  const queryString = new URLSearchParams(
    Object.entries({ ...filters, before }).filter(([, v]) => !!v),
  ).toString();
  const query = useQuery({
    queryKey: ["logs", system, queryString],
    queryFn: () =>
      api<
        {
          id: string;
          run_id: string;
          time: string;
          category: string;
          severity: string;
          stage: string;
          details: unknown;
        }[]
      >((system ? "/system-logs?" : "/logs?") + queryString),
  });
  const searches = useQuery({
    queryKey: ["saved-searches"],
    queryFn: () =>
      api<
        {
          id: string;
          name: string;
          filters: {
            severity: string | null;
            stage: string;
            project_id: string | null;
          };
        }[]
      >("/saved-searches"),
  });
  const client = useQueryClient();
  return (
    <>
      <Heading
        title="Operational logs"
        note="Structured run events. Raw agent output and protected holdout content are excluded."
      />
      <section className="panel">
        {admin && (
          <nav className="tabs">
            <button
              onClick={() => {
                setSystem(false);
                setBefore("");
              }}
            >
              Run events
            </button>
            <button
              onClick={() => {
                setSystem(true);
                setBefore("");
              }}
            >
              System events
            </button>
          </nav>
        )}
        <Form
          initial={filters}
          fields={[
            {
              name: "severity",
              label: "Severity",
              options: ["", "info", "warning", "error"].map((v) => ({
                value: v,
                label: v || "All",
              })),
            },
            { name: "stage", label: "Stage" },
            { name: "project_id", label: "Project ID" },
          ]}
          label="Filter events"
          submit={async (v) => {
            setFilters({
              severity: v.severity,
              stage: v.stage,
              project_id: v.project_id,
            });
            setBefore("");
          }}
        />
        <div className="tabs">
          {searches.data?.map((v) => (
            <button
              key={v.id}
              onClick={() => {
                setFilters({
                  severity: v.filters.severity || "",
                  stage: v.filters.stage || "",
                  project_id: v.filters.project_id || "",
                });
                setBefore("");
              }}
            >
              {v.name}
            </button>
          ))}
        </div>
        <Form
          fields={[
            {
              name: "name",
              label: "Save current filter as",
              required: true,
              max: 120,
            },
          ]}
          label="Save search"
          submit={async (v) => {
            await write("/saved-searches", {
              name: v.name,
              ...filters,
              severity: filters.severity || null,
              project_id: filters.project_id || null,
              shared: false,
            });
            await client.invalidateQueries({ queryKey: ["saved-searches"] });
          }}
        />
      </section>
      <ErrorNotice error={query.error || searches.error} />
      <section className="panel table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Event</th>
              <th>Stage</th>
              <th>Severity</th>
            </tr>
          </thead>
          <tbody>
            {query.data?.map((v) => (
              <tr key={v.id}>
                <td>{v.time}</td>
                <td>
                  {v.run_id ? (
                    <Link href={"/runs/" + v.run_id}>{v.category}</Link>
                  ) : (
                    v.category
                  )}
                  <details>
                    <summary>Safe event details</summary>
                    <pre>{JSON.stringify(v.details, null, 2)}</pre>
                  </details>
                </td>
                <td>{v.stage}</td>
                <td>{v.severity}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!!query.data?.length && (
          <button
            onClick={() => setBefore(query.data![query.data!.length - 1].time)}
          >
            Older events
          </button>
        )}
      </section>
    </>
  );
}
function Retention() {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["retention"],
    queryFn: () =>
      api<{
        version: number;
        log_days: number;
        artifact_days: number;
        protected_history: string;
      }>("/retention"),
  });
  return (
    <>
      <Heading
        title="Retention policy"
        note="Evidence and audit history remain immutable. Disposable executor workspaces are removed after each command."
      />
      <ErrorNotice error={query.error} />
      {query.data && (
        <section className="panel">
          <p>{query.data.protected_history}</p>
          <Form
            key={query.data.version}
            initial={{
              log_days: String(query.data.log_days),
              artifact_days: String(query.data.artifact_days),
            }}
            fields={[
              {
                name: "log_days",
                label: "Operational log window (7–365 days)",
                type: "number",
                required: true,
              },
              {
                name: "artifact_days",
                label: "Unreferenced artifact retention (30–3650 days)",
                type: "number",
                required: true,
              },
            ]}
            submit={async (v) => {
              await write(
                "/retention",
                {
                  version: query.data!.version,
                  log_days: Number(v.log_days),
                  artifact_days: Number(v.artifact_days),
                },
                "PUT",
              );
              await client.invalidateQueries({ queryKey: ["retention"] });
            }}
          />
        </section>
      )}
    </>
  );
}
