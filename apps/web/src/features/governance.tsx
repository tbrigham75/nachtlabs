"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, write, type Governance } from "@nachtlabs/api-client";
import {
  Action,
  Badge,
  Dialog,
  Empty,
  ErrorNotice,
  Form,
  Loading,
  type Field,
} from "@/components/ui";

type Kind = "mission" | "journey" | "holdout";
const field = (name: string, label: string, required = true): Field => ({
  name,
  label,
  required,
  type: "textarea",
});
const missionFields: Field[] = [
  field("purpose", "Project purpose"),
  field("intended_users", "Intended users"),
  field("outcomes", "Core product outcomes"),
  field("scope", "Approved scope and responsibilities"),
  field("non_goals", "Explicit non-goals"),
  field("technical_constraints", "Technical and architectural constraints"),
  field("security_constraints", "Security and privacy constraints"),
  field("reliability_requirements", "Reliability requirements", false),
  field("escalation", "Owner / escalation contact"),
  field("unacceptable_changes", "Unacceptable changes"),
  {
    name: "risk_tolerance",
    label: "Risk tolerance",
    options: ["low", "moderate", "high"].map((value) => ({
      value,
      label: value,
    })),
  },
];
const journeyFields: Field[] = [
  field("description", "Outcome this Journey validates"),
  {
    name: "category",
    label: "Category",
    options: [
      "critical_path",
      "regression",
      "security",
      "usability",
      "api",
      "integration",
    ].map((value) => ({ value, label: value.replaceAll("_", " ") })),
  },
  field("preconditions", "Preconditions", false),
  field("test_data", "Test data / setup", false),
  field("steps", "Steps"),
  field("expected_outcomes", "Expected outcomes"),
  field("evidence_requirements", "Required evidence"),
  {
    name: "execution_type",
    label: "Execution method",
    options: [
      "manual",
      "script",
      "api",
      "browser",
      "integration",
      "external",
    ].map((value) => ({ value, label: value })),
  },
  {
    name: "command_reference",
    label: "Approved command or adapter reference",
    help: "Required for automated methods. Configuration only; execution is unavailable.",
  },
  {
    name: "approval_role",
    label: "Required manual approver",
    options: ["operator", "admin", "owner"].map((value) => ({
      value,
      label: value,
    })),
  },
  {
    name: "required_on",
    label: "Required on (comma-separated workflows)",
    required: true,
  },
  {
    name: "timeout_seconds",
    label: "Timeout in seconds",
    type: "number",
    required: true,
  },
  {
    name: "enabled",
    label: "Enabled",
    options: [
      { value: "true", label: "Yes" },
      { value: "false", label: "No" },
    ],
  },
  { name: "owner", label: "Journey owner", required: true },
  {
    name: "source_reference",
    label: "Source manual test or historical run reference",
    help: "Record the procedure or prior evidence this scenario was derived from.",
  },
];
export function GovernanceScreen({
  projectId,
  kind,
  admin,
}: {
  projectId: string;
  kind: Kind;
  admin: boolean;
}) {
  const client = useQueryClient();
  const [editing, setEditing] = useState<Governance | null | undefined>();
  const [history, setHistory] = useState<Governance[]>();
  const path = `/projects/${projectId}/governance/${kind}`;
  const query = useQuery({
    queryKey: ["governance", projectId, kind],
    queryFn: () => api<Governance[]>(path),
    enabled: kind !== "holdout" || admin,
  });
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ["governance", projectId] });
    await client.invalidateQueries({ queryKey: ["project", projectId] });
  };
  if (kind === "holdout" && !admin)
    return (
      <ErrorNotice
        error={new Error("Protected validation requires Owner or Admin access")}
      />
    );
  return (
    <>
      <div className="panel-head">
        <div>
          <h2>
            {kind === "mission"
              ? "Project Mission"
              : kind === "holdout"
                ? "Protected holdout validation"
                : "Validation Journeys"}
          </h2>
          <p>
            {kind === "mission"
              ? "Versioned intent, boundaries, and required acceptance baseline."
              : kind === "holdout"
                ? "Definitions are encrypted separately and access is audited."
                : "Executable acceptance definitions. Execution is introduced in Milestone 7."}
          </p>
        </div>
        {admin && (kind !== "mission" || !query.data?.length) && (
          <button className="primary" onClick={() => setEditing(null)}>
            + {kind === "mission" ? "Draft Mission" : "Add scenario"}
          </button>
        )}
      </div>
      <ErrorNotice error={query.error} />
      {query.isPending ? (
        <Loading />
      ) : !query.data?.length ? (
        <Empty
          title={
            kind === "mission"
              ? "Define the project’s purpose"
              : "No scenarios yet"
          }
        >
          <p>
            {kind === "mission"
              ? "Create and approve a Journey before approving a Mission with that required baseline."
              : "Capture a meaningful manual procedure and its evidence requirements."}
          </p>
        </Empty>
      ) : (
        query.data.map((doc) => (
          <section className="panel" key={doc.id}>
            <div className="panel-head">
              <div>
                <h2>{doc.name}</h2>
                <small>
                  Version {doc.version} ·{" "}
                  {new Date(doc.created_at).toLocaleString()}
                </small>
              </div>
              <Badge good={doc.approved_version === doc.version}>
                {doc.approved_version === doc.version
                  ? "Approved"
                  : doc.approved_version
                    ? `Draft · v${doc.approved_version} active`
                    : "Draft"}
              </Badge>
            </div>
            <p className="prose">
              {String(doc.content.purpose ?? doc.content.description ?? "")}
            </p>
            <div className="actions" style={{ marginTop: 18 }}>
              {admin && (
                <button onClick={() => setEditing(doc)}>
                  Edit new version
                </button>
              )}
              {admin && doc.approved_version !== doc.version && (
                <Action
                  action={async () => {
                    await write(`${path}/${doc.id}/approve`, {
                      expected_version: doc.version,
                    });
                    await refresh();
                  }}
                >
                  Approve version {doc.version}
                </Action>
              )}
              <Action
                action={async () =>
                  setHistory(
                    await api<Governance[]>(`${path}/${doc.id}/history`),
                  )
                }
              >
                History & evidence
              </Action>
            </div>
            <details style={{ marginTop: 16 }}>
              <summary>Inspect definition</summary>
              <pre>{JSON.stringify(doc.content, null, 2)}</pre>
            </details>
          </section>
        ))
      )}
      {editing !== undefined && (
        <Dialog
          title={
            kind === "mission" ? "Mission editor" : "Validation scenario editor"
          }
          close={() => setEditing(undefined)}
        >
          <DocumentEditor
            projectId={projectId}
            kind={kind}
            doc={editing}
            save={async (body) => {
              await write(
                editing ? `${path}/${editing.id}` : path,
                body,
                editing ? "PUT" : "POST",
              );
              setEditing(undefined);
              await refresh();
            }}
          />
        </Dialog>
      )}
      {history && (
        <Dialog
          title="Immutable version history"
          close={() => setHistory(undefined)}
        >
          {history.map((v) => (
            <div className="history-item" key={v.version}>
              <h3>
                Version {v.version}{" "}
                <Badge good={!!v.approved_at}>
                  {v.approved_at ? "Human approved" : "Draft"}
                </Badge>
              </h3>
              <small>
                Author {v.author_id} · {new Date(v.created_at).toLocaleString()}
              </small>
              <details>
                <summary>Definition</summary>
                <pre>{JSON.stringify(v.content, null, 2)}</pre>
              </details>
            </div>
          ))}
        </Dialog>
      )}
    </>
  );
}
function DocumentEditor({
  projectId,
  kind,
  doc,
  save,
}: {
  projectId: string;
  kind: Kind;
  doc: Governance | null;
  save: (body: unknown) => Promise<void>;
}) {
  const [selected, setSelected] = useState<string[]>(
    (doc?.content.required_journey_ids as string[] | undefined) ?? [],
  );
  const journeys = useQuery({
    queryKey: ["governance", projectId, "journey"],
    queryFn: () =>
      api<Governance[]>(`/projects/${projectId}/governance/journey`),
    enabled: kind === "mission",
  });
  const defaults: Record<string, string> = {
    name: doc?.name ?? (kind === "mission" ? "Project Mission" : ""),
    risk_tolerance: "low",
    execution_type: "manual",
    category: "critical_path",
    approval_role: "operator",
    required_on: "standard",
    timeout_seconds: "300",
    enabled: "true",
  };
  Object.entries(doc?.content ?? {}).forEach(([key, value]) => {
    defaults[key] = Array.isArray(value)
      ? value.join(", ")
      : value === null
        ? ""
        : String(value);
  });
  return (
    <>
      <Form
        initial={defaults}
        fields={[
          { name: "name", label: "Name", required: true, max: 120 },
          ...(kind === "mission" ? missionFields : journeyFields),
        ]}
        label="Save new version"
        submit={async (values) => {
          const { name, ...content } = values;
          const body =
            kind === "mission"
              ? { ...content, required_journey_ids: selected }
              : {
                  ...content,
                  timeout_seconds: Number(content.timeout_seconds),
                  enabled: content.enabled === "true",
                  command_reference: content.command_reference || null,
                  required_on: content.required_on
                    .split(",")
                    .map((v) => v.trim())
                    .filter(Boolean),
                };
          await save({
            name,
            content: body,
            expected_version: doc?.version ?? 0,
          });
        }}
      >
        {kind === "mission" && (
          <fieldset>
            <legend>Required validation baseline</legend>
            <ErrorNotice error={journeys.error} />
            {journeys.data?.length ? (
              journeys.data.map((j) => (
                <div className="field-row" key={j.id}>
                  <input
                    id={`journey-${j.id}`}
                    type="checkbox"
                    checked={selected.includes(j.id)}
                    onChange={(e) =>
                      setSelected(
                        e.target.checked
                          ? [...selected, j.id]
                          : selected.filter((id) => id !== j.id),
                      )
                    }
                  />
                  <label htmlFor={`journey-${j.id}`}>
                    {j.name} ({j.approved_version ? "approved" : "draft"})
                  </label>
                </div>
              ))
            ) : (
              <p>
                Create a Journey first. You can save this Mission as a draft in
                the meantime.
              </p>
            )}
          </fieldset>
        )}
      </Form>
    </>
  );
}
