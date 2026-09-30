const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

// Run the actual route with only its external database/process/filesystem edges
// replaced. No Docker, application database, or credentials are used.
function route({ env = {}, cohortFailure = false, cohortRaw = "" } = {}) {
  const source = fs.readFileSync(path.join(__dirname, "../src/app/api/paper-status/route.ts"), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  const exports = {};
  vm.runInNewContext(output, {
    exports, process: { env, cwd: () => "/fixture", platform: "linux" },
    require(name) {
      if (name === "next/server") return { NextResponse: { json: x => x } };
      if (name === "node:fs/promises") return { readFile: async () => { throw new Error("no pid file"); } };
      if (name === "node:child_process") return { execFile: true };
      if (name === "node:util") return { promisify: () => async (_file, args) => {
        const sql = args.at(-1);
        if (sql.includes("GROUP BY policy_version,policy_sha256,policy_evidence_backed")) {
          if (cohortFailure) throw new Error("database unavailable");
          return { stdout: cohortRaw };
        }
        return { stdout: "" };
      } };
      if (name === "node:path") return path;
      throw new Error(`Unexpected dependency ${name}`);
    },
  });
  return exports.GET;
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
