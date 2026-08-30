"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, fmtUsd, shortAddr } from "@/lib/api/client";

type Row = {
  mint?: string;
  symbol?: string | null;
  gate1_at?: string | null;
  volume_5m_at_gate?: number | null;
  tick_count?: number | null;
  observed_slice_count?: number | null;
  completeness?: number | null;
  outcome?: string | null;
  outcome_label?: string | null;
};

export default function ObservationsPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [source, setSource] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let c = false;
    api
      .bookObservations()
      .then((r) => {
        if (c) return;
        setRows((r.observations || []) as Row[]);
        setSource(r.source || "");
      })
      .catch((e) => {
        if (!c) setError(e instanceof Error ? e.message : "failed");
      })
      .finally(() => {
        if (!c) setLoading(false);
      });
    return () => {
      c = true;
    };
  }, []);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-terminal-border px-4 py-3">
        <h1 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-terminal-dim">
          Observation book
        </h1>
        <p className="mt-1 text-[11px] text-terminal-muted">
          One row per Gate 1 mint. Completeness is observed slices, not interpolated.
          {source ? ` Source: ${source}.` : ""}
        </p>
      </header>
      {error && (
        <p className="border-b border-rose-500/30 bg-rose-500/10 px-4 py-2 text-xs text-rose-300">API: {error}</p>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        {loading && <p className="p-8 text-center text-sm text-terminal-muted">Loading store…</p>}
        {!loading && rows.length === 0 && (
          <p className="p-8 text-center text-sm text-terminal-muted">Book empty. Not fabricated.</p>
        )}
        {rows.length > 0 && (
          <table className="w-full text-left text-[11px]">
            <thead className="sticky top-0 border-b border-terminal-border bg-[#0a0c0a] text-[9px] uppercase tracking-wider text-terminal-muted">
              <tr>
                <th className="px-3 py-2">Gate 1</th>
                <th className="px-2 py-2">Mint</th>
                <th className="px-2 py-2">5m vol</th>
                <th className="px-2 py-2">Ticks</th>
                <th className="px-2 py-2">Complete</th>
                <th className="px-2 py-2">Later outcome</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={String(r.mint)} className="border-b border-terminal-border/40">
                  <td className="px-3 py-1.5 font-mono">{(r.gate1_at || "").slice(0, 19) || "—"}</td>
                  <td className="px-2 py-1.5">
                    {r.mint ? (
                      <Link href={`/tokens/${r.mint}`} className="font-mono text-terminal-accent hover:underline">
                        {r.symbol || shortAddr(r.mint, 4)}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-2 py-1.5 tabular">{fmtUsd(r.volume_5m_at_gate ?? null)}</td>
                  <td className="px-2 py-1.5 tabular">{r.observed_slice_count ?? r.tick_count ?? 0}</td>
                  <td className="px-2 py-1.5 tabular">
                    {r.completeness == null ? "UNKNOWN" : `${Math.round(Number(r.completeness) * 100)}%`}
                  </td>
                  <td className="px-2 py-1.5 text-terminal-muted">{r.outcome_label || r.outcome || "UNKNOWN"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
