"use client";
import { useEffect, useState } from "react";
import { fetchV2Details, type V2DetailResponse } from "@/lib/api/intelligence-execution-v2-details";
import { SupervisorPassStatus } from "./SupervisorPassStatus";

const seconds = (n: number | null) => n === null ? "UNAVAILABLE" : `${n.toFixed(3)}s`;
const labels: Record<string, string> = { detection_to_admission: "Detection → admission", decision_to_admission: "Decision → admission",
  entry_observation_delay: "Entry target → bound observation", exit_observation_delay: "Exit target → bound observation", maturity_to_recording: "Maturity → result recording" };
const freshLabels: Record<string, string> = { bound_entry: "Latest bound entry", bound_exit: "Latest bound exit", terminal_recording: "Latest result recording", selected_mint_capture: "Latest capture for selected mints" };

export function V2DetailsView({ data, loading = false, error = false }: { data: V2DetailResponse | null; loading?: boolean; error?: boolean }) {
  const evidence = !loading && !error && data?.status === "OBSERVED" ? data : null;
  if (!evidence) return <p role="status" className="py-3 text-xs text-terminal-muted">{loading ? "Loading evidence details…" : "Details unavailable. No measurements can be inferred."}</p>;
  return <div className="mt-3 space-y-4 break-words text-[11px] text-terminal-muted">
    <p>Prospective paper evidence · read-only · live authority locked. Snapshot at <time dateTime={evidence.as_of} className="break-all font-mono">{evidence.as_of}</time>.</p>
    <p className="text-amber-300">Latest {evidence.scope.sampled_plans} plans · limit 500 · {evidence.scope.truncated ? "PARTIAL SAMPLE — older plans excluded" : "All currently admitted plans fit this sample"}. Summary adequacy is unchanged.</p>
    {evidence.scope.sampled_plans === 0 ? <p>No admitted plan evidence yet. Unavailable measurements remain unavailable.</p> : null}
    <section aria-labelledby="v2-reasons"><h3 id="v2-reasons" className="font-semibold text-terminal-text">Recorded reasons</h3>
      {evidence.reasons.length ? <ul className="mt-2 space-y-2">{evidence.reasons.map(r => <li key={`${r.status}-${r.reason}`} className="rounded border border-terminal-border p-2"><span className="text-amber-300">{r.status} · {r.count}</span><code className="ml-2 break-all">{r.reason}</code></li>)}</ul> : <p className="mt-2">No recorded missingness or rejection reasons in this sample.</p>}
      <p className="mt-2">UNKNOWN {evidence.counts.UNKNOWN} · REJECTED {evidence.counts.REJECTED} · PENDING {evidence.counts.PENDING} · PAPER_PRICED {evidence.counts.PAPER_PRICED}. Reasons are never inferred or revised.</p>
    </section>
    <section aria-labelledby="v2-availability"><h3 id="v2-availability" className="font-semibold text-terminal-text">Bound observation availability</h3>
      <p className="mt-2">Entry {evidence.bound_observations.entry} · exit {evidence.bound_observations.exit} · unavailable {evidence.bound_observations.unavailable} / {evidence.scope.sampled_plans} plans.</p>
      <p>Only PAPER_PRICED results bind snapshot identities. Unpriced observation clocks are unavailable; REJECTED remains REJECTED.</p>
    </section>
    <div className="overflow-x-auto rounded border border-terminal-border"><table className="w-full min-w-[580px] text-left tabular-nums">
      <caption className="p-2 text-left font-semibold text-terminal-text">Latency (seconds) · nearest-rank p90 · small sample, descriptive only</caption>
      <thead><tr>{["Measurement", "n", "Unavailable", "Median", "p90", "Maximum"].map(h => <th scope="col" key={h} className="p-2 font-medium">{h}</th>)}</tr></thead>
      <tbody>{Object.entries(evidence.latency).map(([key, s]) => <tr key={key} className="border-t border-terminal-border"><th scope="row" className="p-2 font-normal">{labels[key]}</th><td className="p-2">{s.n}</td><td className="p-2">{s.unavailable}</td><td className="p-2">{seconds(s.median_sec)}</td><td className="p-2">{seconds(s.p90_sec)}</td><td className="p-2">{seconds(s.max_sec)}</td></tr>)}</tbody>
    </table></div>
    <section aria-labelledby="v2-freshness"><h3 id="v2-freshness" className="font-semibold text-terminal-text">Evidence freshness at snapshot</h3>
      <dl className="mt-2 grid gap-2 sm:grid-cols-2">{Object.entries(evidence.freshness).map(([key, f]) => <div key={key} className="min-w-0 rounded border border-terminal-border p-2"><dt>{freshLabels[key]}</dt><dd className="mt-1 break-all font-mono text-amber-300">{f.status} · {seconds(f.age_sec)}</dd></div>)}</dl>
      <p className="mt-2">300s is a diagnostic freshness threshold, not a policy window. Old terminal evidence alone does not prove worker downtime. Captures cover selected-plan mints only.</p>
    </section>
    <section aria-labelledby="v2-continuity"><h3 id="v2-continuity" className="font-semibold text-terminal-text">Pending results and collection continuity</h3>
      <p className="mt-2">Awaiting maturity {evidence.pending.awaiting_maturity} · mature without result {evidence.pending.mature_without_result}. Both remain PENDING.</p>
      <p>Session ends: UNAVAILABLE · worker downtime: UNESTABLISHED. Recorded starts do not prove continuous coverage.</p>
      <ul className="mt-2 space-y-1">{evidence.session_starts.map(s => <li key={s} className="break-all font-mono">{s}</li>)}</ul>
      <dl className="mt-2 grid gap-2 sm:grid-cols-2">{Object.entries(evidence.collection.logs).map(([name, log]) => <div key={name} className="min-w-0 rounded border border-terminal-border p-2"><dt className="capitalize">{name} log support</dt><dd>{log.status} · {log.tail_truncated ? "partial tail" : "retained file"} · activity {log.log_activity?.status ?? "UNAVAILABLE"}</dd><dd>V2 success lines {log.v2_success_lines ?? "UNAVAILABLE"}; success timestamps UNAVAILABLE.</dd><dd>Heartbeat {evidence.collection.heartbeats[name]?.status ?? "UNAVAILABLE"}; process identity unverified here.</dd></div>)}</dl>
    </section>
    <section aria-labelledby="v2-coverage"><h3 id="v2-coverage" className="font-semibold text-terminal-text">Current source coverage for missing windows</h3>
      <p className="mt-2">At most 20 windows, 100 captures each. {evidence.missing_windows_truncated ? "Additional missing windows excluded." : "All missing windows in the selected sample fit this limit."} Current captures cannot reconstruct ingestion history or repair outcomes.</p>
      <ul className="mt-2 space-y-2">{evidence.source_coverage.map(s => <li key={s.plan_id} className="rounded border border-terminal-border p-2"><p>Plan {s.plan_id} · <code className="break-all">{s.reason}</code></p><p>Window captures {s.captured_in_window} · bracketing gap {seconds(s.bracketing_gap_sec)}{s.truncated ? " · PARTIAL CAPTURE SAMPLE" : ""}</p><time dateTime={s.target} className="break-all font-mono">Target {s.target}</time></li>)}</ul>
    </section>
    <section aria-labelledby="v2-correlations"><h3 id="v2-correlations" className="font-semibold text-terminal-text">Rate-limit correlations · NONCAUSAL</h3>
      <p className="mt-2">Service-wide matching log lines, not mint-specific cause or unique incidents. Reads capped at 1 MB per log; uncovered windows remain unavailable.</p>
      <ul className="mt-2 space-y-1">{evidence.rate_limit_correlations.map(c => <li key={c.plan_id}>Plan {c.plan_id} · coincident rate-limit lines {c.rate_limit_lines ?? "UNAVAILABLE"}</li>)}</ul>
    </section>
    <ul className="space-y-1 border-t border-terminal-border pt-3">{evidence.limitations.map(s => <li key={s}>{s}</li>)}</ul>
  </div>;
}

export function IntelligenceExecutionV2Details() {
  const [open, setOpen] = useState(false), [revision, setRevision] = useState(0);
  const [data, setData] = useState<V2DetailResponse | null>(null), [loading, setLoading] = useState(false), [error, setError] = useState(false);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true); setData(null); setError(false);
    void fetchV2Details(controller.signal).then(next => { if (!cancelled) setData(next); })
      .catch(() => { if (!cancelled) { setData(null); setError(true); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; controller.abort(); };
  }, [open, revision]);
  return <details onToggle={event => setOpen(event.currentTarget.open)} className="mt-3 border-t border-terminal-border pt-3">
    <summary className="cursor-pointer text-[11px] font-semibold text-terminal-text">Reasons, latency and collection details</summary>
    {open ? <><button type="button" onClick={() => setRevision(r => r+1)} disabled={loading} className="mt-3 max-w-full rounded border border-terminal-border px-3 py-1 text-left text-[11px] text-terminal-text disabled:opacity-50">Refresh detail snapshot</button><SupervisorPassStatus revision={revision} /><V2DetailsView data={data} loading={loading} error={error} /></> : null}
  </details>;
}
