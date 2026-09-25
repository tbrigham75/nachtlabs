"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, FolderGit2, ShieldCheck, KeyRound, Settings, Menu, Search, Bell, Moon, PanelLeftClose, LogOut } from "lucide-react";
import { api, write, type User } from "@nachtlabs/api-client";
import { Notifications } from "@/features/monitoring";
import { Dialog } from "./ui";

export function Shell({ user, children }: {user: User; children: React.ReactNode}) {
  const [drawer, setDrawer] = useState(false); const [compact, setCompact] = useState(false);
  const [palette, setPalette] = useState(false); const [notifications, setNotifications] = useState(false); const [search, setSearch] = useState("");
  const path = usePathname(); const router = useRouter(); const client = useQueryClient();
  const overview = useQuery({queryKey: ["overview"], queryFn: () => api<{worker:string}>("/overview"), refetchInterval: 30000, enabled: !user.mfa_required});
  const admin = ["owner", "admin"].includes(user.role);
  const links = [
    {href:"/overview", title:"Overview", icon:Activity}, {href:"/projects", title:"Projects", icon:FolderGit2},
    ...(admin ? [{href:"/integrations",title:"Integrations",icon:FolderGit2},{href:"/agents-models",title:"Agents & models",icon:Settings},{href:"/api-keys",title:"API & keys",icon:KeyRound}] : []),
    {href:"/work-requests",title:"Work requests",icon:FolderGit2},{href:"/runs",title:"Runs",icon:Activity},{href:"/regressions",title:"Regressions",icon:ShieldCheck},{href:"/monitoring",title:"Monitoring",icon:Activity},
    ...(admin?[{href:"/workflows",title:"Workflows",icon:Settings}]:[]),
    {href:"/audit-log",title:"Audit log",icon:ShieldCheck}, {href:"/settings",title:"Settings",icon:Settings},
  ];
  useEffect(() => {
    const listener = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key === "k") { e.preventDefault(); setPalette(v => !v); } if(e.key === "Escape") setDrawer(false); };
    window.addEventListener("keydown", listener); return () => window.removeEventListener("keydown", listener);
  }, []);
  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const apply = () => { document.documentElement.dataset.theme = user.theme === "system" ? (media.matches ? "midnight" : "canvas") : user.theme; };
    apply(); media.addEventListener("change", apply); return () => media.removeEventListener("change", apply);
  }, [user.theme]);
  return <div className={`workspace ${compact ? "compact" : ""}`}>
    <a className="skip" href="#main">Skip to content</a>
    {drawer && <button className="scrim" aria-label="Close navigation" onClick={() => setDrawer(false)} />}
    <aside className={drawer ? "sidebar open" : "sidebar"}><Link className="brand" href="/overview"><Moon size={24}/><span>Nacht<span className="brand-light">Labs</span><small>ENGINEERING OPERATIONS</small></span></Link>
      <div className="org"><span className="avatar">{user.organization?.slice(0,1) ?? "N"}</span><span>{user.organization ?? "Organization"}<small>Local control plane</small></span></div>
      <p className="nav-label">WORKSPACE</p><nav aria-label="Primary navigation">{links.map(({href,title,icon:Icon}) => <Link key={href} href={href} className={path.startsWith(href) ? "selected" : ""} title={title} onClick={() => setDrawer(false)}><Icon size={18}/><span>{title}</span></Link>)}</nav>
      <div className="sidebar-bottom"><p className="notice">Linux qualification<small>Required before execution</small></p><button onClick={() => setCompact(!compact)} aria-label="Toggle compact navigation"><PanelLeftClose size={17}/><span>Collapse navigation</span></button></div>
    </aside>
    <div className="workarea"><header className="topbar"><button className="mobile-menu" onClick={() => setDrawer(!drawer)} aria-expanded={drawer} aria-label="Open navigation"><Menu size={19}/></button><span className="breadcrumb">Workspace <span>/</span> {path.split("/")[1]?.replaceAll("-", " ")}</span><div className="top-actions"><button onClick={() => setPalette(true)} aria-label="Search navigation"><Search size={16}/><span>Quick navigation</span><kbd>Ctrl K</kbd></button><span className="health"><span className={overview.data?.worker === "online" ? "dot online" : "dot"}/>{overview.data?.worker ?? "Checking worker"}</span><button aria-label="Notifications" onClick={() => setNotifications(true)}><Bell size={17}/></button><details className="user-menu"><summary><span className="avatar">{user.name.slice(0,1)}</span><span>{user.name}</span></summary><div><p>{user.email}<small>{user.role}</small></p><Link href="/settings/security">Security settings</Link><button onClick={async () => { try {await write("/auth/logout"); client.clear(); router.replace("/login");} catch { window.alert("Logout could not be confirmed. Please retry."); } }}><LogOut size={16}/>Sign out</button></div></details></div></header>
      <main id="main" className="main">{children}</main><footer>Native Linux · PostgreSQL persistence · Human-governed delivery <span>v0.1 / Linux acceptance pending</span></footer>
    </div>
    {palette && <Dialog title="Quick navigation" close={() => setPalette(false)}><input autoFocus aria-label="Find a page" placeholder="Find a page…" value={search} onChange={e => setSearch(e.target.value)}/><div className="palette">{links.filter(l => l.title.toLowerCase().includes(search.toLowerCase())).map(l => <Link key={l.href} href={l.href} onClick={() => setPalette(false)}>{l.title} →</Link>)}</div></Dialog>}
    {notifications && <Dialog title="Notifications" close={() => setNotifications(false)}><Notifications/></Dialog>}
  </div>;
}
