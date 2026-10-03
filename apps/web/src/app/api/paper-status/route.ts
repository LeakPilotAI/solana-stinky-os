import { NextResponse } from "next/server";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { readFile } from "node:fs/promises";
import path from "node:path";

const execFileAsync = promisify(execFile);
export const dynamic = "force-dynamic";
type Counts = Record<string, number>;

function positiveEnvInt(name: string): number | null {
  const raw = process.env[name];
  if (!raw || !/^\d+$/.test(raw.trim())) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value > 0 ? value : null;
}

function evidenceCriteria() {
  const minClosed = positiveEnvInt("STINKY_PAPER_READINESS_MIN_CLOSED_OUTCOMES");
  const minMarket = positiveEnvInt("STINKY_PAPER_READINESS_MIN_MARKET_CAP_SAMPLES");
  const minClasses = positiveEnvInt("STINKY_PAPER_READINESS_MIN_OUTCOME_CLASSES");
  const configured = minClosed !== null && minMarket !== null && minClasses !== null && minClasses <= 3;
  return { configured, min_closed_outcomes: minClosed, min_market_cap_samples: minMarket, min_outcome_classes: minClasses };
}

async function psql(sql: string): Promise<string> {
  const { stdout } = await execFileAsync("docker", ["exec", "stinky-postgres", "psql", "-U", "stinky", "-d", "stinky", "-t", "-A", "-F", "|", "-c", sql], { timeout: 8_000, windowsHide: true, maxBuffer: 1024 * 1024 });
  return String(stdout || "").trim();
}

function rootCandidates(): string[] {
  return [process.cwd(), path.resolve(process.cwd(), "..", ".."), path.resolve(process.cwd(), "..", "..", "..")];
}

async function findRootFile(relative: string): Promise<string | null> {
  for (const root of rootCandidates()) {
    const candidate = path.join(root, relative);
    try { await readFile(candidate); return candidate; } catch { /* keep looking */ }
  }
  return null;
}

async function processAlive(pid: number): Promise<boolean> {
  if (!Number.isFinite(pid) || pid <= 0) return false;
  try {
    if (process.platform === "win32") {
      const { stdout } = await execFileAsync("tasklist", ["/FI", `PID eq ${pid}`], { timeout: 4_000, windowsHide: true });
      return String(stdout || "").includes(String(pid)) && !String(stdout || "").includes("No tasks");
    }
    process.kill(pid, 0); return true;
  } catch { return false; }
}

async function workerHealth() {
  const pidPath = await findRootFile(path.join("logs", "stinky-pids.txt"));
  if (!pidPath) return { producer: "UNKNOWN", runtime: "UNKNOWN" };
  const text = await readFile(pidPath, "utf8").catch(() => "");
  const pids: Record<string, number> = {};
  for (const line of text.split(/\r?\n/)) {
    const [name, rawPid] = line.split("=", 2);
    if (name && rawPid) pids[name.trim()] = Number(rawPid.trim());
  }
  const producerPid = pids["paper-intake-producer"];
  const runtimePid = pids["paper-runtime"];
  return {
    producer: producerPid ? ((await processAlive(producerPid)) ? "HEALTHY" : "DOWN") : "UNKNOWN",
    runtime: runtimePid ? ((await processAlive(runtimePid)) ? "HEALTHY" : "DOWN") : "UNKNOWN",
    producer_pid: producerPid || null, runtime_pid: runtimePid || null,
  };
}

async function policyStatus() {
  try {
    const raw = await psql("SELECT json_build_object('status','ACTIVE','version',r.policy_version,'horizon',r.horizon,'notional_usd',r.paper_notional_usd,'policy_sha256',r.policy_sha256,'provenance',CASE WHEN r.policy_payload->'provenance'->>'evidence_backed'='true' THEN 'EVIDENCE_BACKED' WHEN r.policy_payload->'provenance'->>'evidence_backed'='false' THEN 'MANUAL' ELSE 'UNKNOWN' END,'provenance_mode',COALESCE(r.policy_payload->'provenance'->>'mode','UNKNOWN'),'policy_identity',json_build_object('policy_version',r.policy_version,'policy_sha256',r.policy_sha256,'provenance',r.policy_payload->'provenance'),'activated_at',a.activated_at)::text FROM paper_policy_active a JOIN paper_policy_registry r ON r.policy_version=a.policy_version WHERE a.singleton=TRUE LIMIT 1;");
    if (!raw) return { status: "NOT_SET", version: null, horizon: null, notional_usd: null, policy_sha256: null, provenance: null, provenance_mode: null, policy_identity: null, activated_at: null };
    return JSON.parse(raw);
  } catch {
    return { status: "UNKNOWN", version: null, horizon: null, notional_usd: null, policy_sha256: null, provenance: null, provenance_mode: null, policy_identity: null, activated_at: null };
  }
}

