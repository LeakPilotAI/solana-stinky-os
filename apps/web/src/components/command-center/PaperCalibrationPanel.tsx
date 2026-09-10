"use client";

import { useEffect, useState } from "react";

type Status = {
  status?: string;
  producer?: string;
  paper_runtime?: string;
  producer_version?: string | null;
  prospective_started_at?: string | null;
  candidates?: number;
  outcomes?: { RUNNER?: number; HELD?: number; FADE?: number; UNKNOWN?: number; closed?: number };
  decisions?: { WOULD_WATCH?: number; WOULD_SKIP?: number; WOULD_ENTER?: number; UNKNOWN?: number };
  paper?: { SIMULATED_OPEN?: number; SIMULATED_CLOSED?: number; UNKNOWN?: number };
  intake?: { processed?: number; unprocessed?: number };
  policy?: { status?: string; version?: string | null; horizon?: string | null; notional_usd?: number | null };
  live_trading?: string;
  error?: string;
};

function tone(value?: string) {
  const v = String(value || "UNKNOWN").toUpperCase();
  if (["HEALTHY", "OBSERVED", "CONFIGURED", "ACTIVE"].includes(v)) return "text-emerald-400";
  if (["DOWN", "FAILED"].includes(v)) return "text-rose-400";
  if (["NOT_SET", "UNKNOWN", "LOCKED"].includes(v)) return "text-amber-300";
  return "text-terminal-muted";
}

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-md border border-terminal-border bg-[#0c0e0c] px-3 py-2">
      <div className="text-[9px] font-semibold uppercase tracking-[0.14em] text-terminal-dim">{label}</div>
      <div className={`mt-1 font-mono text-[13px] ${typeof value === "string" ? tone(value) : "text-terminal-text"}`}>{value}</div>
      {hint ? <div className="mt-0.5 text-[10px] text-terminal-muted">{hint}</div> : null}
    </div>
  );
}

export function PaperCalibrationPanel() {
  const [data, setData] = useState<Status | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch("/api/paper-status", { cache: "no-store", signal: AbortSignal.timeout(10_000) });
        const body = (await res.json()) as Status;
        if (!cancelled) setData(body);
      } catch (e) {
        if (!cancelled) setData({ status: "UNKNOWN", live_trading: "LOCKED", error: e instanceof Error ? e.message : "status unavailable" });
      }
    };
    load();
    const timer = setInterval(load, 15_000);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  const d = data || {};
  const o = d.outcomes || {};
  const s = d.decisions || {};
  const p = d.paper || {};

  return (
    <section className="shrink-0 border-b border-terminal-border bg-[#080a08] px-4 py-3">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-terminal-dim">Paper / Calibration</div>
          <div className="mt-1 text-[10px] text-terminal-muted">Prospective evidence only. T0 is frozen. UNKNOWN stays UNKNOWN. No live trading authority.</div>
        </div>
        <div className={`font-mono text-[10px] ${tone(d.live_trading)}`}>LIVE {d.live_trading || "LOCKED"}</div>
      </div>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
        <Stat label="Producer" value={d.producer || "UNKNOWN"} hint={d.producer_version || undefined} />
        <Stat label="Paper runtime" value={d.paper_runtime || "UNKNOWN"} />
        <Stat label="Prospective candidates" value={d.candidates ?? 0} hint={d.prospective_started_at ? `since ${d.prospective_started_at.slice(0, 19)}` : "epoch not observed"} />
        <Stat label="Closed outcomes" value={o.closed ?? 0} hint={`R/H/F/U ${o.RUNNER ?? 0}/${o.HELD ?? 0}/${o.FADE ?? 0}/${o.UNKNOWN ?? 0}`} />
        <Stat label="WOULD_WATCH" value={s.WOULD_WATCH ?? 0} />
        <Stat label="WOULD_SKIP" value={s.WOULD_SKIP ?? 0} />
        <Stat label="WOULD_ENTER" value={s.WOULD_ENTER ?? 0} />
        <Stat label="Paper policy" value={d.policy?.status || "NOT_SET"} hint={d.policy?.version || "explicit policy not provisioned"} />
      </div>

      <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
        <Stat label="Open paper" value={p.SIMULATED_OPEN ?? 0} />
        <Stat label="Closed paper" value={p.SIMULATED_CLOSED ?? 0} />
        <Stat label="Intake queue" value={d.intake?.unprocessed ?? 0} hint={`${d.intake?.processed ?? 0} processed`} />
        <Stat label="Policy horizon / notional" value={d.policy?.horizon || "UNKNOWN"} hint={d.policy?.notional_usd != null ? `$${d.policy.notional_usd} paper notional` : "not configured"} />
      </div>

      {d.error ? <div className="mt-2 rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[10px] text-amber-300">Status surface: {d.error}</div> : null}
    </section>
  );
}
