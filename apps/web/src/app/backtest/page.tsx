"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, fmtPct, fmtUsd, shortAddr } from "@/lib/api/client";

type AnyObj = Record<string, unknown>;

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function pct(v: unknown): string {
  const n = num(v);
  if (n == null) return "—";
  if (n <= 1) return `${(n * 100).toFixed(0)}%`;
  return `${n.toFixed(0)}%`;
}

export default function BacktestPage() {
  const [funnel, setFunnel] = useState<AnyObj | null>(null);
  const [backtest, setBacktest] = useState<AnyObj | null>(null);
  const [outcomes, setOutcomes] = useState<AnyObj | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [minScore, setMinScore] = useState(55);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [f, b, o] = await Promise.all([
        api.replayFunnel().catch(() => null),
        api.replayBacktest(minScore, 200).catch(() => null),
        api.outcomes(40, false).catch(() => null),
      ]);
      setFunnel(f);
      setBacktest(b);
      setOutcomes(o as AnyObj | null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [minScore]);

  useEffect(() => {
    load();
  }, [load]);

  const funnelCounts = (funnel?.counts || funnel || {}) as AnyObj;
  const bt = backtest || {};
  const oc = outcomes || {};
  const items = (Array.isArray(oc.items) ? oc.items : []) as AnyObj[];

  return (
    <div className="flex h-full flex-col gap-3 overflow-auto bg-[#050705] p-3 lg:p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-sm font-semibold uppercase tracking-wider text-terminal-text">
            Backtest · Outcomes · Precision
          </h1>
          <p className="mt-1 text-[12px] text-terminal-muted">
            Measured from stored migrations, alerts, and market snapshots — no simulated fills.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-[11px] text-terminal-muted">
            Min score
            <input
              type="number"
              min={0}
              max={100}
              value={minScore}
              onChange={(e) => setMinScore(Number(e.target.value) || 55)}
              className="ml-2 w-16 rounded border border-terminal-border bg-[#0c100c] px-2 py-1 text-[12px] text-terminal-text"
            />
          </label>
          <button
            type="button"
            onClick={load}
            className="rounded-md border border-terminal-accent/40 bg-terminal-accent/15 px-3 py-1.5 text-[11px] font-semibold text-terminal-accent hover:bg-terminal-accent/25"
          >
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-terminal-danger/40 bg-terminal-danger/10 px-3 py-2 text-[12px] text-terminal-danger">
          {error}
        </div>
      )}

      {loading && !funnel && !backtest && (
        <div className="py-12 text-center text-sm text-terminal-muted">Loading measured metrics…</div>
      )}

      {/* Funnel */}
      <section className="rounded-xl border border-terminal-border bg-[#0a0e0a] p-4">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-terminal-muted">
          Replay funnel
        </h2>
        <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-6">
          {[
            ["Migrations", funnelCounts.migrations ?? funnelCounts.token_migrated],
            ["Tracks", funnelCounts.tracks ?? funnelCounts.migration_tracks],
            ["Buyers", funnelCounts.buyers ?? funnelCounts.migration_buyers],
            ["Alerts", funnelCounts.alerts ?? funnelCounts.alert_candidate],
            ["With volume", funnelCounts.with_volume],
            ["Gated", funnelCounts.gated ?? funnelCounts.gate_passed],
          ].map(([label, val]) => (
            <div
              key={String(label)}
              className="rounded-lg border border-terminal-border/70 bg-[#0d120d] px-3 py-2"
            >
              <div className="text-[9px] uppercase tracking-wide text-terminal-muted">
                {label}
              </div>
              <div className="mt-0.5 text-[18px] font-semibold tabular text-terminal-text">
                {val == null ? "—" : Number(val).toLocaleString()}
              </div>
            </div>
          ))}
        </div>
        {funnel?.engine != null && (
          <div className="mt-2 text-[10px] text-terminal-muted">
            Engine: {String(funnel.engine)}
          </div>
        )}
      </section>

      {/* Precision / backtest */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <section className="rounded-xl border border-terminal-border bg-[#0a0e0a] p-4">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-terminal-muted">
            Score-gate backtest
          </h2>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Stat label="Sample (unique mint)" value={bt.total_unique_mints ?? bt.sample_size ?? bt.n} />
            <Stat label="Gate passed" value={bt.gate_passed ?? bt.passed} />
            <Stat
              label="Runner rate"
              value={pct(bt.runner_rate ?? bt.precision_runner)}
              accent
            />
            <Stat label="Fade rate" value={pct(bt.fade_rate ?? bt.precision_fade)} />
            <Stat label="Min score used" value={bt.min_score ?? minScore} />
            <Stat label="Engine" value={bt.engine ?? "—"} />
          </div>
          {bt.error != null && (
            <p className="mt-2 text-[11px] text-terminal-danger">{String(bt.error)}</p>
          )}
          {!bt.engine && !loading && (
            <p className="mt-2 text-[11px] text-terminal-muted">
              No backtest payload yet — need alert.candidate + market_snapshots history.
            </p>
          )}
        </section>

        <section className="rounded-xl border border-terminal-border bg-[#0a0e0a] p-4">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-terminal-muted">
            Alert outcomes summary
          </h2>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Stat label="Outcomes" value={oc.count ?? items.length} />
            <Stat
              label="Runner rate"
              value={pct(
                (oc as AnyObj).runner_rate ??
                  (oc as AnyObj).precision_runner ??
                  ((oc as AnyObj).rates
                    ? ((oc as AnyObj).rates as AnyObj).runner
                    : null)
              )}
              accent
            />
            <Stat
              label="Available"
              value={oc.available === false ? "no" : "yes"}
            />
            <Stat label="Source" value={(oc as AnyObj).source ?? (oc as AnyObj).engine ?? "—"} />
          </div>
        </section>
      </div>

      {/* Outcome rows */}
      <section className="min-h-0 flex-1 overflow-hidden rounded-xl border border-terminal-border bg-[#0a0e0a]">
        <div className="flex items-center justify-between border-b border-terminal-border px-4 py-2.5">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider">
            Recent labeled outcomes
          </h2>
          <span className="text-[10px] text-terminal-muted">{items.length} rows</span>
        </div>
        <div className="overflow-auto">
          <table className="w-full text-left text-[12px]">
            <thead className="sticky top-0 bg-[#0a0e0a] text-[9px] uppercase tracking-wide text-terminal-muted">
              <tr className="border-b border-terminal-border">
                <th className="px-3 py-2">Mint</th>
                <th className="px-2 py-2">Label</th>
                <th className="px-2 py-2">Score</th>
                <th className="px-2 py-2">Peak vol</th>
                <th className="px-2 py-2">Peak mcap</th>
                <th className="px-2 py-2">When</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-terminal-muted">
                    No outcomes stored yet. Gated alerts + later snapshots produce labels
                    (runner / fade / mid / unknown).
                  </td>
                </tr>
              )}
              {items.map((row, i) => {
                const mint = String(row.mint || "");
                const label = String(row.label || row.outcome || "unknown");
                return (
                  <tr
                    key={`${mint}-${i}`}
                    className="border-b border-terminal-border/40 hover:bg-white/[0.02]"
                  >
                    <td className="px-3 py-2">
                      {mint ? (
                        <Link
                          href={`/tokens/${mint}`}
                          className="mono text-terminal-dim hover:text-terminal-accent"
                        >
                          {shortAddr(mint, 5)}
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-2 py-2">
                      <span
                        className={
                          label.includes("runner")
                            ? "text-terminal-accent"
                            : label.includes("fade")
                              ? "text-terminal-danger"
                              : "text-terminal-dim"
                        }
                      >
                        {label}
                      </span>
                    </td>
                    <td className="px-2 py-2 tabular">
                      {num(row.stinky_score ?? row.score)?.toFixed(0) ?? "—"}
                    </td>
                    <td className="px-2 py-2 tabular">
                      {fmtUsd(num(row.peak_volume_m5_usd ?? row.peak_volume))}
                    </td>
                    <td className="px-2 py-2 tabular">
                      {fmtUsd(num(row.peak_market_cap_usd ?? row.peak_mcap))}
                    </td>
                    <td className="px-2 py-2 text-[11px] text-terminal-muted">
                      {String(row.labeled_at || row.occurred_at || row.alert_at || "—").slice(
                        0,
                        19
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: unknown;
  accent?: boolean;
}) {
  const display =
    value == null || value === ""
      ? "—"
      : typeof value === "number"
        ? value.toLocaleString()
        : String(value);
  return (
    <div className="rounded-lg border border-terminal-border/70 bg-[#0d120d] px-3 py-2">
      <div className="text-[9px] uppercase tracking-wide text-terminal-muted">{label}</div>
      <div
        className={`mt-0.5 truncate text-[16px] font-semibold tabular ${
          accent ? "text-terminal-accent" : "text-terminal-text"
        }`}
      >
        {display}
      </div>
    </div>
  );
}
