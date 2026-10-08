"use client";
import { useEffect, useState } from "react";
import { fetchSupervisor, type SupervisorResponse } from "@/lib/api/supervisor-passes";
const seconds = (n: number | null) => n === null ? "UNAVAILABLE" : `${n.toFixed(3)}s`;
export function SupervisorStatusView({ data, loading = false, error = false }: { data: SupervisorResponse | null; loading?: boolean; error?: boolean }) {
  const e = !loading && !error && data?.status === "OBSERVED" ? data : null;
  return <section aria-labelledby="v2-supervisor-title" aria-busy={loading} className="mt-4 space-y-2 break-words rounded border border-terminal-border p-2 text-[11px] text-terminal-muted">
    <h3 id="v2-supervisor-title" className="font-semibold text-terminal-text">Supervisor pass observations</h3>
    {!e ? <p role="status">{loading ? "Loading supervisor snapshot…" : "Supervisor data UNAVAILABLE. No pass records inferred."}</p> : <>
      <p>Read-only · paper-only · live authority locked. <time dateTime={e.as_of} className="break-all font-mono">Snapshot {e.as_of}</time></p>
      <p className="text-amber-300">Pass metadata {e.freshness.status} · age {seconds(e.freshness.age_sec)}. Collection capture {e.collection_freshness.status} · age {seconds(e.collection_freshness.age_sec)} (latest 50 plan mints).</p>
      <p>Last successful complete pass: <span className="break-all font-mono">{e.last_successful_pass?.finished_at ?? "UNAVAILABLE"}</span></p>
      <p>Retained events {e.scope.retained_events}/100 · {e.scope.truncated ? "PARTIAL TAIL" : "retained sample"} · duplicates {e.scope.duplicate_events} · failures {e.recent_failures} · partial pairs {e.partial_passes} · intervals &gt;30s {e.large_observed_intervals}.</p>
      <p>Host UTC supervisor clocks. Local state matching is not live process verification. Observer IDs are not experiment sessions. Gaps do not prove downtime, recovery or source coverage.</p>
      {e.passes.length === 0 ? <p>No recorded passes in this observed snapshot.</p> : <details><summary className="cursor-pointer text-terminal-text">Recent recorded passes (maximum 20)</summary>
        <ol className="mt-2 space-y-2">{e.passes.map(p => <li key={p.pass_id} className="min-w-0 rounded border border-terminal-border p-2">
          <p className="text-amber-300">{p.pair_state} · {p.phase} · exit {p.exit_code ?? "UNAVAILABLE"} · {p.wall_clock_order}</p>
          <dl className="mt-1 grid gap-1 sm:grid-cols-2"><div><dt>Start</dt><dd className="break-all font-mono">{p.started_at ?? "UNAVAILABLE"}</dd></div><div><dt>Completion</dt><dd className="break-all font-mono">{p.finished_at ?? "UNAVAILABLE"}</dd></div><div><dt>Monotonic duration</dt><dd>{seconds(p.duration_sec)}</dd></div><div><dt>Observed sleep interval</dt><dd>{seconds(p.sleep_interval_sec)}</dd></div></dl>
          <p className="mt-1 break-all font-mono">Supervisor PID {p.supervisor_pid} · observer {p.observer_id} · pass {p.pass_id}</p>
        </li>)}</ol>
      </details>}
      <p>1 MB input / 100 events / 20 passes. Intervals derive from recorded wall-clock boundaries, not independent sleep timers. Stale or partial metadata is not a downtime verdict.</p>
    </>}
  </section>;
}
export function SupervisorPassStatus({ revision }: { revision: number }) {
  const [data, setData] = useState<SupervisorResponse | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState(false);
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController(); setLoading(true); setData(null); setError(false);
    void fetchSupervisor(controller.signal).then(next => { if (!cancelled) setData(next); }).catch(() => { if (!cancelled) setError(true); }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; controller.abort(); };
  }, [revision]);
  return <SupervisorStatusView data={data} loading={loading} error={error} />;
}
