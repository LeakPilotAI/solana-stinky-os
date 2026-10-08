const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const root = path.join(__dirname, "../src");
function load(entry, fetch = async () => { throw new Error("disconnected"); }, overrides = {}) {
  const cache = new Map();
  function module(file) {
    if (cache.has(file)) return cache.get(file);
    const exports = {}; cache.set(file, exports);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), { compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
    } }).outputText;
    vm.runInNewContext(output, { exports, fetch, AbortSignal, AbortController, setInterval, clearInterval, process: { env: {} },
      require(name) {
        if (overrides[name]) return overrides[name];
        if (name === "next/server") return { NextResponse: { json: (body, options = {}) => ({ body, status: options.status || 200, headers: options.headers }) } };
        if (name.startsWith("@/") || name.startsWith(".")) {
          const base = name.startsWith("@/") ? path.join(root, name.slice(2)) : path.resolve(path.dirname(file), name);
          return module([base, base + ".ts", base + ".tsx"].find(p => fs.existsSync(p) && fs.statSync(p).isFile()));
        }
        return require(name);
      },
    }, { filename: file });
    return exports;
  }
  return module(path.join(root, entry));
}
const model="lib/api/supervisor-passes.ts",view="components/command-center/SupervisorPassStatus.tsx",route="app/api/stinky/v1/intelligence/execution-v2/supervisor-passes/route.ts";
function fixture(){
 const time="2026-10-08T03:00:00+00:00";
 const pass={pass_id:"00000000-0000-0000-0000-000000000001",observer_id:"00000000-0000-0000-0000-000000000002",supervisor_pid:28324,
 started_at:"2026-10-08T02:59:58+00:00",finished_at:time,phase:"FINISH",pair_state:"COMPLETE",exit_code:0,duration_sec:2,wall_clock_order:"ORDERED",sleep_interval_sec:null,matches_current_state:true};
 return {status:"OBSERVED",as_of:time,clock_owner:"HOST_UTC_SUPERVISOR",experiment_evidence:false,process_identity_verified:false,downtime:"UNESTABLISHED",interval_warning_sec:30,
 scope:{byte_limit:1000000,event_limit:100,pass_limit:20,retained_events:2,truncated:false,duplicate_events:0},
 freshness:{status:"RECENT",age_sec:0,latest_at:time},collection_freshness:{status:"UNAVAILABLE",age_sec:null,latest_at:null,scope:"LATEST_50_PLAN_MINTS",as_of:null},
 passes:[pass],last_successful_pass:{...pass},recent_failures:0,partial_passes:0,large_observed_intervals:0,
 paper_only:true,read_only:true,live_execution:false,trading_authority:false,order_submitted:false,transaction_signed:false,wallet_mutated:false,performance_validation:false};
}
const render=props=>renderToStaticMarkup(React.createElement(load(view).SupervisorStatusView,props));
test("genuine metadata shows recorded identity and exit zero without claiming downtime",()=>{
 const html=render({data:load(model).parseSupervisor(fixture())});
 for(const text of ["Supervisor pass observations","RECENT","exit 0","2.000s","UNAVAILABLE","HOST","observer","not experiment sessions","not live process verification","maximum 20","read-only"].map(t=>t==="HOST"?"Host UTC":t==="read-only"?"Read-only":t))assert.ok(html.includes(text),text);
 assert.ok(html.includes('aria-labelledby="v2-supervisor-title"')&&html.includes("<dl"));
});
for(const [name,props] of [["loading",{data:fixture(),loading:true}],["disconnected",{data:fixture(),error:true}],["unavailable",{data:{status:"UNAVAILABLE"}}]])test(`${name} hides all old pass records`,()=>{
 const html=render(props);assert.ok(!html.includes("28324")&&!html.includes("exit 0"));assert.ok(html.includes('role="status"'));
});
test("observed empty differs from unavailable",()=>{
 const f=fixture();f.passes=[];f.last_successful_pass=null;f.scope.retained_events=0;f.freshness={status:"UNAVAILABLE",age_sec:null,latest_at:null};
 assert.ok(render({data:load(model).parseSupervisor(f)}).includes("No recorded passes"));
});
test("stale partial failed observations and duplicates remain explicit",()=>{
 const f=fixture();f.freshness.status="STALE";f.freshness.age_sec=400;f.scope.truncated=true;f.scope.duplicate_events=2;f.last_successful_pass=null;f.recent_failures=1;f.passes[0].exit_code=1;
 const html=render({data:load(model).parseSupervisor(f)});assert.ok(html.includes("STALE")&&html.includes("PARTIAL TAIL")&&html.includes("duplicates 2")&&html.includes("failures 1"));
 f.passes[0]={...f.passes[0],phase:"START",pair_state:"START_ONLY",finished_at:null,exit_code:null,duration_sec:null,wall_clock_order:"UNAVAILABLE"};f.partial_passes=1;
 assert.ok(render({data:load(model).parseSupervisor(f)}).includes("START_ONLY"));
});
for(const [name,mutate] of [
 ["unsafe authority",f=>f.transaction_signed=true],["fabricated session",f=>f.experiment_evidence=true],["fabricated identity verification",f=>f.process_identity_verified=true],
 ["fabricated downtime",f=>f.downtime="RUNNING"],["unbounded file",f=>f.scope.byte_limit=9000000],["duplicate pass",f=>f.passes.push({...f.passes[0]})],
 ["negative duration",f=>f.passes[0].duration_sec=-1],["unknown replaced by zero",f=>f.collection_freshness.age_sec=0],
 ["invented clock",f=>f.passes[0].started_at="yesterday"],["contradictory pair",f=>f.passes[0].pair_state="START_ONLY"],
 ["false success",f=>f.last_successful_pass.exit_code=1],["unbounded output",f=>f.scope.pass_limit=500],
])test(`parser rejects ${name}`,()=>{const f=fixture();mutate(f);assert.throws(()=>load(model).parseSupervisor(f));});
test("recorded regression is visible and not corrected",()=>{
 const f=fixture();f.passes[0].started_at="2026-10-08T03:00:01+00:00";f.passes[0].wall_clock_order="REGRESSION";f.last_successful_pass=null;
 assert.ok(render({data:load(model).parseSupervisor(f)}).includes("REGRESSION"));
});
test("microsecond clock contradiction is preserved despite Date millisecond rounding",()=>{
 const f=fixture();f.passes[0].started_at="2026-10-08T02:59:58.000002+00:00";f.passes[0].finished_at="2026-10-08T02:59:58.000001+00:00";f.passes[0].wall_clock_order="REGRESSION";f.last_successful_pass=null;
 assert.equal(load(model).parseSupervisor(f).passes[0].wall_clock_order,"REGRESSION");
});
test("bounded no-store client/proxy preserve safety and redact transport failures",async()=>{
 let request;const fetch=async(url,options)=>{request={url,options};return {ok:true,json:async()=>fixture()};};
 assert.equal((await load(model,fetch).fetchSupervisor()).status,"OBSERVED");assert.equal(request.options.method,"GET");assert.equal(request.options.cache,"no-store");assert.ok(request.options.signal);
 assert.equal((await load(route,fetch).GET()).status,200);assert.ok(request.url.startsWith("http://127.0.0.1:8010/"));
 const failed=await load(route,async()=>{throw Error("SECRET");}).GET();assert.equal(failed.status,503);assert.ok(!JSON.stringify(failed).includes("SECRET"));
});
