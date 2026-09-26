"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, type Project, type User } from "@nachtlabs/api-client";
import { Badge, ErrorNotice, Heading, Loading } from "@/components/ui";
export function Overview({ user }: { user: User }) {
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api<Project[]>("/projects"),
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
        {["owner", "admin"].includes(user.role) && (
          <Link className="button primary" href="/projects/new">
            + Create project
          </Link>
        )}
      </Heading>
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
              <Link href="/integrations">
                Configure connections and agent profiles
              </Link>
              <Badge>Available</Badge>
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
