import { V2_SHA, V2_VERSION } from "./intelligence-execution-v2";

type Freshness = { status: "RECENT" | "STALE" | "UNAVAILABLE" | "CLOCK_INCONSISTENT"; age_sec: number | null; latest_at: string | null };
type Distribution = { n: number; unavailable: number; median_sec: number | null; p90_sec: number | null; max_sec: number | null };
export type V2Details = {
  status: "OBSERVED"; as_of: string;
  scope: { sampled_plans: number; plan_limit: number; truncated: boolean; selection: string };
  counts: Record<"PAPER_PRICED" | "UNKNOWN" | "REJECTED" | "PENDING", number>;
  reasons: { status: "UNKNOWN" | "REJECTED"; reason: string; count: number }[];
  bound_observations: { entry: number; exit: number; unavailable: number };
  latency: Record<string, Distribution>;
  freshness: Record<string, Freshness>;
  pending: { awaiting_maturity: number; mature_without_result: number };
  session_starts: string[]; session_ends: string; worker_downtime: string;
  source_coverage: { plan_id: number; reason: string; target: string; captured_in_window: number; bracketing_gap_sec: number | null; truncated: boolean }[];
  missing_windows_truncated: boolean;
  rate_limit_correlations: { plan_id: number; rate_limit_lines: number | null; retained_window_covered: boolean; causal: false }[];
  collection: { log_byte_limit: number; heartbeats: Record<string, { status: string }>;
    logs: Record<string, { status: string; tail_truncated?: boolean; v2_success_lines: number | null; log_activity?: Freshness }> };
  limitations: string[];
};
export type V2DetailResponse = V2Details | { status: "UNAVAILABLE" };
const obj = (v: unknown): Record<string, unknown> => {
  if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error("Invalid detail evidence");
  return v as Record<string, unknown>;
};
const count = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const numberOrNull = (v: unknown): boolean => v === null || (typeof v === "number" && Number.isFinite(v) && v >= 0);
const stamp = (v: unknown): boolean => typeof v === "string" && /(?:Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v));
function bad(): never { throw new Error("V2 detail evidence could not be verified"); }
function fresh(v: unknown) {
  const f = obj(v);
  if (!["RECENT", "STALE", "UNAVAILABLE", "CLOCK_INCONSISTENT"].includes(String(f.status))) bad();
  if (f.status === "UNAVAILABLE") { if (f.age_sec !== null || f.latest_at !== null) bad(); }
  else if (!stamp(f.latest_at) || typeof f.age_sec !== "number" || !Number.isFinite(f.age_sec)
      || (f.status === "CLOCK_INCONSISTENT" ? f.age_sec >= 0 : f.age_sec < 0)
      || (f.status === "RECENT" && f.age_sec > 300) || (f.status === "STALE" && f.age_sec <= 300)) bad();
}
export function parseV2Details(value: unknown): V2DetailResponse {
  const r = obj(value);
  if (r.status === "UNAVAILABLE") return { status: "UNAVAILABLE" };
  if (r.status !== "OBSERVED" || !stamp(r.as_of) || r.policy_version !== V2_VERSION || r.policy_sha256 !== V2_SHA
      || r.prospective_boundary !== "2026-10-07T11:51:36.391317+00:00" || r.paper_only !== true || r.read_only !== true
      || ["live_execution", "trading_authority", "order_submitted", "transaction_signed", "wallet_mutated", "performance_validation"].some(k => r[k] !== false)
      || r.quantile_method !== "NEAREST_RANK_P90" || r.freshness_threshold_sec !== 300) bad();
  const scope = obj(r.scope), counts = obj(r.counts), bound = obj(r.bound_observations), pending = obj(r.pending);
  if (!count(scope.sampled_plans) || scope.sampled_plans > 500 || scope.plan_limit !== 500 || scope.selection !== "LATEST_PLAN_IDS" || typeof scope.truncated !== "boolean"
      || !Object.values(counts).every(count) || Object.keys(counts).sort().join() !== "PAPER_PRICED,PENDING,REJECTED,UNKNOWN"
      || Object.values(counts).reduce<number>((a, b) => a + (b as number), 0) !== scope.sampled_plans
      || bound.entry !== counts.PAPER_PRICED || bound.exit !== counts.PAPER_PRICED || bound.unavailable !== scope.sampled_plans - (counts.PAPER_PRICED as number)
      || !count(pending.awaiting_maturity) || !count(pending.mature_without_result) || pending.awaiting_maturity + pending.mature_without_result !== counts.PENDING) bad();
  if (!Array.isArray(r.reasons) || r.reasons.length > 500) bad();
  for (const value of r.reasons) {
    const reason = obj(value);
    if (!["UNKNOWN", "REJECTED"].includes(String(reason.status)) || typeof reason.reason !== "string" || !reason.reason || reason.reason.length > 200 || !count(reason.count)) bad();
  }
  const latency = obj(r.latency);
  if (Object.keys(latency).sort().join() !== ["detection_to_admission", "decision_to_admission", "entry_observation_delay", "exit_observation_delay", "maturity_to_recording"].sort().join()) bad();
  for (const value of Object.values(latency)) {
    const s = obj(value);
    if (!count(s.n) || !count(s.unavailable) || s.n + s.unavailable !== scope.sampled_plans
        || ![s.median_sec, s.p90_sec, s.max_sec].every(numberOrNull)
        || (s.n === 0 ? [s.median_sec, s.p90_sec, s.max_sec].some(v => v !== null) : [s.median_sec, s.p90_sec, s.max_sec].some(v => v === null))
        || (s.n > 0 && ((s.median_sec as number) > (s.p90_sec as number) || (s.p90_sec as number) > (s.max_sec as number)))) bad();
  }
  for (const key of ["entry_observation_delay", "exit_observation_delay"]) if (obj(latency[key]).n !== counts.PAPER_PRICED || (obj(latency[key]).max_sec as number | null) !== null && (obj(latency[key]).max_sec as number) > 30) bad();
  if (obj(latency.detection_to_admission).n !== 0 || obj(latency.decision_to_admission).n !== scope.sampled_plans
      || obj(latency.maturity_to_recording).n !== scope.sampled_plans - (counts.PENDING as number)) bad();
  const freshness = obj(r.freshness);
  if (Object.keys(freshness).sort().join() !== "bound_entry,bound_exit,selected_mint_capture,terminal_recording") bad();
  Object.values(freshness).forEach(fresh);
  if (!Array.isArray(r.session_starts) || !r.session_starts.every(stamp) || r.session_ends !== "UNAVAILABLE" || r.worker_downtime !== "UNESTABLISHED") bad();
  if (!Array.isArray(r.source_coverage) || r.source_coverage.length > 20 || r.source_coverage_limit !== 20 || typeof r.missing_windows_truncated !== "boolean") bad();
  for (const value of r.source_coverage) {
    const s = obj(value);
    if (!count(s.plan_id) || !stamp(s.target) || !["entry_observation_missing", "exit_observation_missing"].includes(String(s.reason))
        || !count(s.captured_in_window) || s.captured_in_window > 100 || !numberOrNull(s.bracketing_gap_sec) || typeof s.truncated !== "boolean"
        || s.cause !== "UNESTABLISHED" || s.ingestion_delay !== "UNAVAILABLE") bad();
  }
  if (!Array.isArray(r.rate_limit_correlations) || r.rate_limit_correlations.length !== r.source_coverage.length) bad();
  for (const value of r.rate_limit_correlations) {
    const c = obj(value);
    if (!count(c.plan_id) || !numberOrNull(c.rate_limit_lines) || typeof c.retained_window_covered !== "boolean" || c.causal !== false
        || (c.retained_window_covered ? !count(c.rate_limit_lines) : c.rate_limit_lines !== null)) bad();
  }
  const collection = obj(r.collection);
  if (collection.log_byte_limit !== 1_000_000) bad();
  const logs = obj(collection.logs), beats = obj(collection.heartbeats);
  for (const name of ["collector", "maintain"]) {
    const log = obj(logs[name]), beat = obj(beats[name]);
    if (!["OBSERVED", "UNAVAILABLE"].includes(String(log.status)) || !numberOrNull(log.v2_success_lines)
        || !["UNAVAILABLE", "UNVERIFIED_OR_STALE"].includes(String(beat.status))) bad();
    if (log.status === "OBSERVED") fresh(log.log_activity);
  }
  if (!Array.isArray(r.limitations) || !r.limitations.every(v => typeof v === "string")) bad();
  return r as unknown as V2Details;
}

export async function fetchV2Details(signal?: AbortSignal): Promise<V2DetailResponse> {
  const timeout = AbortSignal.timeout(10_000);
  const response = await fetch("/api/stinky/v1/intelligence/execution-v2/details", { method: "GET", cache: "no-store",
    headers: { Accept: "application/json" }, signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
  if (!response.ok) throw new Error("V2 details unavailable");
  return parseV2Details(await response.json());
}
