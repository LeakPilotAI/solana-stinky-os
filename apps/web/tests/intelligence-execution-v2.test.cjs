const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const root = path.join(__dirname, "../src");

// Execute actual TS, route, client and React view, replacing only fetch/Next's
// response transport. Tests never contact a database or a live provider.
function load(entry, fetch = async () => { throw new Error("disconnected"); }, overrides = {}) {
  const cache = new Map();
  function module(file) {
    if (cache.has(file)) return cache.get(file);
    const exports = {}; cache.set(file, exports);
    const source = fs.readFileSync(file, "utf8");
    const output = ts.transpileModule(source, { compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
    } }).outputText;
    vm.runInNewContext(output, { exports, fetch, AbortSignal, AbortController,
      setInterval, clearInterval, process: { env: {} },
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
const modelPath = "lib/api/intelligence-execution-v2.ts";
const viewPath = "components/command-center/IntelligenceExecutionV2Panel.tsx";
const routePath = "app/api/stinky/v1/intelligence/execution-v2/route.ts";
function fixture({ priced = 2, rejected = 2, unknown = 3, pending = 0, mints = 7, sessions = 1, distinctPriced = priced } = {}) {
  const mature = priced + rejected + unknown;
  const fraction = mature ? unknown / mature : null;
  const ready = mints >= 100 && sessions >= 5 && distinctPriced >= 80 && fraction !== null && fraction <= .2;
  const { V2_SHA, V2_VERSION } = load(modelPath);
  return {
    status: "OBSERVED", policy_version: V2_VERSION, policy_sha256: V2_SHA,
    prospective_boundary: "2026-10-07T11:51:36.391317+00:00",
    counts: { PAPER_PRICED: priced, REJECTED: rejected, UNKNOWN: unknown, PENDING: pending },
    distinct_mint_mature_plans: mints, verified_runtime_sessions: sessions, priced_paths: priced,
    unknown_fraction: fraction, evaluation_ready: ready,
    adequacy_status: ready ? "DESCRIPTIVE_REVIEW_ELIGIBLE" : "INSUFFICIENT_EVIDENCE",
    adequacy_gates: {
      distinct_mint_mature_plans: { observed: mints, required: 100, passed: mints >= 100 },
      verified_runtime_sessions: { observed: sessions, required: 5, passed: sessions >= 5 },
      complete_priced_paths: { observed: distinctPriced, required: 80, passed: distinctPriced >= 80 },
      unknown_fraction: { observed: fraction, required_max: .2, passed: fraction !== null && fraction <= .2 },
    }, paper_only: true, read_only: true, live_execution: false, trading_authority: false,
    order_submitted: false, transaction_signed: false, wallet_mutated: false, performance_validation: false,
  };
}
const view = props => renderToStaticMarkup(React.createElement(load(viewPath).IntelligenceExecutionV2View, props));

test("observed panel renders frozen gates, identities and explicit paper authority", () => {
  const html = view({ data: load(modelPath).parseExecutionV2(fixture()) });
  for (const text of ["PAPER-ONLY", "LIVE AUTHORITY LOCKED", "NOT EVALUATION READY", "Mature distinct mints", "Verified runtime sessions", "Distinct priced paths", "42.9%", "≤20%", "PAPER_PRICED", "REJECTED", "UNKNOWN", "PENDING", "genesis-paper-execution-v2", "2026-10-07T11:51:36.391317+00:00", "No live trading"]) assert.ok(html.includes(text), text);
  assert.equal((html.match(/<progress /g) || []).length, 3);
  assert.ok(html.includes('aria-labelledby="execution-v2-title"'));
});
for (const [state, props] of [
  ["loading", { loading: true, data: null }],
  ["unknown", { data: { status: "UNKNOWN" } }],
  ["disconnected", { error: true, data: null }],
  ["failed refresh hides old metrics", { error: true, data: fixture() }],
]) test(state + " never displays invented or stale metrics", () => {
  const html = view(props);
  assert.ok(!html.includes("<progress"));
  assert.ok(!html.includes("PAPER_PRICED</dt>"));
  assert.ok(html.includes(state === "loading" ? "Loading V2 evidence" : "EVIDENCE UNAVAILABLE"));
});
test("observed empty evidence shows genuine zeros and unavailable fraction", () => {
  const empty = fixture({ priced: 0, rejected: 0, unknown: 0, mints: 0, sessions: 0 });
  assert.ok(view({ data: load(modelPath).parseExecutionV2(empty) }).includes("No admitted plans observed yet"));
  assert.equal(empty.unknown_fraction, null);
});
test("pending-only evidence remains inadequate with no mature sessions", () => {
  const data = load(modelPath).parseExecutionV2(fixture({ priced: 0, rejected: 0, unknown: 0, pending: 4, mints: 0, sessions: 0 }));
  assert.equal(data.evaluation_ready, false);
  assert.ok(view({ data }).includes("NOT EVALUATION READY"));
});
test("adequate evidence permits descriptive review and retains paper limitations", () => {
  const data = load(modelPath).parseExecutionV2(fixture({ priced: 80, rejected: 20, unknown: 0, mints: 100, sessions: 5 }));
  const html = view({ data });
  assert.ok(html.includes("DESCRIPTIVE REVIEW ELIGIBLE"));
  assert.ok(html.includes("do not establish profitability"));
  assert.ok(html.includes("LIVE AUTHORITY LOCKED"));
});
test("duplicate priced rows cannot inflate the distinct path gate", () => {
  const data = load(modelPath).parseExecutionV2(fixture({ priced: 100, rejected: 0, unknown: 0, mints: 7, distinctPriced: 2 }));
  assert.equal(data.adequacy_gates.complete_priced_paths.observed, 2);
  assert.equal(data.evaluation_ready, false);
  assert.ok(view({ data }).includes('aria-label="Distinct priced paths" value="2" max="80"'));
});
const mutations = {
  "changed policy": r => { r.policy_sha256 = "different"; },
  "changed boundary": r => { r.prospective_boundary = "2026-10-08T00:00:00Z"; },
  "missing counts": r => { delete r.counts.UNKNOWN; },
  "invalid count": r => { r.counts.PENDING = -1; },
  "nonfinite count": r => { r.counts.PENDING = Infinity; },
  "fabricated readiness": r => { r.evaluation_ready = true; },
  "relaxed adequacy": r => { r.adequacy_gates.complete_priced_paths.required = 2; },
  "false unknown fraction": r => { r.unknown_fraction = 0; },
  ...Object.fromEntries(["live_execution", "trading_authority", "order_submitted", "transaction_signed", "wallet_mutated", "performance_validation"].map(key => [key, r => { r[key] = true; }])),
};
for (const [name, mutate] of Object.entries(mutations)) test("rejects " + name, () => {
  const r = fixture(); mutate(r);
  assert.throws(() => load(modelPath).parseExecutionV2(r));
});
test("actual proxy, API client and panel compose over bounded read-only requests", async () => {
  const body = fixture(); const upstream = [];
  const route = load(routePath, async (url, options) => { upstream.push([url, options]); return { ok: true, json: async () => body }; });
  const proxied = await route.GET();
  assert.equal(proxied.status, 200);
  assert.equal(proxied.headers["Cache-Control"], "no-store");
  assert.equal(upstream.length, 1);
  assert.equal(upstream[0][0], "http://127.0.0.1:8010/v1/intelligence/execution-v2");
  assert.equal(upstream[0][1].method, "GET");
  assert.equal(upstream[0][1].cache, "no-store");
  assert.ok(upstream[0][1].signal instanceof AbortSignal);
  const client = load("lib/api/client.ts", async (url, options) => {
    assert.equal(url, "/api/stinky/v1/intelligence/execution-v2");
    assert.equal(options.method, "GET"); assert.equal(options.cache, "no-store");
    return { ok: true, json: async () => proxied.body };
  });
  const result = await client.api.intelligenceExecutionV2();
  assert.ok(view({ data: result }).includes("NOT EVALUATION READY"));
});
for (const [name, fetch] of [
  ["transport", async () => { throw new Error("private upstream detail"); }],
  ["http", async () => ({ ok: false })],
  ["malformed", async () => ({ ok: true, json: async () => ({ status: "OBSERVED" }) })],
]) test("proxy failure " + name + " has no metrics or leaked error details", async () => {
  const result = await load(routePath, fetch).GET();
  assert.equal(result.status, 502); assert.equal(result.body.status, "UNKNOWN");
  assert.equal(Object.keys(result.body).length, 1);
  await assert.rejects(load(modelPath, async () => ({ ok: false })).fetchExecutionV2());
});
test("Command Center mounts V2 while retaining existing panels and feed", () => {
  const stub = label => () => React.createElement("div", null, label);
  const page = load("app/command-center/page.tsx", undefined, {
    "@/components/command-center/CommandCenter": { CommandCenter: stub("existing feed") },
    "@/components/command-center/PaperCalibrationPanel": { PaperCalibrationPanel: stub("existing calibration") },
    "@/components/command-center/EntityReadinessPanel": { EntityReadinessPanel: stub("existing entities") },
  });
  const html = renderToStaticMarkup(React.createElement(page.default));
  for (const label of ["existing feed", "existing calibration", "existing entities", "Intelligence Execution V2"]) assert.ok(html.includes(label));
});

test("existing Command Center distinguishes unavailable alert/entity feeds from measured empty feeds", () => {
  function render(failed) {
    const data = { status: failed ? "degraded" : "ok", available: !failed,
      degraded_sections: failed ? ["alerts", "entities"] : [], counts: {},
      runners: [], alerts: [], entities: [], smart_wallets: [], launches: [],
      opportunity_queue: [], patterns: { available: false, items: [], message: "" } };
    const states = [data, null, false, null, Date.now(), [], true];
    let index = 0;
    const cc = load("components/command-center/CommandCenter.tsx", undefined, {
      react: { ...React, useState: () => [states[index++], () => {}],
        useEffect: () => {}, useMemo: fn => fn() },
      "next/link": ({ href, children }) => React.createElement("a", { href }, children),
    });
    return renderToStaticMarkup(React.createElement(cc.CommandCenter));
  }
  const degraded = render(true);
  assert.ok(degraded.includes("ALERT EVIDENCE UNAVAILABLE"));
  assert.ok(degraded.includes("ENTITY EVIDENCE UNAVAILABLE"));
  assert.ok(!degraded.includes("No alerts yet."));
  assert.ok(!degraded.includes("No entities yet."));
  const empty = render(false);
  assert.ok(empty.includes("No alerts yet."));
  assert.ok(empty.includes("No entities yet."));
});
