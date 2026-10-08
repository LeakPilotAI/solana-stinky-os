const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

// Execute the current fetch proxy. The backend criteria/SQL semantics are
// behavior-tested in services/api/tests/test_paper_status_contract.py; these
// fixtures verify that transport preserves that complete contract unchanged.
function route({ env = {}, cohortFailure = false, marketFailure = false, cohortRaw = "", policyRaw = "", registryRaw = "", requests = [] } = {}) {
  const source = fs.readFileSync(path.join(__dirname, "../src/app/api/paper-status/route.ts"), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  const exports = {};
  vm.runInNewContext(output, {
    exports, process: { env }, AbortSignal,
    fetch: async (url, options) => {
      requests.push([url, options]);
      if (cohortFailure) throw new Error("database unavailable");
      return { ok: true, json: async () => {
        const criteria = {
          min_closed_outcomes: fixtureInt(env.STINKY_PAPER_READINESS_MIN_CLOSED_OUTCOMES),
          min_market_cap_samples: fixtureInt(env.STINKY_PAPER_READINESS_MIN_MARKET_CAP_SAMPLES),
          min_outcome_classes: fixtureInt(env.STINKY_PAPER_READINESS_MIN_OUTCOME_CLASSES),
        };
        const configured = Object.values(criteria).every(x => x !== null) && criteria.min_outcome_classes <= 3;
        return {
          status: "OBSERVED", policy_cohorts: cohortRaw.split(/\r?\n/).filter(Boolean).map(JSON.parse),
          policy: policyRaw ? JSON.parse(policyRaw) : { status: "NOT_SET" },
          policy_registry: registryRaw.split(/\r?\n/).filter(Boolean).map(JSON.parse),
          aggregate_scope: "ALL_IMMUTABLE_POLICY_COHORTS", historical_identity_inference: false,
          prospective_evidence: { readiness: {
            status: configured ? "CRITERIA_CONFIGURED" : "CRITERIA_NOT_SET", criteria,
            deficits: configured ? { closed_outcomes_needed: criteria.min_closed_outcomes,
              outcome_classes_needed: criteria.min_outcome_classes,
              market_cap_samples_needed: marketFailure ? null : criteria.min_market_cap_samples } : null,
            observed_market_cap_samples: marketFailure ? null : 0,
            market_cap_samples_available: !marketFailure, automatic_activation: false,
          } },
        };
      } };
    },
    require(name) {
      if (name === "next/server") return { NextResponse: { json: x => x } };
      throw new Error(`Unexpected dependency ${name}`);
    },
  });
  return exports.GET;
}
function fixtureInt(raw) {
  if (!raw || !/^[0-9]+$/.test(raw.trim())) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value > 0 ? value : null;
}

test("explicit positive evidence criteria are accepted without defaults", async () => {
  const result = await route({ env: {
    STINKY_PAPER_READINESS_MIN_CLOSED_OUTCOMES: "12",
    STINKY_PAPER_READINESS_MIN_MARKET_CAP_SAMPLES: " 8 ",
    STINKY_PAPER_READINESS_MIN_OUTCOME_CLASSES: "2",
  } })();
  assert.equal(result.prospective_evidence.readiness.status, "CRITERIA_CONFIGURED");
  assert.equal(result.prospective_evidence.readiness.deficits.closed_outcomes_needed, 12);
  assert.equal(result.prospective_evidence.readiness.automatic_activation, false);
  assert.equal((await route()()).prospective_evidence.readiness.status, "CRITERIA_NOT_SET");
});

test("cohort database failure stays UNKNOWN instead of a valid empty cohort list", async () => {
  const result = await route({ cohortFailure: true })();
  assert.equal(result.status, "UNKNOWN");
  assert.equal(result.policy_cohorts, undefined);
});

test("paper status uses one bounded API request instead of concurrent Docker probes", async () => {
  const requests = [];
  await route({ requests })();
  assert.equal(requests.length, 1);
  assert.equal(requests[0][0], "http://127.0.0.1:8010/v1/paper/status");
  assert.equal(requests[0][1].cache, "no-store");
  assert.ok(requests[0][1].signal instanceof AbortSignal);
  const source = fs.readFileSync(path.join(__dirname, "../src/app/api/paper-status/route.ts"), "utf8");
  assert.ok(!source.includes("execFile") && !source.includes("Promise.all"));
});

test("missing market-cap source remains unavailable instead of becoming a measured zero", async () => {
  const result = await route({
    marketFailure: true,
    env: {
      STINKY_PAPER_READINESS_MIN_CLOSED_OUTCOMES: "12",
      STINKY_PAPER_READINESS_MIN_MARKET_CAP_SAMPLES: "8",
      STINKY_PAPER_READINESS_MIN_OUTCOME_CLASSES: "2",
    },
  })();
  assert.equal(result.status, "OBSERVED");
  assert.equal(result.prospective_evidence.readiness.status, "CRITERIA_CONFIGURED");
  assert.equal(result.prospective_evidence.readiness.observed_market_cap_samples, null);
  assert.equal(result.prospective_evidence.readiness.market_cap_samples_available, false);
  assert.equal(result.prospective_evidence.readiness.deficits.market_cap_samples_needed, null);
  assert.equal(result.prospective_evidence.readiness.deficits.closed_outcomes_needed, 12);
  assert.equal(result.prospective_evidence.readiness.automatic_activation, false);
});

test("cohort identity survives newline-delimited JSON including delimiters in versions", async () => {
  const cohorts = [
    { policy_version: "version|one\ncontinued", policy_sha256: "a".repeat(64), provenance: "MANUAL", records: 3 },
    { policy_version: "version-two", policy_sha256: "b".repeat(64), provenance: "EVIDENCE_BACKED", records: 2 },
  ];
  const result = await route({ cohortRaw: cohorts.map(x => JSON.stringify(x)).join("\r\n") })();
  assert.equal(JSON.stringify(result.policy_cohorts), JSON.stringify(cohorts));
  assert.equal(result.aggregate_scope, "ALL_IMMUTABLE_POLICY_COHORTS");
  assert.equal(result.historical_identity_inference, false);
});

test("malformed cohort data is not a successful empty list", async () => {
  assert.equal((await route({ cohortRaw: "not-json" })()).status, "UNKNOWN");
});

test("invalid criteria remain unset rather than acquiring thresholds", async () => {
  for (const value of ["", "0", "-1", "1.5", "Infinity", "\\d", "9007199254740992"]) {
    const result = await route({ env: {
      STINKY_PAPER_READINESS_MIN_CLOSED_OUTCOMES: value,
      STINKY_PAPER_READINESS_MIN_MARKET_CAP_SAMPLES: "8",
      STINKY_PAPER_READINESS_MIN_OUTCOME_CLASSES: "2",
    } })();
    assert.equal(result.prospective_evidence.readiness.status, "CRITERIA_NOT_SET");
    assert.equal(result.prospective_evidence.readiness.deficits, null);
  }
});


test("paper cohort operator workflow has no hidden cutoff or release criteria defaults", () => {
  const source = fs.readFileSync(path.join(__dirname, "../src/components/command-center/PaperCohortReport.tsx"), "utf8");
  assert.ok(source.includes('const [asOf, setAsOf] = useState("")'));
  assert.ok(source.includes('const [minimumClosed, setMinimumClosed] = useState("")'));
  assert.ok(source.includes('const [minimumMean, setMinimumMean] = useState("")'));
  assert.ok(source.includes('const [maximumDrawdown, setMaximumDrawdown] = useState("")'));
  assert.ok(source.includes('const [minimumWinRate, setMinimumWinRate] = useState("")'));
  assert.ok(!source.includes("new Date().toISOString()"));
  assert.ok(source.includes("releaseCriteria() === null"));
  assert.ok(source.includes("Evaluate explicit criteria"));
});

test("paper evaluation artifacts are exportable and verified through read-only API", () => {
  const component = fs.readFileSync(path.join(__dirname, "../src/components/command-center/PaperCohortReport.tsx"), "utf8");
  const proxy = fs.readFileSync(path.join(__dirname, "../src/app/api/paper-evaluation-artifact/verify/route.ts"), "utf8");
  assert.ok(component.includes("IMMUTABLE EVALUATION ARTIFACT PRODUCED"));
  assert.ok(component.includes("Export artifact JSON"));
  assert.ok(component.includes("Verify artifact"));
  assert.ok(component.includes("/api/paper-evaluation-artifact/verify"));
  assert.ok(component.includes("it does not provision or activate a policy"));
  assert.ok(proxy.includes("/v1/paper/evaluation-artifact/verify"));
  assert.ok(proxy.includes("automatic_activation: false"));
  assert.ok(proxy.includes("live_execution: false"));
});


test("paper release evaluation request actually sends only explicit criteria", () => {
  const source = fs.readFileSync(path.join(__dirname, "../src/components/command-center/PaperCohortReport.tsx"), "utf8");
  assert.ok(source.includes("...(evaluate ? { release_criteria: releaseCriteria() } : {})"));
  assert.ok(source.includes("onClick={() => load(false)}"));
  assert.ok(source.includes("onClick={() => load(true)}"));
});

test("paper status distinguishes immutable provisioned registry from active pointer", () => {
  const routeSource = fs.readFileSync(path.join(__dirname, "../../../services/api/src/stinky_api/paper_status_contract.py"), "utf8");
  const panel = fs.readFileSync(path.join(__dirname, "../src/components/command-center/PaperCalibrationPanel.tsx"), "utf8");
  assert.ok(routeSource.includes("paper_registry_scope") || routeSource.includes("policy_registry_scope"));
  assert.ok(routeSource.includes("LATEST_50_IMMUTABLE_POLICIES"));
  assert.ok(routeSource.includes("THEN 'ACTIVE' ELSE 'PROVISIONED' END"));
  assert.ok(routeSource.includes("LIMIT 51"));
  assert.ok(routeSource.includes("provenance_mode"));
  assert.ok(panel.includes("Paper policy registry — provisioned vs active"));
  assert.ok(panel.includes("PROVISIONED is immutable registry state only"));
  assert.ok(panel.includes("Evaluation/review never activates a policy."));
});


test("evidence-backed status preserves exact content-addressed provenance identity", async () => {
  const comparison = "c".repeat(64);
  const candidate = "d".repeat(64);
  const provenanceSha = "e".repeat(64);
  const policySha = "f".repeat(64);
  const identity = {
    policy_version: "paper-evidence-v1",
    policy_sha256: policySha,
    provenance: {
      mode: "EVIDENCE_BACKED_SCORE_CANDIDATE",
      evidence_backed: true,
      candidate_version: "score-paper-candidate-v1:" + candidate.slice(0, 16),
      candidate_evidence_sha256: candidate,
      comparison_evidence_sha256: comparison,
      provenance_sha256: provenanceSha,
      candidate_cutoff: "2026-09-01T00:00:00+00:00",
      comparison_as_of: "2026-09-02T00:00:00+00:00",
    },
  };
  const active = {
    status: "ACTIVE", version: identity.policy_version, horizon: "15m", notional_usd: 20,
    policy_sha256: policySha, provenance: "EVIDENCE_BACKED",
    provenance_mode: identity.provenance.mode, policy_identity: identity,
    activated_at: "2026-09-03T00:00:00+00:00",
  };
  const registry = {
    policy_version: identity.policy_version, policy_sha256: policySha,
    provenance: "EVIDENCE_BACKED", provenance_mode: identity.provenance.mode,
    policy_identity: identity, state: "ACTIVE",
  };
  const cohort = {
    policy_version: identity.policy_version, policy_sha256: policySha,
    provenance: "EVIDENCE_BACKED", policy_identity: identity, records: 2,
  };
  const result = await route({
    policyRaw: JSON.stringify(active),
    registryRaw: JSON.stringify(registry),
    cohortRaw: JSON.stringify(cohort),
  })();
  assert.equal(result.policy.policy_identity.provenance.comparison_evidence_sha256, comparison);
  assert.equal(result.policy.policy_identity.provenance.candidate_evidence_sha256, candidate);
  assert.equal(result.policy.policy_identity.provenance.provenance_sha256, provenanceSha);
  assert.equal(result.policy_registry[0].policy_identity.provenance.comparison_evidence_sha256, comparison);
  assert.equal(result.policy_cohorts[0].policy_identity.provenance.comparison_evidence_sha256, comparison);

  const routeSource = fs.readFileSync(path.join(__dirname, "../../../services/api/src/stinky_api/paper_status_contract.py"), "utf8");
  const panel = fs.readFileSync(path.join(__dirname, "../src/components/command-center/PaperCalibrationPanel.tsx"), "utf8");
  assert.ok(routeSource.includes("'policy_identity',jsonb_build_object"));
  assert.ok(fs.readFileSync(path.join(__dirname, "../../../services/api/src/stinky_api/main.py"), "utf8").includes("record->'policy_identity'"));
  assert.ok(panel.includes("comparison_evidence_sha256"));
  assert.ok(panel.includes("Comparison evidence SHA"));
});