export async function GET() {
  try {
    const criteria = evidenceCriteria();
    const workers = await workerHealth();
    // One bounded read-only psql process replaces the former concurrent docker-exec fan-out.
    // Keep policy and optional market-cap probes separate so their existing UNKNOWN/unavailable
    // failure semantics remain unchanged, while never running multiple docker psql probes at once.
    const snapshotRaw = await psql(`
      /* paper_status_snapshot */
      SELECT 'epoch|' || json_build_object('producer_version',producer_version,'prospective_started_at',prospective_started_at)::text FROM paper_intake_producer_state WHERE singleton=TRUE LIMIT 1;
      SELECT 'candidate|' || count(*)::text FROM paper_prospective_candidate;
      SELECT 'outcome|' || json_build_object('key',COALESCE(canonical_outcome,''),'value',count(*))::text FROM paper_prospective_candidate GROUP BY canonical_outcome ORDER BY canonical_outcome NULLS LAST;
      SELECT 'shadow|' || json_build_object('key',COALESCE(shadow_action,'UNKNOWN'),'value',count(*))::text FROM paper_runtime_record GROUP BY COALESCE(shadow_action,'UNKNOWN') ORDER BY COALESCE(shadow_action,'UNKNOWN');
      SELECT 'paper|' || json_build_object('key',paper_status,'value',count(*))::text FROM paper_runtime_record GROUP BY paper_status ORDER BY paper_status;
      SELECT 'intake|' || json_build_object('key',CASE WHEN processed_at IS NULL THEN 'UNPROCESSED' ELSE 'PROCESSED' END,'value',count(*))::text FROM paper_runtime_intake GROUP BY CASE WHEN processed_at IS NULL THEN 'UNPROCESSED' ELSE 'PROCESSED' END ORDER BY 1;
      SELECT 'evidence|' || json_build_object('closed',count(*) FILTER (WHERE canonical_outcome IN ('RUNNER','HELD','FADE')),'represented',count(DISTINCT canonical_outcome) FILTER (WHERE canonical_outcome IN ('RUNNER','HELD','FADE')),'first_candidate_at',min(decided_at),'latest_candidate_at',max(decided_at))::text FROM paper_prospective_candidate;
      SELECT 'cohort|' || json_build_object('policy_version',COALESCE(policy_version,'LEGACY_UNKNOWN'),'policy_sha256',COALESCE(policy_sha256,'UNKNOWN'),'provenance',CASE WHEN policy_evidence_backed IS TRUE THEN 'EVIDENCE_BACKED' WHEN policy_evidence_backed IS FALSE THEN 'MANUAL' ELSE 'UNKNOWN' END,'policy_identity',record->'policy_identity','records',count(*))::text FROM paper_runtime_record GROUP BY policy_version,policy_sha256,policy_evidence_backed,record->'policy_identity' ORDER BY min(created_at);
      SELECT 'registry|' || json_build_object('policy_version',r.policy_version,'policy_sha256',r.policy_sha256,'provenance',CASE WHEN r.policy_payload->'provenance'->>'evidence_backed'='true' THEN 'EVIDENCE_BACKED' WHEN r.policy_payload->'provenance'->>'evidence_backed'='false' THEN 'MANUAL' ELSE 'UNKNOWN' END,'provenance_mode',COALESCE(r.policy_payload->'provenance'->>'mode','UNKNOWN'),'policy_identity',json_build_object('policy_version',r.policy_version,'policy_sha256',r.policy_payload->'provenance'),'state',CASE WHEN a.policy_version IS NOT NULL THEN 'ACTIVE' ELSE 'PROVISIONED' END,'created_at',r.created_at,'activated_at',a.activated_at)::text FROM paper_policy_registry r LEFT JOIN paper_policy_active a ON a.singleton=TRUE AND a.policy_version=r.policy_version ORDER BY r.created_at DESC,r.policy_version DESC LIMIT 51;
    `);
    const policy = await policyStatus();
    const marketRaw = await psql("SELECT COALESCE(max(sample_count),0) FROM market_pattern_outcome_distributions WHERE status='CALIBRATED_EMPIRICAL';").catch(() => null);

    let producerVersion: string | null = null, prospectiveStartedAt: string | null = null, candidates = 0;
    const outcomes: Counts = {}, shadow: Counts = {}, paper: Counts = {}, intake: Counts = {};
    let evidenceClosed = 0, representedOutcomeClasses = 0, firstCandidateAt: string | null = null, latestCandidateAt: string | null = null;
    const policyCohorts: Record<string, unknown>[] = [], registryAll: Record<string, unknown>[] = [];
    for (const line of snapshotRaw.split(/\r?\n/).filter(Boolean)) {
      const separator = line.indexOf("|");
      if (separator < 0) continue;
      const tag = line.slice(0, separator), payload = line.slice(separator + 1);
      if (tag === "candidate") { candidates = Number(payload || 0) || 0; continue; }
      const value = JSON.parse(payload);
      if (tag === "epoch") { producerVersion = value.producer_version ?? null; prospectiveStartedAt = value.prospective_started_at ?? null; }
      else if (tag === "outcome" && value.key) outcomes[value.key] = Number(value.value || 0) || 0;
      else if (tag === "shadow" && value.key) shadow[value.key] = Number(value.value || 0) || 0;
      else if (tag === "paper" && value.key) paper[value.key] = Number(value.value || 0) || 0;
      else if (tag === "intake" && value.key) intake[value.key] = Number(value.value || 0) || 0;
      else if (tag === "evidence") { evidenceClosed = Number(value.closed || 0) || 0; representedOutcomeClasses = Number(value.represented || 0) || 0; firstCandidateAt = value.first_candidate_at ?? null; latestCandidateAt = value.latest_candidate_at ?? null; }
      else if (tag === "cohort") policyCohorts.push(value);
      else if (tag === "registry") registryAll.push(value);
    }
    const marketCapSamplesAvailable = marketRaw !== null;
    const marketCapSamples = marketCapSamplesAvailable ? (Number(marketRaw || 0) || 0) : null;
    const readiness = criteria.configured ? {
      status: "CRITERIA_CONFIGURED", criteria,
      deficits: {
        closed_outcomes_needed: Math.max(0, (criteria.min_closed_outcomes ?? 0) - evidenceClosed),
        outcome_classes_needed: Math.max(0, (criteria.min_outcome_classes ?? 0) - representedOutcomeClasses),
        market_cap_samples_needed: marketCapSamples === null ? null : Math.max(0, (criteria.min_market_cap_samples ?? 0) - marketCapSamples),
      },
      observed_market_cap_samples: marketCapSamples,
      market_cap_samples_available: marketCapSamplesAvailable,
      policy_provisioned: false, automatic_activation: false,
    } : { status: "CRITERIA_NOT_SET", criteria, deficits: null, observed_market_cap_samples: marketCapSamples, market_cap_samples_available: marketCapSamplesAvailable, policy_provisioned: false, automatic_activation: false };
    const closedOutcomes = (outcomes.RUNNER || 0) + (outcomes.HELD || 0) + (outcomes.FADE || 0);
    const policyRegistryTruncated = registryAll.length > 50;
    const policyRegistry = registryAll.slice(0, 50);
    return NextResponse.json({
      status: "OBSERVED", paper_only: true, live_trading: "LOCKED",
      producer: workers.producer, paper_runtime: workers.runtime,
      producer_pid: workers.producer_pid ?? null, runtime_pid: workers.runtime_pid ?? null,
      producer_version: producerVersion, prospective_started_at: prospectiveStartedAt, candidates,
      outcomes: { RUNNER: outcomes.RUNNER || 0, HELD: outcomes.HELD || 0, FADE: outcomes.FADE || 0, UNKNOWN: Math.max(0, candidates - closedOutcomes), closed: closedOutcomes },
      decisions: { WOULD_WATCH: shadow.WOULD_WATCH || 0, WOULD_SKIP: shadow.WOULD_SKIP || 0, WOULD_ENTER: shadow.WOULD_ENTER || 0, UNKNOWN: shadow.UNKNOWN || 0 },
      paper: { SIMULATED_OPEN: paper.SIMULATED_OPEN || 0, SIMULATED_CLOSED: paper.SIMULATED_CLOSED || 0, UNKNOWN: paper.UNKNOWN || 0 },
      intake: { processed: intake.PROCESSED || 0, unprocessed: intake.UNPROCESSED || 0 },
      policy,
      policy_registry: policyRegistry,
      policy_registry_scope: "LATEST_50_IMMUTABLE_POLICIES",
      policy_registry_truncated: policyRegistryTruncated,
      policy_cohorts: policyCohorts,
      aggregate_scope: "ALL_IMMUTABLE_POLICY_COHORTS",
      historical_identity_inference: false,
      prospective_evidence: {
        status: candidates > 0 ? "ACCUMULATING" : "AWAITING_CANDIDATES",
        closed_outcomes: evidenceClosed,
        pending_outcomes: Math.max(0, candidates - evidenceClosed),
        represented_outcome_classes: representedOutcomeClasses,
        first_candidate_at: firstCandidateAt || null,
        latest_candidate_at: latestCandidateAt || null,
        policy_threshold_proposal: criteria.configured ? "NOT_EVALUATED_ON_STATUS_SURFACE" : "REQUIRES_EXPLICIT_SUFFICIENCY_CRITERIA",
        thresholds_invented: false,
        readiness,
      },
      authority: { live_execution: false, trading_authority: false, rpc_contacted: false, transaction_signed: false, order_submitted: false, wallet_mutated: false },
    });
  } catch (error) {
    return NextResponse.json({ status: "UNKNOWN", paper_only: true, live_trading: "LOCKED", error: error instanceof Error ? error.message : "paper status unavailable", authority: { live_execution: false, trading_authority: false, rpc_contacted: false, transaction_signed: false, order_submitted: false, wallet_mutated: false } }, { status: 200 });
  }
}
