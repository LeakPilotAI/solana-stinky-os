export type Pass = { pass_id: string; observer_id: string; supervisor_pid: number; started_at: string | null; finished_at: string | null;
  phase: "START" | "FINISH" | "RAISED"; pair_state: "COMPLETE" | "START_ONLY" | "END_ONLY"; exit_code: number | null;
  duration_sec: number | null; wall_clock_order: "ORDERED" | "REGRESSION" | "UNAVAILABLE"; sleep_interval_sec: number | null; matches_current_state: boolean | null };
type Fresh = { status: "RECENT" | "STALE" | "UNAVAILABLE" | "CLOCK_INCONSISTENT"; age_sec: number | null; latest_at: string | null };
export type SupervisorEvidence = { status: "OBSERVED"; as_of: string; clock_owner: "HOST_UTC_SUPERVISOR";
  scope: { byte_limit: number; event_limit: number; pass_limit: number; retained_events: number; truncated: boolean; duplicate_events: number };
  freshness: Fresh; collection_freshness: Fresh & { scope: "LATEST_50_PLAN_MINTS"; as_of: string | null };
  passes: Pass[]; last_successful_pass: Pass | null; recent_failures: number; partial_passes: number; large_observed_intervals: number };
export type SupervisorResponse = SupervisorEvidence | { status: "UNAVAILABLE" };
function bad(): never { throw new Error("Supervisor observations could not be verified"); }
function obj(v: unknown): Record<string, unknown> { if (!v || typeof v !== "object" || Array.isArray(v)) bad(); return v as Record<string, unknown>; }
const count = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const numberOrNull = (v: unknown) => v === null || typeof v === "number" && Number.isFinite(v) && v >= 0;
const stamp = (v: unknown) => typeof v === "string" && /(?:Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v));
const uuid = (v: unknown) => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
const earlier = (a: string, b: string) => {
  const x = Date.parse(a), y = Date.parse(b);
  const remainder = (v: string) => Number((v.match(/\.(\d+)/)?.[1] ?? "").padEnd(6, "0").slice(3, 6));
  return x < y || x === y && remainder(a) < remainder(b);
};
function fresh(value: unknown) {
  const f = obj(value);
  if (!["RECENT", "STALE", "UNAVAILABLE", "CLOCK_INCONSISTENT"].includes(String(f.status))) bad();
  if (f.status === "UNAVAILABLE") { if (f.latest_at !== null || f.age_sec !== null) bad(); }
  else if (!stamp(f.latest_at) || typeof f.age_sec !== "number" || !Number.isFinite(f.age_sec)
      || (f.status === "CLOCK_INCONSISTENT" ? f.age_sec >= 0 : f.age_sec < 0)
      || (f.status === "RECENT" && f.age_sec > 300) || (f.status === "STALE" && f.age_sec <= 300)) bad();
}
function pass(value: unknown) {
  const p = obj(value);
  if (!uuid(p.pass_id) || !uuid(p.observer_id) || !count(p.supervisor_pid) || p.supervisor_pid === 0
      || ![null, true, false].includes(p.matches_current_state as null | boolean)
      || !["START", "FINISH", "RAISED"].includes(String(p.phase)) || !["COMPLETE", "START_ONLY", "END_ONLY"].includes(String(p.pair_state))
      || !["ORDERED", "REGRESSION", "UNAVAILABLE"].includes(String(p.wall_clock_order))
      || ![p.started_at, p.finished_at].every(v => v === null || stamp(v))
      || !(p.exit_code === null || typeof p.exit_code === "number" && Number.isSafeInteger(p.exit_code))
      || !numberOrNull(p.duration_sec) || !numberOrNull(p.sleep_interval_sec)) bad();
  if (p.pair_state === "START_ONLY" && (p.phase !== "START" || p.finished_at !== null || p.exit_code !== null || p.duration_sec !== null || p.wall_clock_order !== "UNAVAILABLE")) bad();
  if (p.pair_state === "END_ONLY" && (p.phase === "START" || p.started_at !== null)) bad();
  if (p.pair_state === "COMPLETE" && p.phase === "START" || p.phase === "RAISED" && p.exit_code !== null) bad();
  if (p.started_at && p.finished_at && p.wall_clock_order !== (earlier(String(p.finished_at), String(p.started_at)) ? "REGRESSION" : "ORDERED")) bad();
}
export function parseSupervisor(value: unknown): SupervisorResponse {
  const r = obj(value);
  if (r.status === "UNAVAILABLE") return { status: "UNAVAILABLE" };
  if (r.status !== "OBSERVED" || !stamp(r.as_of) || r.clock_owner !== "HOST_UTC_SUPERVISOR" || r.experiment_evidence !== false
      || r.process_identity_verified !== false || r.downtime !== "UNESTABLISHED" || r.interval_warning_sec !== 30
      || r.paper_only !== true || r.read_only !== true
      || ["live_execution", "trading_authority", "order_submitted", "transaction_signed", "wallet_mutated", "performance_validation"].some(k => r[k] !== false)) bad();
  const scope = obj(r.scope);
  if (scope.byte_limit !== 1_000_000 || scope.event_limit !== 100 || scope.pass_limit !== 20 || !count(scope.retained_events) || scope.retained_events > 100
      || typeof scope.truncated !== "boolean" || !count(scope.duplicate_events) || !Array.isArray(r.passes) || r.passes.length > 20) bad();
  r.passes.forEach(pass);
  const ids = r.passes.map(p => String(obj(p).pass_id)); if (new Set(ids).size !== ids.length) bad();
  for (const key of ["recent_failures", "partial_passes", "large_observed_intervals"]) if (!count(r[key]) || r[key] > 100) bad();
  fresh(r.freshness); fresh(r.collection_freshness);
  const collection = obj(r.collection_freshness);
  if (collection.scope !== "LATEST_50_PLAN_MINTS" || !(collection.as_of === null || stamp(collection.as_of))) bad();
  if (r.last_successful_pass !== null) {
    pass(r.last_successful_pass); const p = obj(r.last_successful_pass);
    if (p.exit_code !== 0 || p.phase !== "FINISH" || p.pair_state !== "COMPLETE" || p.wall_clock_order !== "ORDERED" || p.matches_current_state !== true || !stamp(p.finished_at)) bad();
  }
  return r as unknown as SupervisorEvidence;
}
export async function fetchSupervisor(signal?: AbortSignal): Promise<SupervisorResponse> {
  const timeout = AbortSignal.timeout(10_000);
  const response = await fetch("/api/stinky/v1/intelligence/execution-v2/supervisor-passes", { method: "GET", cache: "no-store", headers: { Accept: "application/json" }, signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
  if (!response.ok) throw new Error("Supervisor data unavailable");
  return parseSupervisor(await response.json());
}
