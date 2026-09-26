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
  const signedOut =
    me.isError && me.error instanceof ApiError && me.error.status === 401;
  useEffect(() => {
    if (!publicPage && signedOut) router.replace("/login");
    if (initialized === false && !signedInPath(path)) router.replace("/setup");
    if (initialized === true && path === "/setup") router.replace("/login");
    if (
      me.data?.mfa_required &&
      !["/mfa/setup", "/settings/security"].includes(path)
    )
      router.replace("/mfa/setup");
  }, [me.error, me.data, initialized, path, publicPage, router, signedOut]);
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
