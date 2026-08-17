"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, fmtPct, shortAddr, tierClass } from "@/lib/api/client";
import type { SmartWallet } from "@/types";
import { CopyButton } from "@/components/ui/CopyButton";

type Filter = "all" | "high" | "medium" | "emerging" | "thin";
type SortKey = "watch" | "hit" | "ret" | "sample" | "early";

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function hitTone(h: number | null): string {
  if (h == null) return "text-terminal-muted";
  const p = h <= 1 ? h * 100 : h;
  if (p >= 70) return "text-emerald-400";
  if (p >= 40) return "text-amber-300";
  return "text-rose-400";
}

function retTone(r: number | null): string {
  if (r == null) return "text-terminal-muted";
  if (r > 50) return "text-emerald-400";
  if (r > 0) return "text-terminal-accent";
  if (r > -30) return "text-amber-300";
  return "text-rose-400";
}

function WatchBar({ score }: { score: number | null }) {
  const s = score ?? 0;
  const w = Math.max(0, Math.min(100, s));
  let bar = "bg-terminal-muted/40";
  if (s >= 75) bar = "bg-emerald-400";
  else if (s >= 55) bar = "bg-terminal-accent";
  else if (s >= 40) bar = "bg-amber-400/80";
  return (
    <div className="flex min-w-[4.5rem] items-center gap-2">
      <span className="w-7 text-right text-[11px] font-semibold tabular text-terminal-text">
        {score != null ? Math.round(score) : "—"}
      </span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${w}%` }} />
      </div>
    </div>
  );
}

function TierPill({ tier }: { tier?: string | null }) {
  const t = (tier || "—").toLowerCase();
  const base =
    "inline-flex rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide";
  if (t === "high")
    return (
      <span className={`${base} border-emerald-500/40 bg-emerald-500/15 text-emerald-300`}>
        high
      </span>
    );
  if (t === "medium")
    return (
      <span className={`${base} border-sky-500/35 bg-sky-500/12 text-sky-300`}>
        medium
      </span>
    );
  if (t === "emerging")
    return (
      <span className={`${base} border-violet-500/35 bg-violet-500/12 text-violet-300`}>
        emerging
      </span>
    );
  if (t === "thin")
    return (
      <span className={`${base} border-terminal-border bg-white/[0.03] text-terminal-muted`}>
        thin
      </span>
    );
  return (
    <span className={`${base} border-terminal-border text-terminal-muted`}>{t}</span>
  );
}

export default function WalletsPage() {
  const [items, setItems] = useState<SmartWallet[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<SortKey>("watch");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  useEffect(() => {
    let c = false;
    (async () => {
      try {
        const r = await api.smartWallets(100);
        if (!c) {
          setItems(r.items || []);
          setUpdatedAt(new Date());
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

  const stats = useMemo(() => {
    const byTier: Record<string, number> = {};
    let hitSum = 0;
    let hitN = 0;
    let high = 0;
    for (const w of items) {
      const t = (w.watch_tier || "unknown").toLowerCase();
      byTier[t] = (byTier[t] || 0) + 1;
      if (t === "high") high += 1;
      const h = num(w.hit_rate);
      if (h != null) {
        hitSum += h <= 1 ? h * 100 : h;
        hitN += 1;
      }
    }
    return {
      total: items.length,
      high,
      byTier,
      avgHit: hitN ? hitSum / hitN : null,
    };
  }, [items]);

  const filtered = useMemo(() => {
    let list = items;
    if (filter !== "all") {
      list = list.filter((w) => (w.watch_tier || "").toLowerCase() === filter);
    }
    const qq = q.trim().toLowerCase();
    if (qq) {
      list = list.filter(
        (w) =>
          w.wallet.toLowerCase().includes(qq) ||
          (w.why_watch || []).some((x) => x.toLowerCase().includes(qq))
      );
    }
    const sorted = [...list].sort((a, b) => {
      const an = (k: SortKey) => {
        if (k === "watch") return num(a.watch_score) ?? -1;
        if (k === "hit") {
          const h = num(a.hit_rate);
          return h == null ? -1 : h <= 1 ? h * 100 : h;
        }
        if (k === "ret") return num(a.avg_return_pct) ?? -9999;
        if (k === "sample") return num(a.sample_size) ?? 0;
        if (k === "early") return num(a.early_buy_count) ?? 0;
        return 0;
      };
      const bn = (k: SortKey) => {
        if (k === "watch") return num(b.watch_score) ?? -1;
        if (k === "hit") {
          const h = num(b.hit_rate);
          return h == null ? -1 : h <= 1 ? h * 100 : h;
        }
        if (k === "ret") return num(b.avg_return_pct) ?? -9999;
        if (k === "sample") return num(b.sample_size) ?? 0;
        if (k === "early") return num(b.early_buy_count) ?? 0;
        return 0;
      };
      return bn(sort) - an(sort);
    });
    return sorted;
  }, [items, filter, q, sort]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header */}
      <div className="shrink-0 border-b border-terminal-border bg-terminal-panel/40 px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-terminal-dim">
                Wallets worth watching
              </h1>
              <span className="rounded border border-terminal-border px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-terminal-muted">
                measured
              </span>
            </div>
            <p className="mt-1 max-w-xl text-[11px] leading-relaxed text-terminal-muted">
              Ranked from early-entry performance, labeled runner/fade outcomes, hit rate
              and returns — not a single lucky trade. Confidence stays low until sample
              grows.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Filter address or why…"
                className="w-52 rounded border border-terminal-border bg-black/40 py-1.5 pl-2.5 pr-2 text-[11px] text-terminal-text outline-none placeholder:text-terminal-muted focus:border-terminal-accent/40"
              />
            </div>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
              className="rounded border border-terminal-border bg-black/40 px-2 py-1.5 text-[11px] text-terminal-dim outline-none"
            >
              <option value="watch">Sort: Watch</option>
              <option value="hit">Sort: Hit rate</option>
              <option value="ret">Sort: Avg return</option>
              <option value="sample">Sort: Sample</option>
              <option value="early">Sort: Early</option>
            </select>
          </div>
        </div>

        {/* Stats strip */}
        <div className="mt-3 flex flex-wrap gap-2">
          <Stat label="Tracked" value={String(stats.total)} />
          <Stat label="High tier" value={String(stats.high)} accent />
          <Stat
            label="Avg hit"
            value={
              stats.avgHit != null ? `${stats.avgHit.toFixed(0)}%` : "—"
            }
          />
          {(["high", "medium", "emerging", "thin"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setFilter(filter === t ? "all" : t)}
              className={`rounded border px-2 py-1 text-[10px] tabular transition ${
                filter === t
                  ? "border-terminal-accent/45 bg-terminal-accent/10 text-terminal-accent"
                  : "border-terminal-border text-terminal-muted hover:text-terminal-dim"
              }`}
            >
              {t}{" "}
              <span className="text-terminal-dim">{stats.byTier[t] ?? 0}</span>
            </button>
          ))}
          <button
            type="button"
            onClick={() => setFilter("all")}
            className={`rounded border px-2 py-1 text-[10px] ${
              filter === "all"
                ? "border-terminal-accent/45 bg-terminal-accent/10 text-terminal-accent"
                : "border-terminal-border text-terminal-muted"
            }`}
          >
            All
          </button>
          {updatedAt && (
            <span className="ml-auto self-center text-[10px] text-terminal-muted">
              refreshed {updatedAt.toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      {error && (
        <p className="shrink-0 border-b border-rose-500/30 bg-rose-500/10 px-4 py-2 text-xs text-rose-300">
          API: {error}
        </p>
      )}

      {/* Table */}
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full text-left text-[11px]">
          <thead className="sticky top-0 z-10 border-b border-terminal-border bg-[#0a0c0a]/95 text-[9px] uppercase tracking-wider text-terminal-muted backdrop-blur">
            <tr>
              <th className="w-10 px-3 py-2 font-medium">#</th>
              <th className="min-w-[9rem] px-2 py-2 font-medium">Wallet</th>
              <th className="min-w-[6.5rem] px-2 py-2 font-medium">Watch</th>
              <th className="px-2 py-2 font-medium">Tier</th>
              <th className="px-2 py-2 text-right font-medium">Early</th>
              <th className="px-2 py-2 text-right font-medium">Sample</th>
              <th className="px-2 py-2 text-right font-medium">Hit</th>
              <th className="px-2 py-2 text-right font-medium">Avg ret</th>
              <th className="min-w-[14rem] px-2 py-2 font-medium">Why watch</th>
              <th className="px-2 py-2 font-medium"> </th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={10} className="px-4 py-12 text-center text-terminal-muted">
                  Loading measured wallets…
                </td>
              </tr>
            )}
            {!loading && filtered.length === 0 && (
              <tr>
                <td colSpan={10} className="px-4 py-12 text-center text-terminal-muted">
                  No rows for this filter. Collector fills wallets from live migrations
                  and learn-success labels.
                </td>
              </tr>
            )}
            {filtered.map((w, i) => {
              const hit = num(w.hit_rate);
              const hitPct = hit == null ? null : hit <= 1 ? hit * 100 : hit;
              const ret = num(w.avg_return_pct);
              const why = (w.why_watch || []).slice(0, 3);
              return (
                <tr
                  key={w.wallet}
                  className="group border-b border-terminal-border/40 transition hover:bg-terminal-accent/[0.04]"
                >
                  <td className="px-3 py-2 tabular text-terminal-muted">{i + 1}</td>
                  <td className="px-2 py-2">
                    <Link
                      href={`/wallets/${w.wallet}`}
                      className="mono text-[11px] text-terminal-text hover:text-terminal-accent"
                    >
                      {shortAddr(w.wallet, 5)}
                    </Link>
                  </td>
                  <td className="px-2 py-2">
                    <WatchBar score={num(w.watch_score)} />
                  </td>
                  <td className="px-2 py-2">
                    <TierPill tier={w.watch_tier} />
                  </td>
                  <td className="px-2 py-2 text-right tabular text-terminal-dim">
                    {w.early_buy_count ?? 0}
                  </td>
                  <td className="px-2 py-2 text-right tabular text-terminal-dim">
                    {w.sample_size ?? "—"}
                  </td>
                  <td
                    className={`px-2 py-2 text-right tabular font-medium ${hitTone(hitPct)}`}
                  >
                    {hitPct != null ? `${hitPct.toFixed(0)}%` : "—"}
                  </td>
                  <td
                    className={`px-2 py-2 text-right tabular font-medium ${retTone(ret)}`}
                  >
                    {ret != null ? `${ret > 0 ? "+" : ""}${ret.toFixed(0)}%` : "—"}
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex flex-wrap gap-1">
                      {why.length === 0 && (
                        <span className="text-terminal-muted">—</span>
                      )}
                      {why.map((line, idx) => (
                        <span
                          key={idx}
                          className="max-w-[16rem] truncate rounded border border-terminal-border/80 bg-white/[0.02] px-1.5 py-0.5 text-[10px] text-terminal-dim"
                          title={line}
                        >
                          {line}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex items-center gap-1 opacity-70 group-hover:opacity-100">
                      <CopyButton value={w.wallet} label="Addr" />
                      <Link
                        href={`/wallets/${w.wallet}`}
                        className="rounded border border-terminal-border px-1.5 py-0.5 text-[10px] text-terminal-muted hover:border-terminal-accent/40 hover:text-terminal-accent"
                      >
                        Open
                      </Link>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="shrink-0 border-t border-terminal-border px-4 py-1.5 text-[10px] text-terminal-muted">
        Showing {filtered.length} of {items.length} · data from wallet_performance +
        wallet_early_success · not financial advice
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="rounded border border-terminal-border bg-black/25 px-2.5 py-1">
      <div className="text-[9px] uppercase tracking-wide text-terminal-muted">
        {label}
      </div>
      <div
        className={`text-sm font-semibold tabular ${
          accent ? "text-terminal-accent" : "text-terminal-text"
        }`}
      >
        {value}
      </div>
    </div>
  );
}
