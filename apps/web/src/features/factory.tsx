"use client";
import Link from "next/link";
import {useEffect,useRef,useState} from "react";
import {useRouter} from "next/navigation";
import {useQuery,useQueryClient} from "@tanstack/react-query";
import {api,write,type Project,type User} from "@nachtlabs/api-client";
import {Action,Badge,Empty,ErrorNotice,Form,Heading,Loading} from "@/components/ui";

type Work={id:string;project_id:string;title:string;description:string;acceptance_criteria:string[];status:string;target_ref:string;runs?:Run[]};
type Evidence={id:string;name:string;kind:string;status:string;candidate:string;protected:boolean};
type Run={id:string;project_id:string;state:string;stage:string;version:number;plan:Record<string,unknown>;plan_digest:string|null;candidate:string|null;error_code:string|null;attempt:number;work_request:Work;evidence:Evidence[];journeys:{id:string;version_id:string;content:{execution_type:string;description:string;approval_role:string}}[];delivery:Record<string,unknown>};
export function FactoryScreen({area,id,user}:{area:string;id?:string;user:User}){
 if(area==="runs"&&id)return <RunDetail id={id} user={user}/>;
 if(area==="work-requests"&&id&&id!=="new")return <WorkDetail id={id}/>;
 if(area==="workflows")return <Workflows user={user}/>;
 return <WorkList area={area} create={id==="new"||area==="regressions"} user={user}/>;
}
function WorkList({area,create,user}:{area:string;create:boolean;user:User}){
 const router=useRouter();const [chosen,setChosen]=useState("");
 const projects=useQuery({queryKey:["projects"],queryFn:()=>api<Project[]>("/projects")});
 const project=chosen||projects.data?.find(p=>!p.archived)?.id||"";
 const list=useQuery({queryKey:[area,project],queryFn:()=>api<(Work&Run)[]>(`/${area==="runs"?"runs":"work-requests"}?project_id=${project}`),enabled:!!project});
 const idempotency=useRef({body:"",key:""});
 const regression=area==="regressions";
 return <><Heading title={regression?"Manual regression":area==="runs"?"Runs":"Work requests"} note="Approved Missions and validation baselines govern every run.">
 {!create&&area==="work-requests"&&user.role!=="viewer"&&<Link className="button primary" href="/work-requests/new">New work request</Link>}</Heading>
 <ErrorNotice error={projects.error||list.error}/>
 <div className="field"><label htmlFor="factory-project">Project</label><select id="factory-project" value={project} onChange={e=>setChosen(e.target.value)}><option value="">Choose a project</option>{projects.data?.filter(p=>!p.archived).map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
 {!project?<Empty title="Choose an active project"/>:create?<section className="panel"><Form key={project} label={regression?"Queue regression plan":"Submit for planning"} initial={{target_ref:"main",priority:"normal",dry_run:"false"}} fields={[
 {name:"title",label:"Title",required:true,min:3,max:200},{name:"description",label:"Description",type:"textarea",required:true,min:10,max:12000},
 {name:"criteria",label:"Acceptance criteria",type:"textarea",required:true,help:"One criterion per line. Every criterion must be verified."},
 {name:"target_ref",label:"Target branch",required:true,max:200},{name:"workflow_id",label:"Workflow version ID (optional)",help:"Leave blank for the standard approval-gated workflow."},
 {name:"priority",label:"Priority",options:["low","normal","high","urgent"].map(v=>({value:v,label:v}))},
 {name:"dry_run",label:"Planning mode",options:[{value:"false",label:"Generate a plan for human approval"},{value:"true",label:"Inventory only; no execution"}]}
 ]} submit={async v=>{
 const body={project_id:project,title:v.title,description:v.description,acceptance_criteria:v.criteria.split("\n").map(c=>c.trim()).filter(Boolean),target_ref:v.target_ref,workflow_id:v.workflow_id||null,priority:v.priority,dry_run:v.dry_run==="true"};
 const serialized=JSON.stringify(body);if(idempotency.current.body!==serialized)idempotency.current={body:serialized,key:crypto.randomUUID()};
 const result=await api<{run:Run}>(regression?"/regressions":"/work-requests",{method:"POST",headers:{"Idempotency-Key":idempotency.current.key},body:serialized});
 router.push("/runs/"+result.run.id);
 }}/></section>:list.isPending?<Loading/>:!list.data?.length?<Empty title="No requests yet"/>:<section className="panel table-wrap"><table><thead><tr><th>{area==="runs"?"Run":"Request"}</th><th>Status</th><th>Target / stage</th></tr></thead><tbody>{list.data.map(v=><tr key={v.id}><td><Link href={`/${area==="runs"?"runs":"work-requests"}/${v.id}`}>{v.title||v.id.slice(0,12)}</Link></td><td><Badge>{v.status||v.state}</Badge></td><td>{v.target_ref||v.stage}</td></tr>)}</tbody></table></section>}
 </>;
}
function WorkDetail({id}:{id:string}){
 const query=useQuery({queryKey:["work",id],queryFn:()=>api<Work>("/work-requests/"+id)});
 if(query.isPending)return <Loading/>;if(query.error)return <ErrorNotice error={query.error}/>;
 const value=query.data!;
 return <><Heading title={value.title} note={value.status}/><section className="panel"><p>{value.description}</p><h2>Acceptance criteria</h2><ol>{value.acceptance_criteria.map((v,i)=><li key={i}>{v}</li>)}</ol><h2>Runs</h2>{value.runs?.map(v=><p key={v.id}><Link href={"/runs/"+v.id}>{v.id}</Link> <Badge>{v.state}</Badge></p>)}</section></>;
}
function RunDetail({id,user}:{id:string;user:User}){
 const client=useQueryClient();const [tab,setTab]=useState("plan");const [payload,setPayload]=useState<unknown>();const [streamState,setStreamState]=useState("Connecting");
 const query=useQuery({queryKey:["run",id],queryFn:()=>api<Run>("/runs/"+id),refetchInterval:15000});
 const events=useQuery({queryKey:["run-events",id],queryFn:()=>api<{items:unknown[];events?:unknown[];latest:number}>("/runs/"+id+"/events"),enabled:tab==="events",refetchInterval:15000});
 useEffect(()=>{const stream=new EventSource("/api/v1/runs/"+id+"/stream");
 stream.onopen=()=>setStreamState("Live");stream.onerror=()=>setStreamState("Reconnecting; polling remains available");
 const refresh=()=>{void client.invalidateQueries({queryKey:["run",id]});void client.invalidateQueries({queryKey:["run-events",id]});};
 stream.addEventListener("run",refresh);stream.addEventListener("revoked",()=>{stream.close();setStreamState("Access expired");refresh();});
 return()=>stream.close();},[id,client]);
 const refresh=()=>client.invalidateQueries({queryKey:["run",id]});
 if(query.isPending)return <Loading/>;if(query.error)return <ErrorNotice error={query.error}/>;
 const value=query.data!;const operator=["owner","admin","operator"].includes(user.role);const admin=["owner","admin"].includes(user.role);
 return <><Heading title={value.work_request.title} note={`Stage: ${value.stage} · Attempt ${value.attempt+1} · ${streamState}`}><Badge good={value.state==="completed"}>{value.state}</Badge></Heading>
 {value.error_code&&<p className="notice warning">Needs review: {value.error_code.replaceAll("_"," ")}</p>}
 <nav className="tabs" aria-label="Run detail">{["plan","evidence","events","delivery"].map(t=><button key={t} className={tab===t?"active":""} onClick={()=>{setTab(t);setPayload(undefined);}}>{t}</button>)}</nav>
 {tab==="plan"&&<section className="panel"><h2>Plan and Mission assessment</h2><pre>{JSON.stringify(value.plan,null,2)}</pre><p>Candidate: <code>{value.candidate||"Not produced"}</code></p>
 {operator&&value.state==="awaiting_approval"&&<Form key={value.version} label="Record decision" initial={{decision:"approve"}} fields={[{name:"decision",label:"Decision",options:["approve","request_changes","reject"].map(v=>({value:v,label:v.replaceAll("_"," ")}))},{name:"reason",label:"Review notes",type:"textarea",required:true,max:2000}]} submit={async v=>{await write(`/runs/${id}/approval`,{expected_version:value.version,digest:value.plan_digest,...v});await refresh();}}/>}
 {user.role==="owner"&&value.state==="human_review"&&value.stage==="verification"&&<Form key={"exception-"+value.version} label="Accept eligible verifier warnings" fields={[{name:"reason",label:"Owner exception justification",type:"textarea",required:true,help:"Requires the project policy to permit this exception. Failed checks and unmet criteria cannot be waived."}]} submit={async v=>{await write(`/runs/${id}/accept-verifier-warnings`,{expected_version:value.version,...v});await refresh();}}/>}
 {operator&&["blocked","human_review"].includes(value.state)&&<Form key={value.version} label="Request a fresh plan" fields={[{name:"reason",label:"Reason for rework",required:true}]} submit={async v=>{await write(`/runs/${id}/replan`,{expected_version:value.version,...v});await refresh();}}/>}
 {operator&&!["completed","cancelled","rejected","dry_run_complete"].includes(value.state)&&<Action danger action={async()=>{await write(`/runs/${id}/cancel`,{expected_version:value.version,reason:"Cancelled from run detail"});await refresh();}}>Cancel run</Action>}</section>}
 {tab==="evidence"&&<section className="panel"><h2>Candidate-bound evidence</h2><p>Agent completion is a claim. Checks, human attestations and independent review are recorded separately.</p>
 <ul className="checklist">{value.evidence.map(e=><li key={e.id}><span>{e.name}<small>{e.kind} · {e.candidate.slice(0,12)}</small></span><Badge good={e.status==="passed"}>{e.status}</Badge>{(!e.protected||admin)&&<Action action={async()=>setPayload(await api(`/runs/${id}/evidence/${e.id}`))}>Read evidence</Action>}</li>)}</ul>
 {payload!==undefined&&<pre>{JSON.stringify(payload,null,2)}</pre>}
 {operator&&value.state==="awaiting_manual"&&<Form key={value.version} label="Record human attestation" initial={{outcome:"passed"}} fields={[
 {name:"journey_id",label:"Manual Journey",required:true,options:value.journeys.filter(j=>j.content.execution_type==="manual"&&!value.evidence.some(e=>e.name===j.id&&e.candidate===value.candidate)).map(j=>({value:j.id,label:j.content.description}))},
 {name:"outcome",label:"Observed outcome",options:["passed","failed","blocked"].map(v=>({value:v,label:v}))},
 {name:"evidence",label:"Observed evidence",type:"textarea",required:true,min:10,max:8000,help:"Record actual observations for this exact candidate. Do not paste secrets."}
 ]} submit={async v=>{await write(`/runs/${id}/attestations`,{...v,expected_version:value.version,candidate:value.candidate});await refresh();}}/>}</section>}
 {tab==="events"&&<section className="panel"><ErrorNotice error={events.error}/><pre>{JSON.stringify(events.data,null,2)}</pre></section>}
 {tab==="delivery"&&<section className="panel"><h2>Pull request delivery</h2>{typeof value.delivery.url==="string"&&value.delivery.url.startsWith("https://")&&<p><a href={value.delivery.url} target="_blank" rel="noopener noreferrer">{value.delivery.url}</a> <Badge>{String(value.delivery.status??"open")}</Badge></p>}<pre>{JSON.stringify(value.delivery,null,2)}</pre><p>Delivery requires current approval, scope checks, secret scanning, all required Journeys and independent verification.</p></section>}
 </>;
}
function Workflows({user}:{user:User}){
 const client=useQueryClient();const query=useQuery({queryKey:["workflows"],queryFn:()=>api<{id:string;name:string;version:number;configuration:unknown}[]>("/workflows"),enabled:["owner","admin"].includes(user.role)});
 if(!["owner","admin"].includes(user.role))return <Empty title="Administrator access required"/>;
 return <><Heading title="Workflow versions" note="Published versions are immutable. Every workflow requires plan approval and PR-only delivery."/><ErrorNotice error={query.error}/>
 <section className="panel"><Form fields={[{name:"name",label:"Workflow name",required:true,max:120},{name:"description",label:"Description",type:"textarea",required:true,max:4000},{name:"max_repairs",label:"Repair budget (0–2)",type:"number",required:true}]} initial={{max_repairs:"1"}} label="Publish next version" submit={async v=>{const latest=Math.max(0,...(query.data??[]).filter(w=>w.name===v.name).map(w=>w.version));await write("/workflows",{name:v.name,description:v.description,max_repairs:Number(v.max_repairs),expected_version:latest});await client.invalidateQueries({queryKey:["workflows"]});}}/></section>
 {query.data?.map(w=><section className="panel" key={w.id}><h2>{w.name} · Version {w.version}</h2><pre>{JSON.stringify(w.configuration,null,2)}</pre></section>)}</>;
}
export function ExecutionSettings({projectId}:{projectId:string}){
 const client=useQueryClient();const query=useQuery({queryKey:["execution-policy",projectId],queryFn:()=>api<{version:number;configuration:Record<string,unknown>}>(`/projects/${projectId}/execution-policy`)});
 const webhook=useQuery({queryKey:["webhook",projectId],queryFn:()=>api<{version:number;enabled:boolean;actors:string[];labels:string[];path:string|null}>(`/projects/${projectId}/webhook`)});
 return <><section className="panel"><h2>Execution policy</h2><p>Repository and command keys refer to the Linux administrator’s qualified catalog. Network access and execution qualification remain operator-controlled.</p><ErrorNotice error={query.error}/>
 {query.data&&<Form key={query.data.version} initial={{configuration:JSON.stringify(query.data.configuration,null,2)}} fields={[{name:"configuration",label:"Policy JSON",type:"textarea",required:true,max:16000}]} submit={async v=>{await write(`/projects/${projectId}/execution-policy`,{expected_version:query.data!.version,configuration:JSON.parse(v.configuration)},"PUT");await client.invalidateQueries({queryKey:["execution-policy",projectId]});}}/>}</section>
 <section className="panel"><h2>Signed webhook intake</h2><ErrorNotice error={webhook.error}/>{webhook.data&&<><p>{webhook.data.path||"Configure to obtain the webhook path"}</p><Form key={webhook.data.version} initial={{enabled:String(webhook.data.enabled),actors:webhook.data.actors.join("\n"),labels:webhook.data.labels.join("\n")}} fields={[{name:"enabled",label:"Webhook state",options:[{value:"false",label:"Disabled"},{value:"true",label:"Enabled"}]},{name:"actors",label:"Allowed provider usernames",type:"textarea",required:true,help:"One per line."},{name:"labels",label:"Required issue labels",type:"textarea",required:true,help:"One per line; all are required."}]} submit={async v=>{await write(`/projects/${projectId}/webhook`,{version:webhook.data!.version,enabled:v.enabled==="true",actors:v.actors.split("\n").filter(Boolean),labels:v.labels.split("\n").filter(Boolean)},"PUT");await client.invalidateQueries({queryKey:["webhook",projectId]});}}/></>}</section></>;
}
