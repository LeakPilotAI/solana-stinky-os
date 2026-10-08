/** Read-only presentation of the frozen prospective experiment. */
export const V2_VERSION = "genesis-paper-execution-v2";
export const V2_SHA = "efb3ab5d544bef3604253e6f0afabcbfcdf7e38a351fd3e031730958950dfa81";
type Gate = { observed: number; required: number; passed: boolean };
export type ExecutionV2Evidence = {
  status: "OBSERVED";
  policy_version: string;
  policy_sha256: string;
  prospective_boundary: string;
  counts: { PAPER_PRICED: number; REJECTED: number; UNKNOWN: number; PENDING: number };
  distinct_mint_mature_plans: number;
  verified_runtime_sessions: number;
  priced_paths: number;
  unknown_fraction: number | null;
  adequacy_status: "INSUFFICIENT_EVIDENCE" | "DESCRIPTIVE_REVIEW_ELIGIBLE";
  evaluation_ready: boolean;
  adequacy_gates: {
    distinct_mint_mature_plans: Gate;
    verified_runtime_sessions: Gate;
    complete_priced_paths: Gate;
    unknown_fraction: { observed: number | null; required_max: number; passed: boolean };
  };
};
export type ExecutionV2 = ExecutionV2Evidence | { status: "UNKNOWN" };
const object = (v: unknown): Record<string, unknown> => {
  if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error("Invalid V2 evidence");
  return v as Record<string, unknown>;
};
const count = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;

export function parseExecutionV2(value: unknown): ExecutionV2 {
  const r = object(value);
  if (r.status === "UNKNOWN") return { status: "UNKNOWN" };
  if (r.status !== "OBSERVED" || r.policy_version !== V2_VERSION || r.policy_sha256 !== V2_SHA
      || r.prospective_boundary !== "2026-10-07T11:51:36.391317+00:00"
      || r.paper_only !== true || r.read_only !== true
      || ["live_execution", "trading_authority", "order_submitted", "transaction_signed", "wallet_mutated", "performance_validation"].some(k => r[k] !== false)) {
    throw new Error("V2 policy or safety markers could not be verified");
  }
  const counts = object(r.counts);
  if (!["PAPER_PRICED", "REJECTED", "UNKNOWN", "PENDING"].every(k => count(counts[k]))) throw new Error("Invalid V2 counts");
  const mature = (counts.PAPER_PRICED as number) + (counts.REJECTED as number) + (counts.UNKNOWN as number);
  const gates = object(r.adequacy_gates);
  const checks: [string, unknown, number][] = [
    ["distinct_mint_mature_plans", r.distinct_mint_mature_plans, 100],
    ["verified_runtime_sessions", r.verified_runtime_sessions, 5],
    ["complete_priced_paths", object(gates.complete_priced_paths).observed, 80],
  ];
  let ready = true;
  for (const [key, observed, required] of checks) {
    const gate = object(gates[key]);
    if (!count(observed) || gate.observed !== observed || gate.required !== required || gate.passed !== (observed >= required)) throw new Error("Invalid V2 adequacy gate");
    ready = ready && gate.passed === true;
  }
  const fraction = mature ? (counts.UNKNOWN as number) / mature : null;
  const unknownGate = object(gates.unknown_fraction);
  const unknownPass = fraction !== null && fraction <= 0.2;
  if (r.unknown_fraction !== fraction || unknownGate.observed !== fraction || unknownGate.required_max !== 0.2 || unknownGate.passed !== unknownPass
      || r.priced_paths !== counts.PAPER_PRICED || (r.distinct_mint_mature_plans as number) > mature
      || (object(gates.complete_priced_paths).observed as number) > (counts.PAPER_PRICED as number)) throw new Error("Inconsistent V2 evidence");
  ready = ready && unknownPass;
  if (r.evaluation_ready !== ready || r.adequacy_status !== (ready ? "DESCRIPTIVE_REVIEW_ELIGIBLE" : "INSUFFICIENT_EVIDENCE")) throw new Error("Inconsistent V2 readiness");
  return r as unknown as ExecutionV2Evidence;
}

export async function fetchExecutionV2(signal?: AbortSignal): Promise<ExecutionV2> {
  const timeout = AbortSignal.timeout(10_000);
  const response = await fetch("/api/stinky/v1/intelligence/execution-v2", {
    method: "GET", headers: { Accept: "application/json" }, cache: "no-store",
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
  });
  if (!response.ok) throw new Error("V2 evidence connection unavailable");
  return parseExecutionV2(await response.json());
}
