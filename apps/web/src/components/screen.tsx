"use client";
import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError, type User } from "@nachtlabs/api-client";
import { AuthScreen } from "@/features/auth";
import { Overview } from "@/features/overview";
import { Projects, ProjectScreen } from "@/features/projects";
import { SettingsScreen } from "@/features/settings";
import { KeysScreen } from "@/features/keys";
import { AuditScreen } from "@/features/audit";
import { IntegrationsScreen } from "@/features/integrations";
import { AgentsModelsScreen } from "@/features/agents-models";
import { LlmSetupScreen } from "@/features/llm-setup";
import { FactoryScreen } from "@/features/factory";
import { MonitoringScreen } from "@/features/monitoring";
import { Shell } from "./shell";
import { Empty, ErrorNotice, Loading } from "./ui";
const publicPaths = [
  "/login",
  "/setup",
  "/forgot-password",
  "/reset-password",
  "/accept-invitation",
  "/mfa/verify",
];
// Password reset and invitation links are unusable until an account exists, so
// they must not compete with Owner setup.
function signedInPath(path: string) {
  return path === "/setup" || path === "/mfa/verify";
}
/**
 * Resolve exactly one redirect destination.
 *
 * Returning a single target is the point: two router.replace calls in one
 * effect let /login and /setup race, and on a slow API that race could land a
 * first-time operator on a sign-in form they cannot use. Priority is ordered
 * so the most specific, most safety-relevant answer wins, and an unknown setup
 * status never produces a redirect at all.
 */
function destination(input: {
  path: string;
  publicPage: boolean;
  signedOut: boolean;
  initialized: boolean | undefined;
  setupUnreachable: boolean;
  mfaRequired: boolean;
}): string | null {
  const {
    path,
    publicPage,
    signedOut,
    initialized,
    setupUnreachable,
    mfaRequired,
  } = input;
  // An unreadable setup status must not be treated as "no account exists", and
  // must not push a signed-in operator out of the application either.
  if (setupUnreachable) return null;
  if (mfaRequired && !["/mfa/setup", "/settings/security"].includes(path))
    return "/mfa/setup";
  // Fail-safe direction only. This fires on a positive "no account exists", so a
  // wrong or missing answer leaves the operator where they are rather than
  // stranding them. The dangerous direction is the opposite one, a wrongly
  // reported "true", so the sign-in page keeps the setup link permanently and
  // /setup always explains itself. Nothing here can make registration
  // unreachable.
  if (initialized === false && !signedInPath(path)) return "/setup";
  // Deliberately no "/setup" -> "/login" redirect. Bouncing a visitor off the
  // setup page looked like a broken refresh and hid the reason they could not
  // register. /setup now always explains itself, and creating an account is
  // still refused server-side with 409 setup_closed.
  if (!publicPage && signedOut) return "/login";
  return null;
}
export function Screen() {
  const path = usePathname();
  const router = useRouter();
  const publicPage = publicPaths.includes(path);
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<User>("/auth/me"),
    enabled: !publicPage,
    refetchOnWindowFocus: true,
  });
  // An installation with no account yet has to offer Owner setup before it can
  // offer sign-in, otherwise a first-time operator is asked to log in to an
  // installation nobody has registered on. This is also the only way the
  // interface can tell "no account exists" from "the API is unreachable" -- if
  // setup-status cannot be read we must say so rather than quietly showing a
  // sign-in form that cannot work.
  const setup = useQuery({
    queryKey: ["setup-status"],
    queryFn: () => api<{ initialized: boolean }>("/auth/setup-status"),
    enabled: publicPage || me.isError,
    staleTime: 30_000,
    retry: 1,
    refetchOnWindowFocus: true,
  });
  const initialized = setup.data?.initialized;
  const setupUnreachable = setup.isError;
  const signedOut = me.error instanceof ApiError && me.error.status === 401;
  const mfaRequired = me.data?.mfa_required === true;
  const target = destination({
    path,
    publicPage,
    signedOut,
    initialized,
    setupUnreachable,
    mfaRequired,
  });
  useEffect(() => {
    if (target) router.replace(target);
  }, [router, target]);
  if (publicPage)
    return (
      <AuthScreen
        key={path}
        path={path}
        initialized={initialized}
        checkingSetup={setup.isPending}
        setupUnreachable={setupUnreachable}
        retrySetup={() => void setup.refetch()}
      />
    );
  if (me.isPending) return <Loading />;
  // With the API unreachable the operator must be told that, not shown a bare
  // error box for a sign-in they cannot complete.
  if (setupUnreachable && !me.data)
    return (
      <AuthScreen
        key="unreachable"
        path="/login"
        initialized={undefined}
        checkingSetup={false}
        setupUnreachable
        retrySetup={() => void setup.refetch()}
      />
    );
  if (me.error) return <ErrorNotice error={me.error} />;
  if (!me.data) return null;
  const user = me.data;
  const parts = path.split("/").filter(Boolean);
  let content: React.ReactNode;
  if (path === "/overview") content = <Overview user={user} />;
  else if (path === "/projects" || path === "/projects/new")
    content = <Projects user={user} create={path.endsWith("/new")} />;
  else if (parts[0] === "projects" && parts[1])
    content = (
      <ProjectScreen key={parts[1]} id={parts[1]} tab={parts[2]} user={user} />
    );
  else if (parts[0] === "settings" || path === "/mfa/setup")
    content = (
      <SettingsScreen
        user={user}
        tab={path === "/mfa/setup" ? "security" : (parts[1] ?? "general")}
      />
    );
  else if (path === "/api-keys") content = <KeysScreen user={user} />;
  else if (path === "/audit-log") content = <AuditScreen />;
  else if (parts[0] === "integrations")
    content = <IntegrationsScreen user={user} provider={parts[1]} />;
  else if (parts[0] === "agents-models")
    content = <AgentsModelsScreen user={user} provider={parts[1]} />;
  else if (parts[0] === "llm-setup") content = <LlmSetupScreen user={user} />;
  else if (
    ["work-requests", "runs", "workflows", "regressions"].includes(parts[0])
  )
    content = <FactoryScreen area={parts[0]} id={parts[1]} user={user} />;
  else if (
    [
      "monitoring",
      "incidents",
      "logs",
      "recommendations",
      "notifications",
      "retention",
    ].includes(parts[0])
  )
    content = <MonitoringScreen area={parts[0]} id={parts[1]} user={user} />;
  else content = <Empty title="Page not found" />;
  return <Shell user={user}>{content}</Shell>;
}
