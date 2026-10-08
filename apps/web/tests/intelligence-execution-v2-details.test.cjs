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
const model = "lib/api/intelligence-execution-v2-details.ts";
const component = "components/command-center/IntelligenceExecutionV2Details.tsx";
const route = "app/api/stinky/v1/intelligence/execution-v2/details/route.ts";
function fixture(empty = false) {
  const n = empty ? 0 : 4, priced = empty ? 0 : 1, time = "2026-10-08T02:00:00+00:00";
  const stat = (samples, value) => ({ n: samples, unavailable: n-samples, median_sec: value, p90_sec: value, max_sec: value });
  const unavailable = { status: "UNAVAILABLE", age_sec: null, latest_at: null };
  return {
    status: "OBSERVED", as_of: time, policy_version: "genesis-paper-execution-v2",
    policy_sha256: "efb3ab5d544bef3604253e6f0afabcbfcdf7e38a351fd3e031730958950dfa81", prospective_boundary: "2026-10-07T11:51:36.391317+00:00",
    paper_only: true, read_only: true, live_execution: false, trading_authority: false, order_submitted: false,
    transaction_signed: false, wallet_mutated: false, performance_validation: false,
    scope: { sampled_plans: n, plan_limit: 500, truncated: false, selection: "LATEST_PLAN_IDS" },
    counts: { PAPER_PRICED: priced, UNKNOWN: priced, REJECTED: priced, PENDING: priced },
    reasons: empty ? [] : [{ status: "UNKNOWN", reason: "entry_observation_missing", count: 1 }, { status: "REJECTED", reason: "entry_liquidity_below_frozen_minimum", count: 1 }],
    bound_observations: { entry: priced, exit: priced, unavailable: n-priced },
    latency: { detection_to_admission: stat(0, null), decision_to_admission: stat(n, empty ? null : 1),
      entry_observation_delay: stat(priced, empty ? null : 0), exit_observation_delay: stat(priced, empty ? null : 30), maturity_to_recording: stat(n-priced, empty ? null : 5) },
    quantile_method: "NEAREST_RANK_P90", freshness_threshold_sec: 300,
    freshness: { bound_entry: empty ? unavailable : { status: "STALE", age_sec: 600, latest_at: time }, bound_exit: empty ? unavailable : { status: "STALE", age_sec: 600, latest_at: time }, terminal_recording: empty ? unavailable : { status: "STALE", age_sec: 600, latest_at: time }, selected_mint_capture: unavailable },
    pending: { awaiting_maturity: 0, mature_without_result: priced }, session_starts: [], session_ends: "UNAVAILABLE", worker_downtime: "UNESTABLISHED",
    source_coverage: empty ? [] : [{ plan_id: 1, reason: "entry_observation_missing", target: time, captured_in_window: 0, bracketing_gap_sec: null, truncated: false, cause: "UNESTABLISHED", ingestion_delay: "UNAVAILABLE" }],
    source_coverage_limit: 20, missing_windows_truncated: false,
    rate_limit_correlations: empty ? [] : [{ plan_id: 1, rate_limit_lines: null, retained_window_covered: false, causal: false }],
    collection: { log_byte_limit: 1000000, logs: { collector: { status: "UNAVAILABLE", v2_success_lines: null }, maintain: { status: "UNAVAILABLE", v2_success_lines: null } }, heartbeats: { collector: { status: "UNAVAILABLE" }, maintain: { status: "UNAVAILABLE" } } },
    limitations: ["Current captures cannot reclassify immutable outcomes."],
  };
}
const view = props => renderToStaticMarkup(React.createElement(load(component).V2DetailsView, props));
test("details preserve reason/status identities, zero latency and unavailable clocks", () => {
  const data = load(model).parseV2Details(fixture());
  const html = view({ data });
  for (const text of ["entry_observation_missing", "entry_liquidity_below_frozen_minimum", "REJECTED", "UNKNOWN", "PENDING", "PAPER_PRICED", "0.000s", "30.000s", "UNAVAILABLE", "STALE", "NONCAUSAL", "read-only", "live authority locked", "nearest-rank p90", "Both remain PENDING", "process identity unverified"]) assert.ok(html.includes(text), text);
  assert.ok(html.includes('scope="col"') && html.includes("<caption") && html.includes('scope="row"'));
});
for (const [name, props] of [["loading", { data: fixture(), loading: true }], ["disconnected", { data: fixture(), error: true }], ["unavailable", { data: { status: "UNAVAILABLE" } }]]) {
  test(`${name} hides evidence metrics`, () => { const html = view(props); assert.ok(!html.includes("entry_observation_missing")); assert.ok(html.includes('role="status"')); });
}
test("observed empty sample is distinct from disconnected evidence", () => {
  const html = view({ data: load(model).parseV2Details(fixture(true)) });
  assert.ok(html.includes("No admitted plan evidence yet") && html.includes("UNKNOWN 0") && html.includes("UNAVAILABLE"));
});
test("partial plan/source samples are labeled", () => {
  const f = fixture(); f.scope.truncated = true; f.missing_windows_truncated = true; f.source_coverage[0].truncated = true;
  const html = view({ data: load(model).parseV2Details(f) });
  assert.ok(html.includes("PARTIAL SAMPLE") && html.includes("Additional missing windows excluded") && html.includes("PARTIAL CAPTURE SAMPLE"));
});
for (const [name, mutate] of [
  ["unsafe authority", f => f.live_execution = true], ["changed policy", f => f.policy_sha256 = "changed"],
  ["invented observation", f => f.bound_observations.entry = 2], ["negative count", f => f.counts.UNKNOWN = -1],
  ["partial latency stats", f => f.latency.entry_observation_delay.n = 2], ["unavailable replaced by zero", f => f.latency.detection_to_admission.median_sec = 0],
  ["changed p90 method", f => f.quantile_method = "interpolation"], ["beyond frozen window", f => f.latency.exit_observation_delay.max_sec = 31],
  ["causal rate claim", f => f.rate_limit_correlations[0].causal = true], ["uncovered zero", f => f.rate_limit_correlations[0].rate_limit_lines = 0],
  ["unbounded scope", f => f.scope.plan_limit = 100000], ["made-up downtime", f => f.worker_downtime = "HEALTHY"],
]) test(`parser rejects ${name}`, () => { const f = fixture(); mutate(f); assert.throws(() => load(model).parseV2Details(f)); });
test("client and proxy use bounded no-store GET with safe transport failure", async () => {
  let request;
  const transport = async (url, options) => { request = { url, options }; return { ok: true, json: async () => fixture() }; };
  assert.equal((await load(model, transport).fetchV2Details()).status, "OBSERVED");
  assert.equal(request.url, "/api/stinky/v1/intelligence/execution-v2/details"); assert.equal(request.options.method, "GET"); assert.equal(request.options.cache, "no-store"); assert.ok(request.options.signal);
  const response = await load(route, transport).GET(); assert.equal(response.status, 200); assert.equal(response.headers["Cache-Control"], "no-store"); assert.ok(request.url.startsWith("http://127.0.0.1:8010/"));
  const failed = await load(route).GET(); assert.equal(failed.status, 503); assert.equal(failed.body.status, "UNAVAILABLE"); assert.ok(!JSON.stringify(failed).includes("SECRET"));
});
test("proxy rejects unsafe or malformed upstream detail", async () => {
  const f = fixture(); f.wallet_mutated = true;
  const out = await load(route, async () => ({ ok: true, json: async () => f })).GET();
  assert.equal(out.status, 503); assert.equal(out.body.status, "UNAVAILABLE");
});
test("collapsed integration has no eager detail request and retains summary", () => {
  let fetches = 0;
  const html = renderToStaticMarkup(React.createElement(load("components/command-center/IntelligenceExecutionV2Panel.tsx", async () => { fetches++; throw new Error(); }).IntelligenceExecutionV2View, { data: null }));
  assert.ok(html.includes("Reasons, latency and collection details") && html.includes("Intelligence Execution V2")); assert.equal(fetches, 0);
});
test("expansion requests once and cleanup aborts; no polling", async () => {
  let state = 0, fetches = 0, cleanup, signal;
  const react = { ...React, useState: init => [state++ === 0 ? true : init, () => {}], useEffect: fn => { cleanup = fn(); } };
  load(component, async (url, options) => { fetches++; signal = options.signal; return { ok: true, json: async () => fixture() }; }, { react }).IntelligenceExecutionV2Details();
  await Promise.resolve(); await Promise.resolve();
  assert.equal(fetches, 1); assert.ok(signal); cleanup(); assert.ok(signal.aborted);
});
