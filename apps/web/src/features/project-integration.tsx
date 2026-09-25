"use client";
import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, write } from "@nachtlabs/api-client";
import { Badge, ErrorNotice, Form, Loading } from "@/components/ui";
import type { AgentConfig, Binding, Connection, ModelProfile, Probe } from "./integration-types";

export function ProjectIntegrationSettings({projectId}:{projectId:string}) {
  const client=useQueryClient(),[connectionId,setConnectionId]=useState<string>(),[probeId,setProbeId]=useState<string>();
  const binding=useQuery({queryKey:["project-integration",projectId],queryFn:()=>api<Binding|null>(`/projects/${projectId}/integration`)});
  const connections=useQuery({queryKey:["integrations"],queryFn:()=>api<Connection[]>("/integrations")});
  const agents=useQuery({queryKey:["agents"],queryFn:()=>api<AgentConfig[]>("/agents")});
  const profiles=useQuery({queryKey:["model-profiles"],queryFn:()=>api<ModelProfile[]>("/model-profiles")});
  const git=connections.data?.filter(c=>c.provider!=="ollama"&&c.active)??[];
  const selected=connectionId??binding.data?.connection_id??git[0]?.id;
  const probes=useQuery({queryKey:["probes",selected],queryFn:()=>api<Probe[]>(`/integrations/${selected}/probes`),enabled:!!selected});
  const current=git.find(c=>c.id===selected);
  const successful=probes.data?.filter(p=>p.state==="succeeded"&&p.connection_version===current?.version&&p.finished_at&&Date.now()-Date.parse(p.finished_at)<86400000)??[];
  const chosen=successful.find(p=>p.id===probeId)??successful[0];
  const options=(role:string)=>[{value:"",label:"Not assigned"},...(agents.data?.filter(a=>a.active&&profiles.data?.some(p=>p.id===a.model_profile_id&&p.role===role&&p.active)).map(a=>({value:a.id,label:a.name}))??[])];
  if(binding.isPending)return <Loading/>;
  return <section className="panel"><h2>Repository and agent routing</h2><p>Only a repository returned by a recent successful check can be selected. Assignment does not enable execution.</p><ErrorNotice error={binding.error||connections.error||agents.error||profiles.error||probes.error}/>
    {binding.data&&<p>Selected: <strong>{binding.data.full_name}</strong> · base {binding.data.default_branch} <Badge>Execution unavailable</Badge></p>}
    {!git.length?<p><Link href="/integrations">Configure a Git connection</Link> before selecting a repository.</p>:<>
      <label>Git connection<select value={selected??""} onChange={e=>{setConnectionId(e.target.value);setProbeId(undefined);}}>{git.map(c=><option value={c.id} key={c.id}>{c.name}</option>)}</select></label>
      {!successful.length?<p className="notice">No current discovery is available. Request an authorized check under Integrations. Network policy may keep this step pending.</p>:<>
        <label>Discovery page<select value={chosen?.id??""} onChange={e=>setProbeId(e.target.value)}>{successful.map(p=><option key={p.id} value={p.id}>Page {p.page} · {new Date(p.created_at).toLocaleString()}</option>)}</select></label>
        {!!chosen?.result.repositories?.length&&<Form key={`${chosen.id}-${binding.data?.version??0}`} initial={{repository_id:chosen.result.repositories.some(r=>r.provider_id===binding.data?.repository_id)?binding.data!.repository_id:chosen.result.repositories[0].provider_id,implementation_agent_id:binding.data?.implementation_agent_id??"",verifier_agent_id:binding.data?.verifier_agent_id??"",require_distinct_models:String(binding.data?.require_distinct_models??true)}} fields={[
          {name:"repository_id",label:"Repository",required:true,options:chosen.result.repositories.map(r=>({value:r.provider_id,label:`${r.full_name} · ${r.default_branch}`}))},
          {name:"implementation_agent_id",label:"Implementation agent",options:options("implementation")},{name:"verifier_agent_id",label:"Verifier agent",options:options("verifier")},
          {name:"require_distinct_models",label:"Require different model identifiers",options:[{value:"true",label:"Required"},{value:"false",label:"Optional"}],help:"Different labels do not prove independent execution. Runtime verification is a later gate."}
        ]} submit={async v=>{await write(`/projects/${projectId}/integration`,{connection_id:selected,probe_id:chosen.id,repository_id:v.repository_id,implementation_agent_id:v.implementation_agent_id||null,verifier_agent_id:v.verifier_agent_id||null,require_distinct_models:v.require_distinct_models==="true",expected_version:binding.data?.version??0},"PUT");await client.invalidateQueries({queryKey:["project-integration",projectId]});await client.invalidateQueries({queryKey:["project",projectId]});}}/>}
      </>}
    </>}
  </section>;
}
