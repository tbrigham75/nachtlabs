import {test,expect} from "@playwright/test";

// Mocked UI permission/projection checks only; this does not demonstrate a real run.
const id="00000000-0000-4000-8000-000000000001";
for(const role of ["owner","viewer"]){
 test(`plan decision controls respect ${role} presentation`,async({page})=>{
  await page.route("**/api/v1/**",async route=>{
   const path=new URL(route.request().url()).pathname;
   if(path.endsWith("/stream"))return route.fulfill({status:200,contentType:"text/event-stream",body:": heartbeat\n\n"});
   const data=path.endsWith("/auth/me")?{id,name:"Fixture",email:"fixture@example.invalid",role,active:true,theme:"canvas",version:1,mfa_required:false}
    :path.endsWith("/overview")?{worker:"online"}
    :path.endsWith("/runs/"+id)?{id,project_id:id,state:"awaiting_approval",stage:"planning",version:1,attempt:0,
     plan:{summary:"Synthetic plan",mission_alignment:"aligned"},plan_digest:"a".repeat(64),candidate:null,error_code:null,
     work_request:{id,title:"Synthetic greeting",description:"Write a greeting",acceptance_criteria:["Greeting matches"]},evidence:[],journeys:[],delivery:{}}
    :{};
   await route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(data)});
  });
  await page.goto("/runs/"+id);
  await expect(page.getByRole("heading",{name:"Synthetic greeting"})).toBeVisible();
  const decision=page.getByRole("button",{name:"Record decision"});
  if(role==="owner")await expect(decision).toBeVisible();
  else await expect(decision).toHaveCount(0);
  await page.getByRole("button",{name:"evidence",exact:true}).click();
  await expect(page.getByRole("heading",{name:"Candidate-bound evidence"})).toBeVisible();
  await expect(page.getByText("Agent completion is a claim.",{exact:false})).toBeVisible();
 });
}
