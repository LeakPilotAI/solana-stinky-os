import { NextResponse } from "next/server";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { readFile } from "node:fs/promises";
import path from "node:path";

const execFileAsync = promisify(execFile);
export const dynamic = "force-dynamic";
type Counts = Record<string, number>;

async function psql(sql: string): Promise<string> {
  const { stdout } = await execFileAsync("docker", ["exec", "stinky-postgres", "psql", "-U", "stinky", "-d", "stinky", "-t", "-A", "-F", "|", "-c", sql], { timeout: 8_000, windowsHide: true, maxBuffer: 1024 * 1024 });
  return String(stdout || "").trim();
}

function parseCountRows(raw: string): Counts {
  const out: Counts = {};
  for (const line of raw.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const [key, value] = line.split("|");
    if (key) out[key] = Number(value || 0) || 0;
  }
  return out;
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
    const raw = await psql("SELECT r.policy_version,r.horizon,r.paper_notional_usd,r.policy_sha256,a.activated_at::text FROM paper_policy_active a JOIN paper_policy_registry r ON r.policy_version=a.policy_version WHERE a.singleton=TRUE LIMIT 1;");
    if (!raw) return { status: "NOT_SET", version: null, horizon: null, notional_usd: null, policy_sha256: null, activated_at: null };
    const [version, horizon, notional, sha, activatedAt] = raw.split("|", 5);
    return { status: "ACTIVE", version: version || null, horizon: horizon || null, notional_usd: notional ? Number(notional) : null, policy_sha256: sha || null, activated_at: activatedAt || null };
  } catch {
    return { status: "UNKNOWN", version: null, horizon: null, notional_usd: null, policy_sha256: null, activated_at: null };
  }
}

export async function GET() {
  try {
    const [workers, policy, epochRaw, candidateRaw, outcomeRaw, shadowRaw, paperRaw, intakeRaw] = await Promise.all([
      workerHealth(), policyStatus(),
      psql("SELECT producer_version || '|' || prospective_started_at::text FROM paper_intake_producer_state WHERE singleton=TRUE LIMIT 1;"),
      psql("SELECT count(*) FROM paper_prospective_candidate;"),
      psql("SELECT canonical_outcome, count(*) FROM paper_prospective_candidate GROUP BY canonical_outcome ORDER BY canonical_outcome NULLS LAST;"),
      psql("SELECT COALESCE(shadow_action,'UNKNOWN'), count(*) FROM paper_runtime_record GROUP BY COALESCE(shadow_action,'UNKNOWN') ORDER BY 1;"),
      psql("SELECT paper_status, count(*) FROM paper_runtime_record GROUP BY paper_status ORDER BY paper_status;"),
      psql("SELECT CASE WHEN processed_at IS NULL THEN 'UNPROCESSED' ELSE 'PROCESSED' END, count(*) FROM paper_runtime_intake GROUP BY 1 ORDER BY 1;"),
    ]);
    const [producerVersion, prospectiveStartedAt] = epochRaw ? epochRaw.split("|", 2) : [null, null];
    const outcomes = parseCountRows(outcomeRaw), shadow = parseCountRows(shadowRaw), paper = parseCountRows(paperRaw), intake = parseCountRows(intakeRaw);
    const candidates = Number(candidateRaw || 0) || 0;
    const closedOutcomes = (outcomes.RUNNER || 0) + (outcomes.HELD || 0) + (outcomes.FADE || 0);
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
      authority: { live_execution: false, trading_authority: false, rpc_contacted: false, transaction_signed: false, order_submitted: false, wallet_mutated: false },
    });
  } catch (error) {
    return NextResponse.json({ status: "UNKNOWN", paper_only: true, live_trading: "LOCKED", error: error instanceof Error ? error.message : "paper status unavailable", authority: { live_execution: false, trading_authority: false, rpc_contacted: false, transaction_signed: false, order_submitted: false, wallet_mutated: false } }, { status: 200 });
  }
}
