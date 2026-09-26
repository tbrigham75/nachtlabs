"use client";
import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, write, type Theme, type User } from "@nachtlabs/api-client";
import {
  Action,
  Badge,
  ErrorNotice,
  Form,
  Heading,
  Loading,
  SecretNotice,
} from "@/components/ui";
const themes: { id: Theme; name: string; note: string }[] = [
  {
    id: "midnight",
    name: "Midnight Operations",
    note: "Deep slate with cool blue actions",
  },
  {
    id: "graphite",
    name: "Graphite",
    note: "Neutral surfaces for focused work",
  },
  {
    id: "canvas",
    name: "Light Canvas",
    note: "Warm white and disciplined blue",
  },
  {
    id: "forest",
    name: "Forest Terminal",
    note: "Muted greens on deep charcoal",
  },
  {
    id: "nordic",
    name: "Nordic Frost",
    note: "Cool, clean blue-gray surfaces",
  },
  {
    id: "solarized",
    name: "Solarized Workshop",
    note: "Low-glare warmth and balanced accents",
  },
];
export function SettingsScreen({ user, tab }: { user: User; tab: string }) {
  const admin = ["owner", "admin"].includes(user.role);
  return (
    <>
      <Heading
        title="Settings"
        note="Manage identity, access, and your operating environment."
      />
      <div className="tabs">
        <Link href="/settings" className={tab === "general" ? "active" : ""}>
          Organization
        </Link>
        <Link
          href="/settings/themes"
          className={tab === "themes" ? "active" : ""}
        >
          Appearance
        </Link>
        <Link
          href="/settings/security"
          className={tab === "security" ? "active" : ""}
        >
          Security
        </Link>
        {admin && (
          <>
            <Link href="/integrations">Integrations</Link>
            <Link href="/agents-models">Agents & models</Link>
          </>
        )}
        {admin && (
          <Link
            href="/settings/users"
            className={tab === "users" ? "active" : ""}
          >
            Users & access
          </Link>
        )}
      </div>
      {tab === "themes" ? (
        <Themes user={user} />
      ) : tab === "security" ? (
        <Security user={user} />
      ) : tab === "users" && admin ? (
        <Users actor={user} />
      ) : tab === "general" ? (
        <Organization user={user} />
      ) : (
        <p className="notice">
          This setting is introduced in a later milestone.
        </p>
      )}
    </>
  );
}
function Themes({ user }: { user: User }) {
  const client = useQueryClient();
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const apply = async (theme: Theme) => {
    setBusy(true);
    try {
      await write("/auth/preferences", { theme }, "PUT");
      await client.invalidateQueries({ queryKey: ["me"] });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <div className="panel-head">
        <h2>Choose your workspace</h2>
        <Action action={() => apply("system")}>
          Follow system {user.theme === "system" ? "✓" : ""}
        </Action>
      </div>
      <ErrorNotice error={error} />
      <div className="grid">
        {themes.map((t) => (
          <button
            disabled={busy}
            className="theme-card"
            key={t.id}
            aria-pressed={user.theme === t.id}
            onClick={() => apply(t.id)}
          >
            <span className="theme-preview" data-theme={t.id}>
              <aside />
              <div>
                <i />
                <i />
                <i />
              </div>
            </span>
            <span className="panel-head" style={{ marginBottom: 4 }}>
              <strong>{t.name}</strong>
              {user.theme === t.id && <Badge good>Selected</Badge>}
            </span>
            <small>{t.note}</small>
          </button>
        ))}
      </div>
    </>
  );
}
function Security({ user }: { user: User }) {
  const client = useQueryClient();
  const [enrollment, setEnrollment] = useState<{
    secret: string;
    uri: string;
  }>();
  const [codes, setCodes] = useState<string>();
  const [confirmed, setConfirmed] = useState(false);
  return (
    <div className="grid two">
      <section className="panel">
        <div className="panel-head">
          <h2>Multi-factor authentication</h2>
          <Badge good={user.mfa_enabled}>
            {user.mfa_enabled ? "Enrolled" : "Not enrolled"}
          </Badge>
        </div>
        {user.mfa_required && (
          <p className="notice warning">
            Your organization requires MFA before you can continue.
          </p>
        )}
        <p>
          Use a TOTP authenticator. Recovery codes are single-use and displayed
          once.
        </p>
        {!user.mfa_enabled && !enrollment && (
          <Action
            action={async () =>
              setEnrollment(
                await write<{ secret: string; uri: string }>(
                  "/auth/mfa/enroll",
                ),
              )
            }
          >
            Start enrollment
          </Action>
        )}
        {enrollment && (
          <>
            <div className="notice warning">
              <h3>Authenticator setup key</h3>
              <pre>{enrollment.secret}</pre>
              <small>
                Enter this key manually into your authenticator app. Time-based,
                six digits, 30-second interval.
              </small>
              <details>
                <summary>Provisioning URI</summary>
                <pre>{enrollment.uri}</pre>
              </details>
            </div>
            <Form
              fields={[
                {
                  name: "code",
                  label: "Current authenticator code",
                  required: true,
                },
              ]}
              label="Enable MFA"
              submit={async (v) => {
                const result = await write<{ recovery_codes: string[] }>(
                  "/auth/mfa/confirm",
                  v,
                );
                setCodes(result.recovery_codes.join("\n"));
                setEnrollment(undefined);
                await client.invalidateQueries({ queryKey: ["me"] });
              }}
            />
          </>
        )}
        {codes && (
          <SecretNotice value={codes} dismiss={() => setCodes(undefined)} />
        )}{" "}
        {user.mfa_enabled && (
          <Action
            danger
            action={async () => {
              if (
                !window.confirm(
                  "Disable MFA for your account? Organization policy may prevent this.",
                )
              )
                return;
              await write("/auth/mfa/disable");
              await client.invalidateQueries({ queryKey: ["me"] });
            }}
          >
            Disable MFA
          </Action>
        )}
      </section>
      <section className="panel">
        <h2>Confirm sensitive changes</h2>
        <p>
          Administrative actions require authentication within the last ten
          minutes. Reconfirm here, then retry your action.
        </p>
        {confirmed && (
          <p className="notice success" role="status">
            Identity confirmed for ten minutes.
          </p>
        )}
        <Form
          fields={[
            {
              name: "password",
              label: "Current password",
              type: "password",
              required: true,
            },
            {
              name: "code",
              label: "Fresh MFA or recovery code",
              type: "password",
              help: "Required when MFA is enabled.",
            },
          ]}
          label="Confirm identity"
          submit={async (v) => {
            await write("/auth/reauthenticate", {
              password: v.password,
              code: v.code || null,
            });
            setConfirmed(true);
            await client.invalidateQueries({ queryKey: ["me"] });
          }}
        />
      </section>
    </div>
  );
}
function Organization({ user }: { user: User }) {
  const admin = ["owner", "admin"].includes(user.role);
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["organization"],
    queryFn: () =>
      api<{ name: string; require_admin_mfa: boolean; version: number }>(
        "/organization",
      ),
    enabled: admin,
  });
  if (!admin)
    return (
      <section className="panel">
        <h2>{user.organization}</h2>
        <p>
          Signed in as {user.name} with the {user.role} role. Organization
          changes require an Owner or Admin.
        </p>
      </section>
    );
  if (query.isPending) return <Loading />;
  if (query.error) return <ErrorNotice error={query.error} />;
  const org = query.data!;
  return (
    <section className="panel">
      <h2>Organization policy</h2>
      <Form
        key={org.version}
        initial={{
          name: org.name,
          require_admin_mfa: String(org.require_admin_mfa),
        }}
        fields={[
          {
            name: "name",
            label: "Organization name",
            required: true,
            max: 120,
          },
          {
            name: "require_admin_mfa",
            label: "Require MFA for Owners and Admins",
            options: [
              { value: "false", label: "Optional" },
              { value: "true", label: "Required" },
            ],
            help: "Only an Owner can change this policy. Enroll your own MFA first.",
          },
        ]}
        submit={async (v) => {
          await write(
            "/organization",
            {
              name: v.name,
              require_admin_mfa: v.require_admin_mfa === "true",
              version: org.version,
            },
            "PUT",
          );
          await client.invalidateQueries({ queryKey: ["organization"] });
          await client.invalidateQueries({ queryKey: ["me"] });
        }}
      />
      <div className="notice" style={{ marginTop: 24 }}>
        Delivery remains PR-only with required plan approval. Agent execution
        and scheduling remain unavailable. Configure connections under
        Integrations; provider checks require installation-level network
        permission.
      </div>
    </section>
  );
}
function Users({ actor }: { actor: User }) {
  const client = useQueryClient();
  const [sent, setSent] = useState(false);
  const query = useQuery({
    queryKey: ["users"],
    queryFn: () => api<User[]>("/users"),
  });
  const roleOptions = ["admin", "operator", "contributor", "viewer"].map(
    (value) => ({ value, label: value }),
  );
  return (
    <>
      <section className="panel">
        <h2>Invite a colleague</h2>
        {sent && (
          <p className="notice success" role="status">
            Invitation queued for email delivery.
          </p>
        )}
        <Form
          fields={[
            {
              name: "email",
              label: "Email address",
              type: "email",
              required: true,
            },
            { name: "role", label: "Organization role", options: roleOptions },
          ]}
          initial={{ role: "viewer" }}
          label="Send invitation"
          submit={async (v) => {
            await write("/invitations", v);
            setSent(true);
          }}
        />
      </section>
      <ErrorNotice error={query.error} />
      {query.isPending ? (
        <Loading />
      ) : (
        <div className="grid two">
          {query.data?.map((u) => (
            <section className="panel" key={`${u.id}-${u.version}`}>
              <div className="panel-head">
                <h2>{u.name}</h2>
                <Badge good={u.active}>
                  {u.active ? "Active" : "Disabled"}
                </Badge>
              </div>
              <p>{u.email}</p>
              <small>MFA {u.mfa_enabled ? "enrolled" : "not enrolled"}</small>
              <Form
                initial={{ role: u.role, active: String(u.active) }}
                fields={[
                  {
                    name: "role",
                    label: "Role",
                    options: [
                      ...(actor.role === "owner" || u.role === "owner"
                        ? [{ value: "owner", label: "owner" }]
                        : []),
                      ...roleOptions,
                    ],
                  },
                  {
                    name: "active",
                    label: "Account access",
                    options: [
                      { value: "true", label: "Active" },
                      { value: "false", label: "Disabled" },
                    ],
                  },
                ]}
                label="Update access"
                submit={async (v) => {
                  if (
                    (u.role === "owner" ||
                      v.role === "owner" ||
                      v.active === "false") &&
                    window.prompt(
                      `Type ${u.email} to confirm this access change`,
                    ) !== u.email
                  )
                    return;
                  await write(
                    `/users/${u.id}`,
                    {
                      role: v.role,
                      active: v.active === "true",
                      version: u.version,
                    },
                    "PATCH",
                  );
                  await client.invalidateQueries({ queryKey: ["users"] });
                  await client.invalidateQueries({ queryKey: ["me"] });
                }}
              />
            </section>
          ))}
        </div>
      )}
    </>
  );
}
