"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { api, shortAddr } from "@/lib/api/client";
import type { TimeMachineResponse } from "@/types";
import { CopyButton } from "@/components/ui/CopyButton";

export default function TimeMachinePage() {
  const [mode, setMode] = useState<"wallet" | "entity">("wallet");
  const [query, setQuery] = useState("");
  const [data, setData] = useState<TimeMachineResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    const q = query.trim();
    if (!q) return;
    setLoading(true);
    setError(null);
    setData(null);
    try {
      const res =
        mode === "wallet"
          ? await api.timeMachineWallet(q)
          : await api.timeMachineEntity(q);
      setData(res);
      if (!res.available) setError(res.message || "No data");
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed");
    } finally {
      setLoading(false);
    }
  }

  const series = data?.series || [];
  const maxAct = useMemo(
    () => Math.max(1, ...series.map((s) => s.activity || 0)),
    [series]
  );
  const events = useMemo(() => {
    const list = [...(data?.events || [])];
    list.sort((a, b) => String(b.at || "").localeCompare(String(a.at || "")));
    return list;
  }, [data]);

  return (
    <div className="space-y-3 p-4">
      <div>
        <h1 className="text-sm font-medium uppercase tracking-wide text-terminal-dim">
          Time Machine
        </h1>
        <p className="mt-1 max-w-2xl text-xs text-terminal-muted">
          Replay measured launches, early buys, and trades over time. No invented
          historical scores — only what is in the event store.
        </p>
        {data?.engine && (
          <p className="mt-1 text-2xs text-terminal-muted mono">{data.engine}</p>
        )}
      </div>

      <div className="panel flex flex-wrap items-end gap-2 p-3">
        <div className="flex gap-1 text-2xs">
          {(["wallet", "entity"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`rounded border px-2 py-1 ${
                mode === m
                  ? "border-terminal-accent/50 bg-terminal-elevated"
                  : "border-terminal-border text-terminal-muted"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
        <input
          className="min-w-[280px] flex-1 rounded border border-terminal-border bg-terminal-bg px-2 py-1.5 font-mono text-xs"
          placeholder={
            mode === "wallet"
              ? "Wallet address"
              : "Entity UUID"
          }
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
        />
        <button
          type="button"
          onClick={run}
          disabled={loading || !query.trim()}
          className="rounded bg-terminal-accent/20 px-3 py-1.5 text-xs text-terminal-accent hover:bg-terminal-accent/30 disabled:opacity-40"
        >
          {loading ? "Loading…" : "Replay"}
        </button>
      </div>

      {error && <p className="text-xs text-terminal-danger">{error}</p>}

      {data?.available && data.summary && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
          <Stat label="Events" value={data.summary.event_count} />
          <Stat label="Days active" value={data.summary.days_active} />
          <Stat label="Launches" value={data.summary.launches} />
          <Stat label="Early buys" value={data.summary.early_buys} />
          <Stat label="Buys" value={data.summary.buys} />
          <Stat label="Sells" value={data.summary.sells} />
        </div>
      )}

      {data?.available && data.wallet && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-terminal-muted">Wallet</span>
          <code className="mono text-2xs">{data.wallet}</code>
          <CopyButton value={data.wallet} label="Copy" />
          <Link
            href={`/wallets/${data.wallet}`}
            className="text-terminal-accent hover:underline"
          >
            Wallet card →
          </Link>
          <Link
            href={`/graph`}
            className="text-terminal-muted hover:underline"
          >
            Graph
          </Link>
        </div>
      )}

      {data?.available && data.entity && (
        <div className="text-xs text-terminal-dim">
          Entity{" "}
          {data.entity.display_label || data.entity_id || data.entity.entity_id} ·
          launches {data.entity.launch_count ?? "—"} · conf{" "}
          {data.entity.confidence != null
            ? `${(Number(data.entity.confidence) * 100).toFixed(0)}%`
            : "—"}
        </div>
      )}

      {data?.score_series && data.score_series.length > 0 && (
        <div className="panel mb-4 p-3">
          <div className="mb-2 text-2xs uppercase text-terminal-muted">Score history</div>
          <div className="space-y-1">
            {data.score_series.map((s: any, i: number) => (
              <div key={i} className="flex justify-between text-xs tabular">
                <span className="text-terminal-dim">{String(s.captured_at || s.at || "").slice(0, 19)}</span>
                <span>score <strong>{Number(s.score).toFixed(1)}</strong>{s.confidence != null ? ` · conf ${(Number(s.confidence)*100).toFixed(0)}%` : ""}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Activity bars */}
      {series.length > 0 && (
        <div className="panel p-3">
          <div className="mb-2 text-2xs uppercase text-terminal-muted">
            Daily activity (launches ×3 + early ×2 + trades)
          </div>
          <div className="flex h-28 items-end gap-px overflow-x-auto">
            {series.map((s) => (
              <div
                key={s.day}
                className="group relative flex w-3 min-w-[6px] flex-col justify-end"
                title={`${s.day}: act=${s.activity} L=${s.launches} E=${s.early_buys} B=${s.buys} S=${s.sells}`}
              >
                <div
                  className="w-full rounded-t bg-terminal-accent/70"
                  style={{
                    height: `${Math.max(4, ((s.activity || 0) / maxAct) * 100)}%`,
                  }}
                />
              </div>
            ))}
          </div>
          <div className="mt-1 flex justify-between text-2xs text-terminal-muted">
            <span>{series[0]?.day}</span>
            <span>{series[series.length - 1]?.day}</span>
          </div>
        </div>
      )}

      {/* Cumulative table */}
      {series.length > 0 && (
        <div className="panel overflow-x-auto">
          <div className="border-b border-terminal-border px-3 py-2 text-2xs uppercase text-terminal-muted">
            Cumulative series
          </div>
          <table className="w-full text-left text-xs">
            <thead className="text-2xs text-terminal-muted">
              <tr className="border-b border-terminal-border">
                <th className="px-3 py-2">Day</th>
                <th className="px-2 py-2">Act</th>
                <th className="px-2 py-2">Σ Launch</th>
                <th className="px-2 py-2">Σ Early</th>
                <th className="px-2 py-2">Σ Buy</th>
                <th className="px-2 py-2">Σ Sell</th>
              </tr>
            </thead>
            <tbody>
              {series
                .slice()
                .reverse()
                .slice(0, 40)
                .map((s) => (
                  <tr
                    key={s.day}
                    className="border-b border-terminal-border/40"
                  >
                    <td className="px-3 py-1 mono text-2xs">{s.day}</td>
                    <td className="px-2 py-1 tabular">{s.activity}</td>
                    <td className="px-2 py-1 tabular">{s.cum_launches}</td>
                    <td className="px-2 py-1 tabular">{s.cum_early_buys}</td>
                    <td className="px-2 py-1 tabular">{s.cum_buys}</td>
                    <td className="px-2 py-1 tabular">{s.cum_sells}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Event log */}
      {events.length > 0 && (
        <div className="panel overflow-x-auto">
          <div className="border-b border-terminal-border px-3 py-2 text-2xs uppercase text-terminal-muted">
            Event stream (newest first)
          </div>
          <table className="w-full text-left text-xs">
            <thead className="text-2xs text-terminal-muted">
              <tr className="border-b border-terminal-border">
                <th className="px-3 py-2">When</th>
                <th className="px-2 py-2">Kind</th>
                <th className="px-2 py-2">Mint / note</th>
              </tr>
            </thead>
            <tbody>
              {events.slice(0, 80).map((e, i) => (
                <tr
                  key={`${e.at}-${e.kind}-${i}`}
                  className="border-b border-terminal-border/40"
                >
                  <td className="px-3 py-1 mono text-2xs text-terminal-dim">
                    {String(e.at || "").replace("T", " ").slice(0, 19)}
                  </td>
                  <td className="px-2 py-1 text-terminal-dim">{e.kind}</td>
                  <td className="px-2 py-1">
                    {e.mint ? (
                      <Link
                        href={`/tokens/${e.mint}`}
                        className="mono text-terminal-accent hover:underline"
                      >
                        {shortAddr(e.mint, 4)}
                      </Link>
                    ) : (
                      "—"
                    )}
                    {e.rank != null && (
                      <span className="ml-2 text-terminal-muted">
                        rank {e.rank}
                      </span>
                    )}
                    {e.name && (
                      <span className="ml-2 text-terminal-muted">{e.name}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value?: number }) {
  return (
    <div className="panel px-3 py-2">
      <div className="text-2xs uppercase text-terminal-muted">{label}</div>
      <div className="tabular text-lg font-semibold">{value ?? "—"}</div>
    </div>
  );
}
