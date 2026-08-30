"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, ageFrom, copyText, fmtPct, fmtUsd, shortAddr } from "@/lib/api/client";
import type {
  Alert,
  CommandCenterData,
  Opportunity,
  Runner,
  Entity,
  SmartWallet,
} from "@/types";
import { CopyButton } from "@/components/ui/CopyButton";

const AXIOM_BASE =
  process.env.NEXT_PUBLIC_AXIOM_URL?.replace(/\/$/, "") ||
  "https://axiom.trade/t";

function axiomUrl(mint: string) {
  return `${AXIOM_BASE}/${mint}`;
}

type StatusKind = "WATCH" | "RESEARCH" | "MONITOR" | "—";

function statusFromScore(score: number | null | undefined): StatusKind {
  if (score == null || Number.isNaN(score)) return "—";
  if (score >= 80) return "WATCH";
  if (score >= 65) return "RESEARCH";
  if (score >= 55) return "MONITOR";
  return "—";
}

function statusClass(s: StatusKind) {
  switch (s) {
    case "WATCH":
      return "bg-emerald-500/20 text-emerald-300 border-emerald-500/40";
    case "RESEARCH":
      return "bg-amber-500/15 text-amber-300 border-amber-500/35";
    case "MONITOR":
      return "bg-sky-500/15 text-sky-300 border-sky-500/35";
    default:
      return "bg-white/5 text-terminal-muted border-terminal-border";
  }
}

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function confPct(v: unknown): string {
  const c = num(v);
  if (c == null) return "—";
  return `${(c <= 1 ? c * 100 : c).toFixed(0)}%`;
}

function tokenLabel(symbol?: string | null, name?: string | null, mint?: string) {
  const primary = (symbol || name || "").trim();
  if (primary) return primary;
  return shortAddr(mint || "");
}

function tokenSub(symbol?: string | null, name?: string | null) {
  if (symbol && name && symbol !== name) return name;
  return null;
}

/** Decorative sparkline — visual only, not a measured series */
function Spark({ color = "#39ff14" }: { color?: string }) {
  const d =
    "M0 12 L4 10 L8 13 L12 7 L16 9 L20 4 L24 8 L28 5 L32 6 L36 3 L40 5 L44 2 L48 4";
  return (
    <svg viewBox="0 0 48 16" className="h-6 w-14 opacity-80" aria-hidden>
      <path d={d} fill="none" stroke={color} strokeWidth="1.4" />
    </svg>
  );
}

