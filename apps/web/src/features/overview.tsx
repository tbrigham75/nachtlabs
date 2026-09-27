"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  type LlmReadiness,
  type Project,
  type User,
} from "@nachtlabs/api-client";
import { Badge, ErrorNotice, Heading, Loading } from "@/components/ui";
export function Overview({ user }: { user: User }) {
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api<Project[]>("/projects"),
  });
  const admin = ["owner", "admin"].includes(user.role);
  const llm = useQuery({
    queryKey: ["llm-readiness"],
    queryFn: () => api<LlmReadiness>("/llm-readiness"),
    enabled: admin,
  });
  const status = useQuery({
    queryKey: ["overview"],
    queryFn: () =>
      api<{ worker: string; worker_last_seen: string | null }>("/overview"),
  });
  if (projects.isPending) return <Loading />;
  return (
    <>
      <Heading
        title="Engineering overview"
        note="Establish your projects, define their boundaries, and make the acceptance criteria explicit."
      >
        {admin && (
          <Link className="button primary" href="/projects/new">
            + Create project
          </Link>
        )}
      </Heading>
      {/*
        The first-login prompt. Deliberately a panel rather than a redirect: this
        installation may be mid-configuration for a legitimate reason, and the
        app elsewhere refuses to move an operator out from under a click.
      */}
      {admin && llm.data && !llm.data.complete && (
        <section className="panel" aria-labelledby="llm-callout">
          <div className="panel-head">
            <h2 id="llm-callout">Finish setting up your LLM</h2>
            <Badge>Next step</Badge>
          </div>
          <p>
            {llm.data.complete
              ? ""
              : !llm.data.connection?.active
                ? "No model endpoint is configured. The wizard walks the order the API enforces: endpoint, connection check, distinct implementation and verification models, then a coding agent."
                : llm.data.discovery.state !== "succeeded"
                  ? `A model endpoint is saved but no current connection check has succeeded (${llm.data.discovery.state.replace("_", " ")}).`
                  : !llm.data.distinct_models
                    ? "Implementation and verification must use different model identifiers."
                    : "A coding agent still needs to be bound to a model profile."}
          </p>
          {!llm.data.provider_network_enabled && (
            <p className="notice warning">
              Provider checks are disabled by installation policy. You can still
              store configuration, but the connection check will stay blocked
              until an operator enables{" "}
              <code>NACHTLABS_INTEGRATION_NETWORK_ENABLED</code> and restarts
              the API and worker.
            </p>
          )}
          <Link className="button primary" href="/llm-setup">
            Open the setup wizard
          </Link>
        </section>
      )}
      <ErrorNotice error={projects.error || status.error} />
      <div className="grid">
        <section className="panel stat">
          <p>Authorized projects</p>
          <strong>{projects.data?.length ?? "—"}</strong>
          <small>Projects visible to your identity</small>
        </section>
        <section className="panel stat">
          <p>Foundation worker</p>
          <strong>
            {status.data?.worker === "online" ? "Online" : "Unavailable"}
          </strong>
          <small>
            {status.data?.worker_last_seen
              ? `Last heartbeat ${new Date(status.data.worker_last_seen).toLocaleTimeString()}`
              : "No recent heartbeat recorded"}
          </small>
        </section>
        <section className="panel stat">
          <p>Agent execution</p>
          <strong>Not enabled</strong>
          <small>Available after the execution milestone</small>
        </section>
      </div>
      <div className="grid two">
        <section className="panel">
          <div className="panel-head">
            <h2>Installation checklist</h2>
            <Badge>Foundation</Badge>
          </div>
          <ul className="checklist">
            <li>
              <span>Owner account initialized</span>
              <Badge good>Configured</Badge>
            </li>
            <li>
              <Link href="/settings/security">
                Protect your account with MFA
              </Link>
              <Badge good={user.mfa_enabled}>
                {user.mfa_enabled ? "Enrolled" : "Action available"}
              </Badge>
            </li>
            <li>
              <Link href="/projects">Create your first project</Link>
              <Badge good={!!projects.data?.length}>
                {projects.data?.length ? "Created" : "Next step"}
              </Badge>
            </li>
            <li>
              {/*
                Replaced a static "Available" badge with the real derived state.
                A link that is always there but says honestly what is missing
                is better than one that disappears when a flag is wrong.
              */}
              <Link href="/llm-setup">
                {llm.data?.complete
                  ? "Model and agent configuration"
                  : "Set up your LLM"}
              </Link>
              {llm.data ? (
                <Badge good={llm.data.complete}>
                  {llm.data.complete ? "Configured" : "Action available"}
                </Badge>
              ) : (
                <Badge>Checking</Badge>
              )}
            </li>
          </ul>
        </section>
        <section className="panel">
          <div className="panel-head">
            <h2>Governance comes first</h2>
            <Badge good>Human controlled</Badge>
          </div>
          <p>
            Each project starts with required plan approval and PR-only
            delivery. Define an approved Validation Journey, then include it in
            the project Mission’s baseline.
          </p>
          <div className="notice" style={{ marginTop: 20 }}>
            This checkpoint does not run agents or create commits. No workflow
            outcomes or integration health are simulated.
          </div>
          <Link href="/audit-log">Inspect recorded activity →</Link>
        </section>
      </div>
    </>
  );
}
