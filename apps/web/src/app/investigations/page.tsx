"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, fmtUsd, shortAddr } from "@/lib/api/client";

type Row = {
  mint?: string;
  symbol?: string | null;
  protocol?: string | null;
  gate1_at?: string | null;
  volume_5m_at_gate?: number | null;
  investigation_status?: string | null;
  tick_count?: number | null;
  observed_slice_count?: number | null;
  outcome?: string | null;
  outcome_label?: string | null;
  completeness?: number | null;
};

export default function InvestigationsPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [source, setSource] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let c = false;
    (async () => {
      try {
        const r = await api.bookObservations();
        if (!c) {
          setRows((r.observations || []) as Row[]);
          setSource(r.source || "");
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

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-terminal-border px-4 py-3">
        <h1 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-terminal-dim">
          Investigations
        </h1>
        <p className="mt-1 text-[11px] text-terminal-muted">
          Gate 1 passed. Not an alert. One row per mint from stored investigations.
          {source ? ` Source: ${source}.` : ""}
        </p>
      </header>
      {error && (
        <p className="border-b border-rose-500/30 bg-rose-500/10 px-4 py-2 text-xs text-rose-300">
          API: {error}
        </p>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        {loading && <p className="p-8 text-center text-sm text-terminal-muted">Loading store…</p>}
        {!loading && rows.length === 0 && (
          <p className="p-8 text-center text-sm text-terminal-muted">
            No Gate 1 investigations stored. Empty is empty.
          </p>
        )}
        {rows.length > 0 && (
          <table className="w-full text-left text-[11px]">
            <thead className="sticky top-0 border-b border-terminal-border bg-[#0a0c0a] text-[9px] uppercase tracking-wider text-terminal-muted">
              <tr>
                <th className="px-3 py-2">Gate 1</th>
                <th className="px-2 py-2">Mint</th>
                <th className="px-2 py-2">5m vol</th>
                <th className="px-2 py-2">Status</th>
                <th className="px-2 py-2">Ticks</th>
                <th className="px-2 py-2">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={String(r.mint)} className="border-b border-terminal-border/40">
                  <td className="px-3 py-1.5 font-mono text-terminal-dim">
                    {(r.gate1_at || "").slice(0, 19) || "—"}
                  </td>
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
                  <td className="px-2 py-1.5">{r.investigation_status || "UNKNOWN"}</td>
                  <td className="px-2 py-1.5 tabular">{r.observed_slice_count ?? r.tick_count ?? 0}</td>
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