export function CommandCenter() {
  const [data, setData] = useState<CommandCenterData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    const load = async (isFirst = false) => {
      if (inFlight) return; // never stack polls when CC is slow
      inFlight = true;
      try {
        const d = await api.commandCenter();
        if (!cancelled) {
          setData(d);
          setError(null);
          setUpdatedAt(new Date());
        }
      } catch (e) {
        // Sticky: keep last good data. Only hard-fail if we have never loaded.
        if (!cancelled) {
          const msg = e instanceof Error ? e.message : "API unavailable";
          setError(msg);
          // do not clear data
        }
      } finally {
        inFlight = false;
        if (!cancelled) setLoading(false);
      }
    };
    load(true);
    const id = setInterval(() => load(false), 6000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const uniqueQueue = useMemo(() => {
    if (!data?.opportunity_queue) return [];
    const seen = new Set<string>();
    const out: Opportunity[] = [];
    for (const o of data.opportunity_queue) {
      if (!o.mint || seen.has(o.mint)) continue;
      seen.add(o.mint);
      out.push(o);
    }
    return out.slice(0, 5);
  }, [data]);

  const uniqueAlerts = useMemo(() => {
    if (!data?.alerts) return [];
    const seen = new Set<string>();
    const out: Alert[] = [];
    for (const a of data.alerts) {
      const key = a.mint || a.event_id || "";
      if (!key || seen.has(key)) continue;
      seen.add(key);
      out.push(a);
    }
    return out.slice(0, 5);
  }, [data]);

  const patternGroups = useMemo(() => {
    const items = data?.patterns?.items;
    if (!Array.isArray(items)) return [];
    const byKind = new Map<string, { kind: string; n: number; conf: number }>();
    for (const raw of items) {
      const p = raw as Record<string, unknown>;
      const kind = String(p.kind || p.title || "pattern");
      const conf = num(p.confidence) ?? 0;
      const prev = byKind.get(kind);
      if (!prev) byKind.set(kind, { kind, n: 1, conf });
      else
        byKind.set(kind, {
          kind,
          n: prev.n + 1,
          conf: Math.max(prev.conf, conf),
        });
    }
    return Array.from(byKind.values())
      .sort((a, b) => b.n - a.n)
      .slice(0, 5);
  }, [data]);

  const vol5mSum = useMemo(() => {
    if (!data?.runners?.length) return null;
    let s = 0;
    let any = false;
    for (const r of data.runners) {
      const v = num(r.volume_m5_usd);
      if (v != null) {
        s += v;
        any = true;
      }
    }
    return any ? s : null;
  }, [data]);

  if (loading && !data) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-terminal-muted">
        Loading command center…
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-terminal-danger/40 bg-terminal-danger/10 p-4 text-sm">
          <div className="font-medium text-terminal-danger">API offline</div>
          <p className="mt-1 text-terminal-muted">
            Start <code className="mono">stinky-api</code> on port 8010.
          </p>
          <p className="mt-2 text-[11px] text-terminal-muted">{error}</p>
        </div>
      </div>
    );
  }

  if (!data) return null;
  const c = data.counts;

  return (
    <div className="flex h-full flex-col gap-2.5 overflow-auto bg-[#050705] p-2.5 lg:p-3">
      {error ? (
        <div className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-[11px] text-amber-200">
          Last refresh lagged ({error}). Showing last good data — still live.
        </div>
      ) : null}
      {/* ── KPI STRIP ── */}
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        <Kpi
          label="Migrations"
          value={(c.migrations ?? 0).toLocaleString()}
          accent
          sparkColor="#39ff14"
        />
        <Kpi
          label="Volume (5m sum)"
          value={vol5mSum != null ? fmtUsd(vol5mSum) : "—"}
          sparkColor="#3dd6ff"
        />
        <Kpi
          label="Alerts (gated)"
          value={(c.alerts ?? 0).toLocaleString()}
          accent
          sparkColor="#c084fc"
        />
        <Kpi
          label="Tracked wallets"
          value={(c.wallets ?? c.wallets ?? c.wallets_perf ?? 0).toLocaleString()}
          sparkColor="#f0c000"
        />
        <Kpi
          label="Entities"
          value={(c.entities ?? 0).toLocaleString()}
          sparkColor="#f472b6"
        />
        <Kpi
          label="Buyers captured"
          value={(c.buyers ?? 0).toLocaleString()}
          sparkColor="#39ff14"
        />
      </div>

      {/* ── ALERT PRECISION (measured outcomes) ── */}
      {(data as any).pipeline?.available && (
        <div className="rounded border border-terminal-border bg-terminal-panel/80 px-3 py-2 text-2xs">
          <div className="mb-1 text-[9px] font-semibold uppercase tracking-wide text-terminal-dim">
            Pipeline
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-terminal-muted">
            {Object.entries(((data as any).pipeline?.tables as Record<string, number | null>) || {}).map(
              ([k, v]) => (
                <span key={k}>
                  <span className="text-terminal-dim">{k}</span>{" "}
                  <span className="tabular text-terminal-fg">{v ?? "—"}</span>
                </span>
              )
            )}
            {(data as any).pipeline?.maintain_last_utc && (
              <span>
                <span className="text-terminal-dim">maintain</span>{" "}
                <span className="tabular text-terminal-fg">
                  {String((data as any).pipeline.maintain_last_utc).slice(0, 19)}Z
                </span>
              </span>
            )}
          </div>
        </div>
      )}

      {data.alert_precision && data.alert_precision.available !== false && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-terminal-border bg-[#0a0e0a] px-3 py-2">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-terminal-muted">
            Alert precision
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-terminal-muted">Runner rate</span>
            <span className="text-[13px] font-bold tabular text-terminal-accent">
              {data.alert_precision.precision_runner != null
                ? `${(
                    data.alert_precision.precision_runner <= 1
                      ? data.alert_precision.precision_runner * 100
                      : data.alert_precision.precision_runner
                  ).toFixed(0)}%`
                : data.alert_precision.runner_rate != null
                  ? `${(
                      data.alert_precision.runner_rate <= 1
                        ? data.alert_precision.runner_rate * 100
                        : data.alert_precision.runner_rate
                    ).toFixed(0)}%`
                  : "—"}
            </span>
          </div>
          <div className="h-3 w-px bg-terminal-border" />
          <div className="flex flex-wrap gap-2 text-[11px] tabular">
            {Object.entries(data.alert_precision.counts || {}).map(([lab, n]) => (
              <span
                key={lab}
                className={
                  lab === "runner"
                    ? "text-terminal-accent"
                    : lab === "fade"
                      ? "text-terminal-danger"
                      : "text-terminal-dim"
                }
              >
                {lab} {n}
              </span>
            ))}
            {!data.alert_precision.counts ||
              (Object.keys(data.alert_precision.counts).length === 0 && (
                <span className="text-terminal-muted">
                  no labeled outcomes yet
                </span>
              ))}
          </div>
          <div className="ml-auto flex items-center gap-3 text-[10px] text-terminal-muted">
            {data.alert_precision.total_unique_mints != null && (
              <span>{data.alert_precision.total_unique_mints} unique mints</span>
            )}
            <Link
              href="/backtest"
              className="text-terminal-accent hover:underline"
            >
              Backtest →
            </Link>
          </div>
        </div>
      )}

      {/* ── MAIN BAND: Runners | Queue | Alerts ── */}
      <div className="grid min-h-[340px] flex-1 grid-cols-1 gap-2.5 lg:grid-cols-12">
        {/* LIVE RUNNERS */}
        <section className="flex min-h-[280px] flex-col overflow-hidden rounded-xl border border-terminal-border bg-[#0a0e0a] lg:col-span-5">
          <div className="flex items-center justify-between border-b border-terminal-border px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="text-orange-400">🔥</span>
              <h2 className="text-[11px] font-semibold uppercase tracking-wider text-terminal-text">
                Live Runners
              </h2>
            </div>
            <div className="flex items-center gap-2">
              <span className="rounded border border-terminal-border px-1.5 py-0.5 text-[9px] text-terminal-muted">
                Score
              </span>
              <Link
                href="/runners"
                className="text-[10px] text-terminal-muted hover:text-terminal-accent"
              >
                View →
              </Link>
            </div>
          </div>
          <div className="flex-1 overflow-auto">
            <table className="w-full text-left">
              <thead className="sticky top-0 z-10 bg-[#0a0e0a] text-[9px] uppercase tracking-wide text-terminal-muted">
                <tr className="border-b border-terminal-border">
                  <th className="px-3 py-1.5 font-medium">Token</th>
                  <th className="px-1.5 py-1.5 font-medium">Age</th>
                  <th className="px-1.5 py-1.5 font-medium">5m Vol</th>
                  <th className="px-1.5 py-1.5 font-medium">Liq</th>
                  <th className="px-1.5 py-1.5 font-medium">Buyers</th>
                  <th className="px-1.5 py-1.5 font-medium">Smart</th>
                  <th className="px-1.5 py-1.5 font-medium">Score</th>
                  <th className="px-1.5 py-1.5 font-medium">Conf</th>
                  <th className="px-1.5 py-1.5 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="text-[11px]">
                {data.runners.length === 0 && (
                  <tr>
                    <td
                      colSpan={9}
                      className="px-4 py-10 text-center text-terminal-muted"
                    >
                      No runners in API payload. If pipeline shows migration_tracks, restart stinky-api (old query may have timed out).
                    </td>
                  </tr>
                )}
                {data.runners.slice(0, 10).map((r) => (
                  <RunnerRow key={r.mint} r={r} />
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center gap-3 border-t border-terminal-border px-3 py-1.5 text-[10px] text-terminal-muted">
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-terminal-accent" />
              Live poll 4s
            </span>
            <span>
              Last updated{" "}
              {updatedAt
                ? `${Math.max(0, Math.round((now - updatedAt.getTime()) / 1000))}s ago`
                : "—"}
            </span>
          </div>
        </section>

        {/* OPPORTUNITY QUEUE */}
        <section className="flex min-h-[280px] flex-col overflow-hidden rounded-xl border border-terminal-accent/25 bg-[#0a0e0a] lg:col-span-4">
          <div className="flex items-center justify-between border-b border-terminal-border px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="text-terminal-accent">⚡</span>
              <h2 className="text-[11px] font-semibold uppercase tracking-wider">
                Opportunity Queue
              </h2>
            </div>
            <Link
              href="/alerts"
              className="text-[10px] text-terminal-muted hover:text-terminal-accent"
            >
              View All
            </Link>
          </div>
          <div className="flex-1 space-y-1.5 overflow-auto p-2">
            {uniqueQueue.length === 0 && (
              <p className="py-8 text-center text-[12px] text-terminal-muted">
                No gated candidates yet.
              </p>
            )}
            {uniqueQueue.map((o, i) => (
              <OpportunityCard key={o.mint} o={o} rank={i + 1} />
            ))}
          </div>
          <div className="border-t border-terminal-border px-3 py-1.5 text-[9px] text-terminal-muted">
            <span className="text-terminal-accent">●</span> Opportunities from
            measured store · score ≥55 · buyers · $25k 5m
          </div>
        </section>

        {/* RECENT ALERTS */}
        <section className="flex min-h-[280px] flex-col overflow-hidden rounded-xl border border-terminal-border bg-[#0a0e0a] lg:col-span-3">
          <div className="flex items-center justify-between border-b border-terminal-border px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="text-red-400">🔔</span>
              <h2 className="text-[11px] font-semibold uppercase tracking-wider">
                Recent Alerts
              </h2>
            </div>
            <Link
              href="/alerts"
              className="text-[10px] text-terminal-muted hover:text-terminal-accent"
            >
              View All
            </Link>
          </div>
          <ul className="flex-1 space-y-0.5 overflow-auto p-1.5">
            {uniqueAlerts.length === 0 && (
              <li className="py-8 text-center text-[12px] text-terminal-muted">
                No alerts yet.
              </li>
            )}
            {uniqueAlerts.map((a) => {
              const score = num(a.stinky_score);
              return (
                <li
                  key={a.event_id || a.mint}
                  className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-white/[0.03]"
                >
                  <TokenAvatar label={a.symbol || a.name || "?"} />
                  <div className="min-w-0 flex-1">
                    <Link
                      href={a.mint ? `/tokens/${a.mint}` : "/alerts"}
                      className="block truncate text-[12px] font-semibold text-terminal-text hover:text-terminal-accent"
                    >
                      {tokenLabel(a.symbol, a.name, a.mint)}
                    </Link>
                    <div className="text-[9px] text-terminal-muted">
                      {fmtUsd(a.volume_m5_usd)} ·{" "}
                      {a.meaningful_buyer_count ?? a.early_buyer_count ?? 0}{" "}
                      buyers · {ageFrom(a.occurred_at)}
                    </div>
                  </div>
                  <div className="text-right">
                    <div
                      className={`text-[14px] font-bold tabular ${
                        score != null && score >= 55
                          ? "text-terminal-accent"
                          : "text-terminal-dim"
                      }`}
                    >
                      {score != null ? score.toFixed(0) : "—"}
                    </div>
                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-terminal-accent" />
                  </div>
                </li>
              );
            })}
          </ul>
          <div className="border-t border-terminal-border px-3 py-1.5 text-[9px] text-terminal-muted">
            Gated: Score ≥55 · Buyers ≥3 · Vol ≥$25k (5m)
          </div>
        </section>
      </div>

      {/* ── BOTTOM: Market | Entities | Patterns ── */}
      <div className="grid grid-cols-1 gap-2.5 lg:grid-cols-3">
        <section className="rounded-xl border border-terminal-border bg-[#0a0e0a]">
          <div className="flex items-center justify-between border-b border-terminal-border px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="text-terminal-accent">📈</span>
              <h2 className="text-[11px] font-semibold uppercase tracking-wider">
                Market Overview
              </h2>
            </div>
            <div className="flex gap-1 text-[9px] text-terminal-muted">
              <span className="rounded bg-terminal-accent/15 px-1.5 py-0.5 text-terminal-accent">
                LIVE
              </span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 p-3">
            <MiniStat label="Migrations" value={(c.migrations ?? 0).toLocaleString()} />
            <MiniStat label="Tracks" value={(c.tracks ?? 0).toLocaleString()} />
            <MiniStat label="Launches" value={(c.launches ?? 0).toLocaleString()} />
            <MiniStat label="Entities" value={(c.entities ?? 0).toLocaleString()} />
            <MiniStat
              label="5m Vol (runners)"
              value={vol5mSum != null ? fmtUsd(vol5mSum) : "—"}
            />
            <MiniStat label="Wallet perf" value={(c.wallets ?? c.wallets_perf ?? 0).toLocaleString()} />
          </div>
        </section>

        <section className="rounded-xl border border-terminal-border bg-[#0a0e0a]">
          <div className="flex items-center justify-between border-b border-terminal-border px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="text-sky-400">⬡</span>
              <h2 className="text-[11px] font-semibold uppercase tracking-wider">
                Top Entities
              </h2>
            </div>
            <Link
              href="/entities"
              className="text-[10px] text-terminal-muted hover:text-terminal-accent"
            >
              View All
            </Link>
          </div>
          <ul className="space-y-0.5 p-1.5">
            {data.entities.slice(0, 5).map((e, idx) => (
              <EntityRow key={e.entity_id} e={e} rank={idx + 1} />
            ))}
            {data.entities.length === 0 && (
              <li className="px-3 py-6 text-center text-[12px] text-terminal-muted">
                No entities yet.
              </li>
            )}
          </ul>
        </section>

        <section className="rounded-xl border border-terminal-border bg-[#0a0e0a]">
          <div className="flex items-center justify-between border-b border-terminal-border px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="text-fuchsia-400">✦</span>
              <h2 className="text-[11px] font-semibold uppercase tracking-wider">
                Active Patterns
              </h2>
            </div>
            <Link
              href="/patterns"
              className="text-[10px] text-terminal-muted hover:text-terminal-accent"
            >
              View All
            </Link>
          </div>
          <ul className="space-y-0.5 p-1.5">
            {patternGroups.length === 0 && (
              <li className="px-3 py-6 text-center text-[12px] text-terminal-muted">
                {data.patterns?.message || "No patterns yet."}
              </li>
            )}
            {patternGroups.map((p) => (
              <li
                key={p.kind}
                className="flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 hover:bg-white/[0.03]"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <span className="h-2 w-2 shrink-0 rounded-sm bg-terminal-accent/70" />
                  <div className="min-w-0">
                    <div className="truncate text-[11px] font-medium text-terminal-text">
                      {p.kind}
                    </div>
                    <div className="text-[9px] text-terminal-muted">
                      {p.n} findings
                    </div>
                  </div>
                </div>
                <span className="shrink-0 text-[12px] font-semibold tabular text-terminal-accent">
                  {confPct(p.conf <= 1 ? p.conf : p.conf / 100)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      
      {/* ── TRENDING: Gate 1 5m vol >= $150k ── */}
      <section className="flex min-h-[220px] flex-col overflow-hidden rounded-xl border border-emerald-500/25 bg-[#0a0e0a]">
        <div className="flex items-center justify-between border-b border-terminal-border px-3 py-2">
          <div className="flex items-center gap-2">
            <span className="text-emerald-400">📈</span>
            <h2 className="text-[11px] font-semibold uppercase tracking-wider text-terminal-text">
              Trending · Gate 1 $150k 5m
            </h2>
            <span className="rounded border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-[9px] text-emerald-300">
              any age
            </span>
          </div>
          <div className="flex items-center gap-2 text-[9px] text-terminal-muted">
            <span>
              {(data.trending?.count ?? data.trending?.items?.length ?? 0)} hits
            </span>
            <span className="text-terminal-muted/60">pump · fees gate when known</span>
          </div>
        </div>
        <div className="flex-1 overflow-auto">
          <table className="w-full text-left">
            <thead className="sticky top-0 z-10 bg-[#0a0e0a] text-[9px] uppercase tracking-wide text-terminal-muted">
              <tr className="border-b border-terminal-border">
                <th className="px-3 py-1.5 font-medium">#</th>
                <th className="px-1.5 py-1.5 font-medium">Token</th>
                <th className="px-1.5 py-1.5 font-medium text-right">5m Vol</th>
                <th className="px-1.5 py-1.5 font-medium text-right">Liq</th>
                <th className="px-1.5 py-1.5 font-medium text-right">MCap</th>
                <th className="px-1.5 py-1.5 font-medium text-right">Fees</th>
                <th className="px-1.5 py-1.5 font-medium">Snap</th>
                <th className="px-1.5 py-1.5 font-medium">CA</th>
              </tr>
            </thead>
            <tbody>
              {(data.trending?.items ?? []).length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-8 text-center text-[12px] text-terminal-muted">
                    No measured coins at ≥ $150k 5m volume yet. Gate 1 is an investigation trigger, not a buy.
                  </td>
                </tr>
              )}
              {(data.trending?.items ?? []).slice(0, 20).map((t, i) => {
                const mint = String(t.mint || "");
                return (
                  <tr
                    key={mint || i}
                    className="border-b border-terminal-border/50 hover:bg-white/[0.03]"
                  >
                    <td className="px-3 py-1.5 text-[10px] tabular text-terminal-muted">
                      {i + 1}
                    </td>
                    <td className="px-1.5 py-1.5">
                      <Link
                        href={`/tokens/${mint}`}
                        className="block min-w-0 hover:text-terminal-accent"
                      >
                        <div className="truncate text-[11px] font-semibold text-terminal-text">
                          {tokenLabel(t.symbol, t.name, mint)}
                        </div>
                        {tokenSub(t.symbol, t.name) && (
                          <div className="truncate text-[9px] text-terminal-muted">
                            {tokenSub(t.symbol, t.name)}
                          </div>
                        )}
                      </Link>
                    </td>
                    <td className="px-1.5 py-1.5 text-right text-[11px] font-semibold tabular text-emerald-300">
                      {fmtUsd(num(t.volume_m5_usd))}
                    </td>
                    <td className="px-1.5 py-1.5 text-right text-[10px] tabular text-terminal-muted">
                      {fmtUsd(num(t.liquidity_usd))}
                    </td>
                    <td className="px-1.5 py-1.5 text-right text-[10px] tabular text-terminal-muted">
                      {fmtUsd(num(t.market_cap_usd))}
                    </td>
                    <td className="px-1.5 py-1.5 text-right text-[10px] tabular text-terminal-muted">
                      {t.fees_sol != null ? `${Number(t.fees_sol).toFixed(1)}◎` : "—"}
                    </td>
                    <td className="px-1.5 py-1.5 text-[9px] text-terminal-muted">
                      {ageFrom(t.captured_at ?? undefined)}
                    </td>
                    <td className="px-1.5 py-1.5">
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          className="rounded border border-terminal-border px-1 py-0.5 text-[9px] text-terminal-muted hover:border-terminal-accent hover:text-terminal-accent"
                          onClick={() => copyText(mint)}
                          title="Copy CA"
                        >
                          CA
                        </button>
                        <a
                          href={axiomUrl(mint)}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded border border-terminal-border px-1 py-0.5 text-[9px] text-terminal-muted hover:border-terminal-accent hover:text-terminal-accent"
                        >
                          Ax
                        </a>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── EVENT STREAM FOOTER ── */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-terminal-border bg-[#0a0e0a] px-3 py-1.5 text-[10px]">
        <span className="flex items-center gap-1.5 font-semibold text-terminal-text">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-terminal-accent" />
          EVENT STREAM
          <span className="text-terminal-accent">LIVE</span>
        </span>
        <span className="text-terminal-border">|</span>
        {(data.alerts || []).slice(0, 4).map((a, i) => (
          <span key={a.event_id || i} className="text-terminal-muted">
            <span className="text-terminal-accent">●</span>{" "}
            {a.mint ? shortAddr(a.mint, 4) : "event"} ·{" "}
            {tokenLabel(a.symbol, a.name, a.mint)}
          </span>
        ))}
        <span className="ml-auto text-terminal-muted">
          Real store only · no invented metrics
        </span>
      </div>
    </div>
  );
}

function Kpi({
  label,
  value,
  accent,
  sparkColor,
}: {
  label: string;
  value: string;
  accent?: boolean;
  sparkColor?: string;
}) {
  return (
    <div
      className={`rounded-xl border bg-[#0a0e0a] px-3 py-2.5 ${
        accent
          ? "border-terminal-accent/30 shadow-[0_0_20px_rgba(57,255,20,0.05)]"
          : "border-terminal-border"
      }`}
    >
      <div className="flex items-start justify-between gap-1">
        <div className="text-[9px] font-medium uppercase tracking-wider text-terminal-muted">
          {label}
        </div>
        <Spark color={sparkColor || "#39ff14"} />
      </div>
      <div
        className={`mt-1 text-[20px] font-semibold tabular leading-none ${
          accent ? "text-terminal-accent" : "text-white"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-terminal-border/60 bg-[#0d120d] px-2.5 py-2">
      <div className="text-[9px] uppercase tracking-wide text-terminal-muted">
        {label}
      </div>
      <div className="mt-0.5 text-[15px] font-semibold tabular text-terminal-text">
        {value}
      </div>
    </div>
  );
}

function TokenAvatar({ label }: { label: string }) {
  const ch = (label || "?").replace("$", "").charAt(0).toUpperCase();
  return (
    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-terminal-accent/30 to-terminal-elevated text-[10px] font-bold text-terminal-accent">
      {ch}
    </div>
  );
}

function EntityRow({ e, rank }: { e: Entity; rank: number }) {
  const conf = num(e.confidence);
  return (
    <li className="flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 hover:bg-white/[0.03]">
      <div className="flex min-w-0 items-center gap-2">
        <span className="w-4 text-[10px] tabular text-terminal-muted">
          #{rank}
        </span>
        <Link
          href={`/entities/${e.entity_id}`}
          className="mono truncate text-[11px] text-terminal-dim hover:text-terminal-accent"
        >
          {e.display_label || shortAddr(e.primary_wallet, 5)}
        </Link>
      </div>
      <div className="flex shrink-0 items-center gap-2 text-[10px]">
        <span className="tabular text-terminal-text">
          {e.launch_count ?? 0} launches
        </span>
        {conf != null && (
          <span className="tabular text-terminal-accent">
            {(conf <= 1 ? conf * 100 : conf).toFixed(0)}%
          </span>
        )}
      </div>
    </li>
  );
}

function RunnerRow({ r }: { r: Runner }) {
  const score = num(r.stinky_score);
  const conf = num(r.confidence);
  const status = statusFromScore(score);
  const sub = tokenSub(r.symbol, r.name);
  const buyers = r.meaningful_buyers ?? r.buyers_captured;
  const smart = r.meaningful_buyers;
  return (
    <tr className="border-b border-terminal-border/40 hover:bg-white/[0.025]">
      <td className="px-3 py-1.5">
        <div className="flex items-center gap-2">
          <TokenAvatar label={r.symbol || r.name || "T"} />
          <div className="min-w-0">
            <Link
              href={`/tokens/${r.mint}`}
              className="block truncate text-[11px] font-semibold text-terminal-text hover:text-terminal-accent"
            >
              {tokenLabel(r.symbol, r.name, r.mint)}
            </Link>
            {sub && (
              <div className="truncate text-[9px] text-terminal-muted">{sub}</div>
            )}
          </div>
        </div>
      </td>
      <td className="px-1.5 py-1.5 tabular text-[10px] text-terminal-dim">
        {ageFrom(r.migration_at)}
      </td>
      <td className="px-1.5 py-1.5 tabular text-[10px]">
        {num(r.volume_m5_usd) != null ? (
          <span className="text-terminal-text">{fmtUsd(r.volume_m5_usd)}</span>
        ) : (r.trades_observed || r.buyers_captured) ? (
          <span className="text-amber-300/90" title="Collector tracking; Dex snapshot pending">
            gathering…
          </span>
        ) : (
          <span className="text-terminal-muted" title="No market_snapshots yet">—</span>
        )}
      </td>
      <td className="px-1.5 py-1.5 tabular text-[10px] text-terminal-dim">
        {r.liquidity_usd != null ? fmtUsd(r.liquidity_usd) : "—"}
      </td>
      <td className="px-1.5 py-1.5 tabular text-[10px]">{buyers ?? "—"}</td>
      <td className="px-1.5 py-1.5 tabular text-[10px] text-terminal-accent">
        {smart != null && buyers != null ? `${smart}/${buyers}` : "—"}
      </td>
      <td className="px-1.5 py-1.5 tabular text-[11px]">
        {score != null ? (
          <span
            className={
              score >= 55 ? "font-bold text-terminal-accent" : "text-terminal-dim"
            }
          >
            {score.toFixed(0)}
          </span>
        ) : (
          <span className="text-terminal-muted">—</span>
        )}
      </td>
      <td className="px-1.5 py-1.5 tabular text-[10px] text-terminal-dim">
        {confPct(conf)}
      </td>
      <td className="px-1.5 py-1.5">
        <span
          className={`inline-block rounded border px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-wide ${statusClass(status)}`}
        >
          {status}
        </span>
      </td>
    </tr>
  );
}

function OpportunityCard({ o, rank }: { o: Opportunity; rank: number }) {
  const score = num(o.score);
  const conf = num(o.confidence);
  return (
    <div className="rounded-xl border border-terminal-border bg-[#0d120d] p-2.5 hover:border-terminal-accent/35">
      <div className="flex items-start gap-2.5">
        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-terminal-accent/10 text-[11px] font-bold tabular text-terminal-accent">
          {rank}
        </div>
        <TokenAvatar label={o.symbol || o.name || "?"} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <Link
                href={o.mint ? `/tokens/${o.mint}` : "/alerts"}
                className="truncate text-[12px] font-bold text-white hover:text-terminal-accent"
              >
                {tokenLabel(o.symbol, o.name, o.mint)}
              </Link>
              <div className="mt-0.5 flex flex-wrap gap-x-2 text-[9px] text-terminal-muted">
                <span>{fmtUsd(o.volume_m5_usd)} vol</span>
                <span>
                  {o.meaningful_buyer_count != null
                    ? `${o.meaningful_buyer_count} buyers`
                    : "— buyers"}
                </span>
              </div>
            </div>
            <div className="text-right">
              <div
                className={`text-[18px] font-bold tabular leading-none ${
                  score != null && score >= 55
                    ? "text-terminal-accent"
                    : "text-terminal-text"
                }`}
              >
                {score != null ? score.toFixed(0) : "—"}
              </div>
              <div className="text-[9px] text-terminal-muted">
                {confPct(conf)} conf
              </div>
            </div>
          </div>
          {o.mint && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              <CopyButton value={o.mint} label="CA" variant="outline" />
              <a
                href={axiomUrl(o.mint)}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center rounded-md bg-terminal-accent px-2 py-0.5 text-[9px] font-bold text-black hover:brightness-110"
              >
                AXIOM
              </a>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
