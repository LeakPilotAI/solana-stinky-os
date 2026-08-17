"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, ageFrom, fmtUsd, shortAddr } from "@/lib/api/client";
import type { Runner } from "@/types";
import { CopyButton } from "@/components/ui/CopyButton";

export default function RunnersPage() {
  const [items, setItems] = useState<Runner[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.runners(100);
      setItems(r.items || []);
      setError(null);
      setUpdatedAt(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <div className="p-4">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-sm font-medium uppercase tracking-wide text-terminal-dim">
            Live runners
          </h1>
          <p className="mt-1 text-2xs text-terminal-muted">
            Pump.fun mints from migration_tracks · live snapshots · 5s poll
          </p>
        </div>
        <div className="text-2xs text-terminal-muted">
          {loading ? "Loading…" : `${items.length} tracks`}
          {updatedAt && (
            <span className="ml-2">
              · updated {updatedAt.toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      {error && (
        <p className="mb-3 text-xs text-terminal-danger">API error: {error}</p>
      )}

      <div className="panel overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-2xs uppercase text-terminal-muted">
            <tr className="border-b border-terminal-border">
              <th className="px-3 py-2">Token</th>
              <th className="px-2 py-2">Age</th>
              <th className="px-2 py-2">Status</th>
              <th className="px-2 py-2">DEX</th>
              <th className="px-2 py-2">Vol 5m</th>
              <th className="px-2 py-2">Liq</th>
              <th className="px-2 py-2">Buyers</th>
              <th className="px-2 py-2">Trades</th>
              <th className="px-2 py-2">CA</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && !error && !loading && (
              <tr>
                <td
                  colSpan={9}
                  className="px-3 py-10 text-center text-terminal-muted"
                >
                  No migration tracks in store yet. Collector fills this as
                  migrations land.
                </td>
              </tr>
            )}
            {items.map((r) => (
              <tr
                key={r.mint}
                className="border-b border-terminal-border/50 hover:bg-terminal-elevated/40"
              >
                <td className="px-3 py-1.5">
                  <Link
                    href={`/tokens/${r.mint}`}
                    className="hover:text-terminal-accent"
                  >
                    {r.symbol || r.name || shortAddr(r.mint)}
                  </Link>
                </td>
                <td className="px-2 py-1.5 tabular">
                  {ageFrom(r.migration_at)}
                </td>
                <td className="px-2 py-1.5 text-terminal-dim">
                  {r.status || "—"}
                </td>
                <td className="px-2 py-1.5 text-terminal-dim">
                  {r.dex_id || "—"}
                </td>
                <td className="px-2 py-1.5 tabular">
                  {fmtUsd(r.volume_m5_usd)}
                </td>
                <td className="px-2 py-1.5 tabular">
                  {fmtUsd(r.liquidity_usd)}
                </td>
                <td className="px-2 py-1.5 tabular">
                  {r.meaningful_buyers ?? r.buyers_captured ?? "—"}
                </td>
                <td className="px-2 py-1.5 tabular">
                  {r.trades_observed ?? "—"}
                </td>
                <td className="px-2 py-1.5">
                  <div className="flex items-center gap-1">
                    <code className="mono text-2xs">{shortAddr(r.mint)}</code>
                    <CopyButton value={r.mint} label="CA" />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
