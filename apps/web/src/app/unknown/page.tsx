"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, fmtUsd, shortAddr } from "@/lib/api/client";

type Item = {
  mint?: string;
  symbol?: string | null;
  volume_m5_usd?: number | null;
  pipeline_status?: string | null;
  reason?: string | null;
};

export default function UnknownPage() {
  const [rows, setRows] = useState<Item[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let c = false;
    api
      .bookDesk()
      .then((d) => {
        if (c) return;
        const q = (d.unknown_queue || d.unknown || []) as Item[];
        setRows(Array.isArray(q) ? q : []);
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
    <div className="space-y-3 p-4">
      <header>
        <h1 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-terminal-dim">
          Unknown queue
        </h1>
        <p className="mt-1 text-[11px] text-terminal-muted">
          Gate 1 passed, evidence insufficient. Research queue — not a hide and not a buy.
        </p>
      </header>
      {error && <p className="text-xs text-rose-300">API: {error}</p>}
      {loading && <p className="text-xs text-terminal-muted">Loading desk…</p>}
      {!loading && rows.length === 0 && (
        <p className="panel p-8 text-center text-sm text-terminal-muted">
          No UNKNOWN investigations in the stored book.
        </p>
      )}
      {rows.length > 0 && (
        <ul className="panel divide-y divide-terminal-border text-[11px]">
          {rows.map((t, i) => (
            <li key={String(t.mint || i)} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              {t.mint ? (
                <Link href={`/tokens/${t.mint}`} className="font-mono text-terminal-accent hover:underline">
                  {t.symbol || shortAddr(t.mint, 4)}
                </Link>
              ) : (
                <span>UNKNOWN mint</span>
              )}
              <span className="tabular text-terminal-muted">{fmtUsd(t.volume_m5_usd ?? null)}</span>
              <span className="rounded border border-terminal-border px-1.5 py-0.5 text-[10px] uppercase text-terminal-muted">
                {t.pipeline_status || "UNKNOWN"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
