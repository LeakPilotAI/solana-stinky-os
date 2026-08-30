"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, fmtUsd, shortAddr } from "@/lib/api/client";

type Desk = {
  system_status?: string;
  live_data_status?: string;
  migration_watch_status?: string;
  intel_version?: string;
  operator_version?: string;
  source?: string;
  evidence_label?: string;
  as_of?: string;
  note?: string;
  gate_status?: {
    threshold_usd?: number;
    clamp_usd?: number;
    live_gate1?: string;
    live_gate1_count?: number | null;
    note?: string;
  };
  last_observation?: { at?: string | null; mint?: string | null; kind?: string; evidence_label?: string };
  next_observation?: { label?: string; reason?: string };
  quality_state?: { current?: string; previous?: string | null; mint?: string | null; dips?: unknown[] };
  database?: { status?: string; note?: string; error?: string | null };
  discord?: { policy?: string; delivery?: string; note?: string };
  providers?: Record<string, { status?: string; error?: string | null }>;
  active_investigations?: Array<Record<string, unknown>>;
  active_watches?: Array<Record<string, unknown>>;
  investigations?: Array<Record<string, unknown>>;
};

function tone(s: string | undefined) {
  const u = (s || "UNKNOWN").toUpperCase();
  if (["UP", "CONNECTED", "OBSERVING", "SENT", "FIRED", "OBSERVED", "LIVE"].includes(u)) return "text-emerald-400";
  if (["DOWN", "FAILED"].includes(u)) return "text-rose-400";
  if (["DEGRADED", "WATCH", "DETERIORATING"].includes(u)) return "text-amber-300";
  return "text-terminal-muted";
}

function Cell({ label, value, hint }: { label: string; value?: string | number | null; hint?: string }) {
  const v = value == null || value === "" ? "UNKNOWN" : String(value);
  return (
    <div className="rounded-md border border-terminal-border bg-[#0c0e0c] px-3 py-2">
      <div className="text-[9px] font-semibold uppercase tracking-[0.14em] text-terminal-dim">{label}</div>
      <div className={`mt-1 font-mono text-[13px] ${tone(v)}`}>{v}</div>
      {hint ? <div className="mt-0.5 text-[10px] text-terminal-muted">{hint}</div> : null}
    </div>
  );
}

export default function OperatorPage() {
  const [desk, setDesk] = useState<Desk | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let c = false;
    (async () => {
      try {
        const d = (await api.operator()) as Desk;
        if (!c) {
          setDesk(d);
          setError(null);
        }
      } catch (e) {
        if (!c) setError(e instanceof Error ? e.message : "failed");
      } finally {
        if (!c) setLoading(false);
      }
    })();
    return () => {
      c = true;
    };
  }, []);

  const inv = (desk?.active_investigations || desk?.investigations || []) as Array<{
    mint?: string;
    symbol?: string | null;
    lifecycle?: string;
    gate_volume?: number | null;
    current_volume?: number | null;
    current_quality?: string;
    evidence_label?: string;
    watch_age_sec?: number | null;
    next_tick?: { label?: string };
    observation_count?: number;
  }>;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-terminal-border px-4 py-3">
        <h1 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-terminal-dim">Operator</h1>
        <p className="mt-1 text-[11px] text-terminal-muted">
          First live investigation desk. UNKNOWN is UNKNOWN. Policy fired is not delivery. Not a buy.
          {desk?.intel_version ? ` ${desk.intel_version}.` : ""}
        </p>
      </header>
      {error && (
        <p className="border-b border-rose-500/30 bg-rose-500/10 px-4 py-2 text-xs text-rose-300">API: {error}</p>
      )}
      {loading && <p className="p-8 text-center text-sm text-terminal-muted">Loading operator desk…</p>}
      {!loading && desk && (
        <div className="min-h-0 flex-1 space-y-3 overflow-auto p-4">
          <section className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Cell label="System" value={desk.system_status} hint={desk.source} />
            <Cell label="Live data" value={desk.live_data_status} hint="DexScreener" />
            <Cell label="Migration watch" value={desk.migration_watch_status} hint="Solana WS" />
            <Cell
              label="Gate 1"
              value={desk.gate_status?.live_gate1}
              hint={`$${Number(desk.gate_status?.threshold_usd || 150000) / 1000}k / clamp $${Number(desk.gate_status?.clamp_usd || 200000) / 1000}k`}
            />
            <Cell label="Database" value={desk.database?.status} hint={desk.database?.note} />
            <Cell label="Discord policy" value={desk.discord?.policy} hint="FIRED is not SENT" />
            <Cell label="Discord delivery" value={desk.discord?.delivery} />
            <Cell label="Quality" value={desk.quality_state?.current} />
          </section>
          <section className="grid gap-2 md:grid-cols-2">
            <div className="rounded-md border border-terminal-border px-3 py-2 text-[11px]">
              <div className="text-[9px] uppercase tracking-wider text-terminal-dim">Last observation</div>
              <p className="mt-1 font-mono">
                {desk.last_observation?.at || "UNKNOWN"} · {desk.last_observation?.kind || "UNKNOWN"} ·{" "}
                {desk.last_observation?.evidence_label || "UNKNOWN"}
              </p>
            </div>
            <div className="rounded-md border border-terminal-border px-3 py-2 text-[11px]">
              <div className="text-[9px] uppercase tracking-wider text-terminal-dim">Next observation</div>
              <p className="mt-1 font-mono">{desk.next_observation?.label || "UNKNOWN"}</p>
            </div>
          </section>
          <p className="text-[10px] text-terminal-dim">{desk.gate_status?.note} {desk.note}</p>
          <section className="overflow-hidden rounded-md border border-terminal-border">
            <header className="border-b border-terminal-border px-3 py-2 text-[9px] font-semibold uppercase tracking-wider text-terminal-dim">
              Investigations · {inv.length}
            </header>
            {inv.length === 0 ? (
              <p className="px-3 py-6 text-center text-[12px] text-terminal-muted">
                LIVE GATE-1: {desk.gate_status?.live_gate1 || "UNKNOWN"}. Empty is empty.
              </p>
            ) : (
              <table className="w-full text-left text-[11px]">
                <thead className="text-[9px] uppercase tracking-wider text-terminal-muted">
                  <tr>
                    <th className="px-3 py-2">Mint</th>
                    <th className="px-2 py-2">Lifecycle</th>
                    <th className="px-2 py-2">Gate vol</th>
                    <th className="px-2 py-2">Now vol</th>
                    <th className="px-2 py-2">Quality</th>
                    <th className="px-2 py-2">Next</th>
                    <th className="px-2 py-2">Label</th>
                  </tr>
                </thead>
                <tbody>
                  {inv.map((r) => (
                    <tr key={String(r.mint)} className="border-t border-terminal-border">
                      <td className="px-3 py-1.5 font-mono">
                        <Link href={`/tokens/${r.mint}`} className="hover:text-terminal-accent">
                          {r.symbol || shortAddr(String(r.mint || ""), 4)}
                        </Link>
                      </td>
                      <td className={`px-2 py-1.5 ${tone(r.lifecycle)}`}>{r.lifecycle}</td>
                      <td className="px-2 py-1.5">{fmtUsd(r.gate_volume ?? null)}</td>
                      <td className="px-2 py-1.5">{fmtUsd(r.current_volume ?? null)}</td>
                      <td className="px-2 py-1.5">{r.current_quality || "UNKNOWN"}</td>
                      <td className="px-2 py-1.5">{r.next_tick?.label || "UNKNOWN"}</td>
                      <td className="px-2 py-1.5">{r.evidence_label || "UNKNOWN"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
