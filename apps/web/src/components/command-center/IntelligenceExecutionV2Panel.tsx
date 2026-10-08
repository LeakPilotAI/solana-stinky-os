"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import type { ExecutionV2 } from "@/lib/api/intelligence-execution-v2";
import { IntelligenceExecutionV2Details } from "./IntelligenceExecutionV2Details";

function Gate({ label, observed, required, passed }: { label: string; observed: number; required: number; passed: boolean }) {
  return <div className="rounded-lg border border-terminal-border bg-black/20 p-3">
    <div className="flex justify-between gap-2 text-[11px] text-terminal-muted"><span>{label}</span><span className={passed ? "text-emerald-300" : "text-amber-300"}>{passed ? "MET" : "NOT MET"}</span></div>
    <div className="my-2 font-mono text-lg text-terminal-text">{observed} <span className="text-xs text-terminal-dim">/ {required} required</span></div>
    <progress aria-label={label} value={Math.min(observed, required)} max={required} className="h-1.5 w-full overflow-hidden rounded bg-terminal-border [&::-webkit-progress-bar]:bg-terminal-border [&::-webkit-progress-value]:bg-amber-400 [&::-moz-progress-bar]:bg-amber-400" />
  </div>;
}

export function IntelligenceExecutionV2View({ data, loading = false, error = false }: { data: ExecutionV2 | null; loading?: boolean; error?: boolean }) {
  const evidence = !loading && !error && data?.status === "OBSERVED" ? data : null;
  const ready = evidence?.evaluation_ready === true;
  return <section aria-labelledby="execution-v2-title" aria-busy={loading} className="mx-2.5 mt-2.5 rounded-xl border border-terminal-border bg-[#0a0e0a] p-3 lg:mx-3 lg:mt-3 lg:p-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 id="execution-v2-title" className="text-xs font-semibold uppercase tracking-wider text-terminal-text">Intelligence Execution V2</h2>
        <p className="mt-1 text-[11px] text-terminal-muted">Frozen prospective experiment · snapshot-based paper observations</p></div>
      <span className="rounded border border-amber-400/30 bg-amber-400/5 px-2 py-1 text-[10px] font-semibold tracking-wide text-amber-300">PAPER-ONLY · LIVE AUTHORITY LOCKED</span>
    </div>
    <div role="status" aria-live="polite" className="mt-3 text-[11px] text-amber-300">
      {loading ? "Loading V2 evidence…" : !evidence ? "EVIDENCE UNAVAILABLE · NOT EVALUATION READY" : ready ? "DESCRIPTIVE REVIEW ELIGIBLE" : "INSUFFICIENT EVIDENCE · NOT EVALUATION READY"}
    </div>
    {evidence ? <>
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <Gate label="Mature distinct mints" {...evidence.adequacy_gates.distinct_mint_mature_plans} />
        <Gate label="Verified runtime sessions" {...evidence.adequacy_gates.verified_runtime_sessions} />
        <Gate label="Distinct priced paths" {...evidence.adequacy_gates.complete_priced_paths} />
        <div className="rounded-lg border border-terminal-border bg-black/20 p-3">
          <div className="flex justify-between gap-2 text-[11px] text-terminal-muted"><span>UNKNOWN fraction</span><span className={evidence.adequacy_gates.unknown_fraction.passed ? "text-emerald-300" : "text-amber-300"}>{evidence.adequacy_gates.unknown_fraction.passed ? "MET" : "NOT MET"}</span></div>
          <div className="my-2 font-mono text-lg text-terminal-text">{evidence.unknown_fraction === null ? "—" : `${(evidence.unknown_fraction * 100).toFixed(1)}%`} <span className="text-xs text-terminal-dim">/ ≤20% maximum</span></div>
          <p className="text-[10px] text-terminal-dim">Missing evidence remains UNKNOWN.</p>
        </div>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {(["PAPER_PRICED", "REJECTED", "UNKNOWN", "PENDING"] as const).map(status => <div key={status} className="min-w-0 rounded border border-terminal-border px-3 py-2"><dt className="break-all text-[10px] tracking-wide text-terminal-muted">{status}</dt><dd className="mt-1 font-mono text-sm text-terminal-text">{evidence.counts[status]}</dd></div>)}
      </dl>
      {Object.values(evidence.counts).every(count => count === 0) ? <p className="mt-3 text-[11px] text-terminal-muted">No admitted plans observed yet.</p> : null}
      <div className="mt-3 space-y-1 text-[10px] text-terminal-muted">
        <p className="break-all">Frozen policy · <span className="font-mono text-terminal-text">{evidence.policy_version}</span></p>
        <p className="break-all">Prospective boundary · <time dateTime={evidence.prospective_boundary} className="font-mono text-terminal-text">{evidence.prospective_boundary}</time></p>
        <details><summary className="cursor-pointer py-1">Policy SHA256</summary><p className="break-all font-mono">{evidence.policy_sha256}</p></details>
      </div>
    </> : <p className="mt-3 text-[11px] text-terminal-muted">{loading ? "Waiting for the evidence service." : "The evidence service is disconnected or has no verifiable V2 summary. Metrics are unavailable."}</p>}
    <IntelligenceExecutionV2Details />
    <p className="mt-3 border-t border-terminal-border pt-3 text-[10px] leading-relaxed text-terminal-muted">Adequacy permits descriptive paper review only. Snapshot proxies do not establish profitability, validated predictions or executable fills. No live trading, order submission, signing or wallet mutation.</p>
  </section>;
}

export function IntelligenceExecutionV2Panel() {
  const [data, setData] = useState<ExecutionV2 | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const load = async () => {
      try {
        const next = await api.intelligenceExecutionV2(controller.signal);
        if (!cancelled) { setData(next); setError(false); }
      } catch {
        if (!cancelled) { setData(null); setError(true); }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    const timer = setInterval(load, 60_000);
    return () => { cancelled = true; controller.abort(); clearInterval(timer); };
  }, []);
  return <IntelligenceExecutionV2View data={data} loading={loading} error={error} />;
}
