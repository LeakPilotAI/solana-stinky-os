"use client";

import { useRef, useState } from "react";

type Report = {
  status: string;
  reasons?: string[];
  selected_policy?: { policy_version: string; policy_sha256: string; evidence_backed: boolean };
  provenance_classification?: string;
  as_of?: string;
  structurally_eligible?: boolean;
  available_for_walk_forward?: number;
  counts?: { total_immutable_records: number; closed_simulations: number; open_simulation_records: number; not_simulated_records: number } | null;
  earliest_closed_record?: string | null;
  latest_closed_record?: string | null;
  release_criteria_supplied?: boolean;
  walk_forward_evaluated: boolean;
  walk_forward?: { status: string; release_gate_result?: string; mean_net_return_pct_after_costs?: number; win_rate?: number; maximum_drawdown_pct_of_deployed_notional?: number } | null;
};

export function PaperCohortReport() {
  const [version, setVersion] = useState("");
  const [sha, setSha] = useState("");
  const [provenance, setProvenance] = useState("");\n  const [asOf, setAsOf] = useState("");\n  const [minimumClosed, setMinimumClosed] = useState("");\n  const [minimumMean, setMinimumMean] = useState("");\n  const [maximumDrawdown, setMaximumDrawdown] = useState("");\n  const [minimumWinRate, setMinimumWinRate] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const reset = () => { generation.current += 1; setReport(null); setBusy(false); };
  const releaseCriteria = () => {\n    if (!/^\\d+$/.test(minimumClosed.trim()) || Number(minimumClosed) <= 0) return null;\n    const mean = Number(minimumMean), drawdown = Number(maximumDrawdown), win = Number(minimumWinRate);\n    if (!minimumMean.trim() || !maximumDrawdown.trim() || !minimumWinRate.trim() || !Number.isFinite(mean) || !Number.isFinite(drawdown) || drawdown < 0 || !Number.isFinite(win) || win < 0 || win > 1) return null;\n    return { minimum_closed_trades: Number(minimumClosed), minimum_mean_net_return_pct: mean, maximum_drawdown_pct: drawdown, minimum_win_rate: win };\n  };\n  const load = async (evaluate = false) => {
    const requestId = ++generation.current;
    setBusy(true); setReport(null);
    try {
      const response = await fetch("/api/paper-cohort-report", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ policy_version: version.trim(), policy_sha256: sha.trim(),
          evidence_backed: provenance === "EVIDENCE_BACKED", as_of: new Date(asOf.trim()).toISOString() }),
        cache: "no-store", signal: AbortSignal.timeout(12_000),
      });
      if (!response.ok) throw new Error("unavailable");
      const value = await response.json() as Report;
      if (requestId === generation.current) setReport(value);
    } catch {
      if (requestId === generation.current) setReport({ status: "UNKNOWN", reasons: ["cohort_evidence_unavailable"], walk_forward_evaluated: false });
    } finally {
      if (requestId === generation.current) setBusy(false);
    }
  };
  const cutoffValid = asOf.trim().length > 0 && !Number.isNaN(new Date(asOf.trim()).getTime());\n  const valid = version.trim().length > 0 && /^[0-9a-f]{64}$/.test(sha.trim()) && provenance !== "" && cutoffValid;
  const inputClass = "rounded border border-terminal-border bg-[#080a08] px-2 py-1 font-mono text-terminal-text";
  return (
    <details className="mt-2 rounded border border-terminal-border bg-[#0c0e0c] px-3 py-2 text-[10px] text-terminal-muted">
      <summary className="cursor-pointer font-semibold text-terminal-text">Single-policy release evidence</summary>
      <p className="mt-2">Explicit immutable cohort only. Copy the full SHA and version from the cohort list. This inspection supplies no release criteria and does not run walk-forward evaluation. The cutoff is explicit; Genesis does not substitute the current time.</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <label>Policy version <input aria-label="Cohort policy version" className={inputClass} value={version} onChange={e => { setVersion(e.target.value); reset(); }} /></label>
        <label>Full policy SHA <input aria-label="Cohort policy SHA" className={`${inputClass} w-64`} value={sha} onChange={e => { setSha(e.target.value); reset(); }} /></label>
        <label>Provenance <select aria-label="Cohort provenance" className={inputClass} value={provenance} onChange={e => { setProvenance(e.target.value); reset(); }}>
          <option value="">Select explicitly</option><option value="MANUAL">MANUAL</option><option value="EVIDENCE_BACKED">EVIDENCE_BACKED</option>
        </select></label>
        <button type="button" disabled={!valid || busy} onClick={() => load(false)} className="rounded border border-terminal-border px-2 py-1 text-terminal-text disabled:opacity-40">{busy ? "Loading…" : "Inspect selected cohort"}</button>
      </div>
      <div className="mt-2 flex flex-wrap gap-2 rounded border border-terminal-border p-2">\n        <span className="w-full font-semibold text-terminal-dim">Explicit release criteria — blank means no evaluation</span>\n        <label>Min closed <input aria-label="Minimum closed trades" className={`${inputClass} w-20`} value={minimumClosed} onChange={e => { setMinimumClosed(e.target.value); reset(); }} /></label>\n        <label>Min mean net return % <input aria-label="Minimum mean net return percent" className={`${inputClass} w-24`} value={minimumMean} onChange={e => { setMinimumMean(e.target.value); reset(); }} /></label>\n        <label>Max drawdown % <input aria-label="Maximum drawdown percent" className={`${inputClass} w-24`} value={maximumDrawdown} onChange={e => { setMaximumDrawdown(e.target.value); reset(); }} /></label>\n        <label>Min win rate 0–1 <input aria-label="Minimum win rate" className={`${inputClass} w-20`} value={minimumWinRate} onChange={e => { setMinimumWinRate(e.target.value); reset(); }} /></label>\n        <button type="button" disabled={!valid || releaseCriteria() === null || busy} onClick={() => load(true)} className="rounded border border-terminal-border px-2 py-1 text-terminal-text disabled:opacity-40">Evaluate explicit criteria</button>\n      </div>\n      {report ? <div className="mt-2 space-y-1" role="status">
        <p className={report.status === "OBSERVED" ? "text-terminal-text" : "text-amber-300"}>{report.status} · {report.provenance_classification || "UNKNOWN"}</p>
        {report.selected_policy ? <p className="break-all font-mono">{report.selected_policy.policy_version} · {report.selected_policy.policy_sha256} · evidence_backed={String(report.selected_policy.evidence_backed)}</p> : null}
        {report.counts ? <p>{report.counts.total_immutable_records} immutable records · {report.counts.closed_simulations} closed simulations · {report.counts.open_simulation_records} open simulation records · {report.counts.not_simulated_records} not simulated</p> : null}
        {report.counts ? <p>Open records are historical entries, not a count of currently open positions.</p> : null}
        {report.status === "OBSERVED" ? <p>Available for walk-forward: {report.available_for_walk_forward} · Structurally eligible: {report.structurally_eligible ? "YES" : "NO"}</p> : null}
        {report.earliest_closed_record ? <p>Closed evidence: {report.earliest_closed_record} through {report.latest_closed_record}</p> : null}
        {report.as_of ? <p>As of {report.as_of}</p> : null}
        <p>Release criteria: {report.release_criteria_supplied ? "SUPPLIED" : "NOT SUPPLIED"} · Walk-forward: {report.walk_forward_evaluated ? "EVALUATED" : "NOT EVALUATED"}</p>
        {report.reasons?.length ? <p className="text-amber-300">{report.reasons.join(", ")}</p> : null}
        <p>No automatic activation or live trading authority.</p>
      </div> : null}
    </details>
  );
}
