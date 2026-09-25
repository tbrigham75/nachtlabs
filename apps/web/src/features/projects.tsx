"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, write, type Project, type User } from "@nachtlabs/api-client";
import { Action, Badge, Empty, ErrorNotice, Form, Heading, Loading } from "@/components/ui";
import { GovernanceScreen } from "./governance";
import { ExecutionSettings } from "./factory";
import { ProjectIntegrationSettings } from "./project-integration";

export function Projects({user,create=false}:{user:User;create?:boolean}) {
 const router=useRouter(); const client=useQueryClient(); const admin=["owner","admin"].includes(user.role);
 const query=useQuery({queryKey:["projects"],queryFn:()=>api<Project[]>("/projects")});
 if(create) return <><Heading title="Create project" note="Begin with a draft project. Configure repository and agent routing under project settings."/>{admin ? <section className="panel"><Form fields={[{name:"name",label:"Project name",required:true,max:120},{name:"slug",label:"Project slug",required:true,max:80,help:"Lowercase letters, numbers, and hyphens."},{name:"description",label:"Description",type:"textarea"}]} label="Create project" submit={async v=>{const p=await write<Project>("/projects",v); await client.invalidateQueries({queryKey:["projects"]}); router.push(`/projects/${p.id}`);}}/></section>:<ErrorNotice error={new Error("Owner or Admin access is required")}/>}</>;
 return <><Heading title="Projects" note="Repository-independent governance, ownership, and delivery boundaries.">{admin&&<Link className="button primary" href="/projects/new">+ Create project</Link>}</Heading><ErrorNotice error={query.error}/>{query.isPending?<Loading/>:!query.data?.length?<Empty title="Give your factory a clear mission"><p>Create a project to establish its scope and validation baseline.</p>{admin&&<Link className="button" href="/projects/new">Create your first project</Link>}</Empty>:<section className="panel table-wrap"><table><thead><tr><th>Project</th><th>Delivery</th><th>State</th><th>Approval</th></tr></thead><tbody>{query.data.map(p=><tr key={p.id}><td><Link href={`/projects/${p.id}`}><strong>{p.name}</strong></Link><small>{p.description || p.slug}</small></td><td>PR only</td><td><Badge>{p.archived?"Archived":"Governance workspace"}</Badge></td><td>Plan approval required</td></tr>)}</tbody></table></section>}</>;
}
export function ProjectScreen({id,tab="overview",user}:{id:string;tab?:string;user:User}) {
 const query=useQuery({queryKey:["project",id],queryFn:()=>api<Project>(`/projects/${id}`)});
 if(query.isPending)return <Loading/>;if(query.error)return <ErrorNotice error={query.error}/>;
 const project=query.data!;const admin=["owner","admin"].includes(user.role);
 const tabs=[['overview','Overview'],['mission','Mission'],['validation-journeys','Validation Journeys'],...(admin?[["holdouts","Holdouts"],["settings","Settings"]]:[])];
 return <><Heading title={project.name} note={project.description || "Define the outcomes this project exists to deliver."}><Badge>{project.archived?"Archived":"Governance workspace"}</Badge></Heading><div className="tabs" role="navigation" aria-label="Project sections">{tabs.map(([key,label])=><Link key={key} className={tab===key?"active":""} href={`/projects/${id}${key==='overview'?'':`/${key}`}`}>{label}</Link>)}</div>
 {['mission','validation-journeys','holdouts'].includes(tab)?<GovernanceScreen projectId={id} kind={tab==='mission'?'mission':tab==='holdouts'?'holdout':'journey'} admin={admin}/>:tab==='settings'?<ProjectSettings project={project} admin={admin}/>:<div className="grid two"><section className="panel"><h2>Project readiness</h2><ul className="checklist">{Object.entries(project.readiness??{}).map(([key,value])=><li key={key}><span>{key.replaceAll('_',' ')}</span><Badge good={value}>{value?'Configured':'Pending'}</Badge></li>)}</ul></section><section className="panel"><h2>Delivery policy</h2><ul className="checklist"><li>Plan approval<Badge good>Required</Badge></li><li>Delivery mode<Badge>PR only</Badge></li><li>Agent execution<Badge>Operator qualification required</Badge></li><li>Schedules<Badge>Disabled</Badge></li></ul><p>Start with a Validation Journey, approve it, and select it as a required baseline when drafting the Mission.</p></section></div>}
 </>;
}
function ProjectSettings({project,admin}:{project:Project;admin:boolean}) {
 const client=useQueryClient();
 const users=useQuery({queryKey:["users"],queryFn:()=>api<User[]>("/users"),enabled:admin});
 const members=useQuery({queryKey:["members",project.id],queryFn:()=>api<User[]>(`/projects/${project.id}/members`),enabled:admin});
 const refresh=()=>client.invalidateQueries({queryKey:["members",project.id]});
 if(!admin)return <ErrorNotice error={new Error("Owner or Admin access is required")}/>;
 return <div className="grid two"><ProjectIntegrationSettings projectId={project.id}/><ExecutionSettings projectId={project.id}/><section className="panel"><h2>Project details</h2><Form key={project.version} initial={{name:project.name,description:project.description,archived:String(project.archived)}} fields={[{name:"name",label:"Name",required:true},{name:"description",label:"Description",type:"textarea"},{name:"archived",label:"Project state",options:[{value:"false",label:"Active"},{value:"true",label:"Archived"}]}]} submit={async v=>{await write(`/projects/${project.id}`,{name:v.name,description:v.description,archived:v.archived==='true',version:project.version},"PATCH");await client.invalidateQueries({queryKey:["project",project.id]});await client.invalidateQueries({queryKey:["projects"]});}}/></section><section className="panel"><h2>Project membership</h2><p>Owners and Admins have organization-wide access. Other roles require membership.</p><ErrorNotice error={users.error||members.error}/>{!!users.data?.length&&<Form fields={[{name:"user_id",label:"User",required:true,options:users.data.filter(u=>u.active).map(u=>({value:u.id,label:`${u.name} (${u.role})`}))}]} label="Grant project access" submit={async v=>{await write(`/projects/${project.id}/members`,v);await refresh();}}/>}<ul className="checklist">{members.data?.map(u=><li key={u.id}><span>{u.name}<small>{u.role}</small></span><Action danger action={async()=>{await api(`/projects/${project.id}/members/${u.id}`,{method:"DELETE"});await refresh();}}>Remove</Action></li>)}</ul></section></div>;
}
