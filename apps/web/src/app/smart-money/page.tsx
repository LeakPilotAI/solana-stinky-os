"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, fmtPct, shortAddr, tierClass } from "@/lib/api/client";
import type { SmartWallet } from "@/types";
import { CopyButton } from "@/components/ui/CopyButton";

type Tab = "edge" | "success";
type Filter = "all" | "high" | "medium" | "emerging";

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function ratePct(v: unknown): number | null {
  const n = num(v);
  if (n == null) return null;
  return n <= 1 ? n * 100 : n;
}

function hitTone(h: number | null): string {
  if (h == null) return "text-terminal-muted";
  if (h >= 70) return "text-emerald-400";
  if (h >= 40) return "text-amber-300";
  return "text-rose-400";
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
  return (
    <span className={`${base} border-terminal-border text-terminal-muted`}>{t}</span>
  );
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
      <span className="w-7 text-right text-[11px] font-semibold tabular">{score != null ? Math.round(score) : "—"}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${w}%` }} />
      </div>
    </div>
  );
}

type SuccessRow = {
  wallet: string;
  early_entries?: number;
  early_on_mega?: number;
  early_on_runner?: number;
  early_on_mid?: number;
  early_on_fade?: number;
  success_rate?: number | null;
  sample_size?: number;
  last_success_at?: string | null;
};

export default function SmartMoneyPage() {
  const [tab, setTab] = useState<Tab>("edge");
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const [edge, setEdge] = useState<SmartWallet[]>([]);
  const [success, setSuccess] = useState<SuccessRow[]>([]);
  const [successMeta, setSuccessMeta] = useState<{ available?: boolean; message?: string; engine?: string }>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  useEffect(() => {
    let c = false;
    (async () => {
      try {
        const [s, suc] = await Promise.all([
          api.smartWallets(100),
          api.walletsSuccess(50).catch(() => ({
            available: false,
            items: [] as SuccessRow[],
            count: 0,
            message: "success endpoint unavailable",
          })),
        ]);
        if (!c) {
          setEdge(s.items || []);
          setSuccess(suc.items || []);
          setSuccessMeta({
            available: suc.available,
            message: suc.message,
            engine: suc.engine,
          });
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

  const edgeStats = useMemo(() => {
    let high = 0;
    let mid = 0;
    let hitN = 0;
    let hitSum = 0;
    for (const w of edge) {
      const t = (w.watch_tier || "").toLowerCase();
      if (t === "high") high += 1;
      if (t === "medium") mid += 1;
      const h = ratePct(w.hit_rate);
      if (h != null) {
        hitSum += h;
        hitN += 1;
      }
    }
    return {
      total: edge.length,
      high,
      mid,
      avgHit: hitN ? hitSum / hitN : null,
    };
  }, [edge]);

  const successStats = useMemo(() => {
    let mega = 0;
    let runners = 0;
    let withRate = 0;
    let rateSum = 0;
    for (const r of success) {
      mega += num(r.early_on_mega) ?? 0;
      runners += num(r.early_on_runner) ?? 0;
      const sr = ratePct(r.success_rate);
      if (sr != null) {
        rateSum += sr;
        withRate += 1;
      }
    }
    return {
      total: success.length,
      megaHits: mega,
      runnerHits: runners,
      avgSuccess: withRate ? rateSum / withRate : null,
    };
  }, [success]);

  const edgeRows = useMemo(() => {
    let list = edge;
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
    // Prefer high sample + high watch for "edge book"
    return [...list].sort((a, b) => {
      const as = (num(a.watch_score) ?? 0) + (num(a.sample_size) ?? 0) * 0.5;
      const bs = (num(b.watch_score) ?? 0) + (num(b.sample_size) ?? 0) * 0.5;
      return bs - as;
    });
  }, [edge, filter, q]);

  const successRows = useMemo(() => {
    let list = success;
    const qq = q.trim().toLowerCase();
    if (qq) list = list.filter((r) => r.wallet.toLowerCase().includes(qq));
    return list;
  }, [success, q]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-terminal-border bg-terminal-panel/40 px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-terminal-dim">
                Smart Money
              </h1>
              <span className="rounded border border-terminal-accent/30 bg-terminal-accent/10 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-terminal-accent">
                edge book
              </span>
            </div>
            <p className="mt-1 max-w-2xl text-[11px] leading-relaxed text-terminal-muted">
              Wallets with measured edge on migrations — watch ranking plus labeled
              runner/mega early-entry success. Not a leaderboard of volume bots.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex rounded border border-terminal-border p-0.5 text-[10px]">
              <button
                type="button"
                onClick={() => setTab("edge")}
                className={`rounded px-2.5 py-1 ${
                  tab === "edge"
                    ? "bg-terminal-accent/15 text-terminal-accent"
                    : "text-terminal-muted hover:text-terminal-dim"
                }`}
              >
                Watch edge
              </button>
              <button
                type="button"
                onClick={() => setTab("success")}
                className={`rounded px-2.5 py-1 ${
                  tab === "success"
                    ? "bg-terminal-accent/15 text-terminal-accent"
                    : "text-terminal-muted hover:text-terminal-dim"
                }`}
              >
                Success book
              </button>
            </div>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filter wallet…"
              className="w-44 rounded border border-terminal-border bg-black/40 py-1.5 px-2.5 text-[11px] outline-none placeholder:text-terminal-muted focus:border-terminal-accent/40"
            />
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {tab === "edge" ? (
            <>
              <Stat label="Tracked" value={String(edgeStats.total)} />
              <Stat label="High tier" value={String(edgeStats.high)} accent />
              <Stat label="Medium" value={String(edgeStats.mid)} />
              <Stat
                label="Avg hit"
                value={edgeStats.avgHit != null ? `${edgeStats.avgHit.toFixed(0)}%` : "—"}
              />
              {(["all", "high", "medium", "emerging"] as const).map((k) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => setFilter(k)}
                  className={`rounded border px-2 py-1 text-[10px] capitalize ${
                    filter === k
                      ? "border-terminal-accent/45 bg-terminal-accent/10 text-terminal-accent"
                      : "border-terminal-border text-terminal-muted"
                  }`}
                >
                  {k}
                </button>
              ))}
            </>
          ) : (
            <>
              <Stat label="Success rows" value={String(successStats.total)} />
              <Stat label="Mega hits" value={String(successStats.megaHits)} accent />
              <Stat label="Runner hits" value={String(successStats.runnerHits)} />
              <Stat
                label="Avg success"
                value={
                  successStats.avgSuccess != null
                    ? `${successStats.avgSuccess.toFixed(0)}%`
                    : "—"
                }
              />
              {successMeta.engine && (
                <span className="self-center text-[10px] text-terminal-muted">
                  {successMeta.engine}
                </span>
              )}
            </>
          )}
          {updatedAt && (
            <span className="ml-auto self-center text-[10px] text-terminal-muted">
              refreshed {updatedAt.toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      {error && (
        <p className="border-b border-rose-500/30 bg-rose-500/10 px-4 py-2 text-xs text-rose-300">
          API: {error}
        </p>
      )}

      <div className="min-h-0 flex-1 overflow-auto">
        {loading && (
          <p className="p-8 text-center text-sm text-terminal-muted">Loading smart money…</p>
        )}

        {!loading && tab === "edge" && (
          <table className="w-full text-left text-[11px]">
            <thead className="sticky top-0 z-10 border-b border-terminal-border bg-[#0a0c0a]/95 text-[9px] uppercase tracking-wider text-terminal-muted backdrop-blur">
              <tr>
                <th className="w-10 px-3 py-2">#</th>
                <th className="px-2 py-2">Wallet</th>
                <th className="px-2 py-2">Watch</th>
                <th className="px-2 py-2">Tier</th>
                <th className="px-2 py-2 text-right">Sample</th>
                <th className="px-2 py-2 text-right">Hit</th>
                <th className="px-2 py-2 text-right">Avg ret</th>
                <th className="px-2 py-2">Why</th>
                <th className="px-2 py-2"> </th>
              </tr>
            </thead>
            <tbody>
              {edgeRows.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-12 text-center text-terminal-muted">
                    No edge wallets yet. Collector + learn-success fill this over time.
                  </td>
                </tr>
              )}
              {edgeRows.map((w, i) => {
                const hit = ratePct(w.hit_rate);
                const ret = num(w.avg_return_pct);
                const why = (w.why_watch || []).slice(0, 2);
                return (
                  <tr
                    key={w.wallet}
                    className="group border-b border-terminal-border/40 hover:bg-terminal-accent/[0.04]"
                  >
                    <td className="px-3 py-2 tabular text-terminal-muted">{i + 1}</td>
                    <td className="px-2 py-2">
                      <Link
                        href={`/wallets/${w.wallet}`}
                        className="mono hover:text-terminal-accent"
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
                      {w.sample_size ?? "—"}
                    </td>
                    <td className={`px-2 py-2 text-right tabular font-medium ${hitTone(hit)}`}>
                      {hit != null ? `${hit.toFixed(0)}%` : "—"}
                    </td>
                    <td
                      className={`px-2 py-2 text-right tabular font-medium ${
                        ret == null
                          ? "text-terminal-muted"
                          : ret > 0
                            ? "text-emerald-400"
                            : "text-rose-400"
                      }`}
                    >
                      {ret != null ? `${ret > 0 ? "+" : ""}${ret.toFixed(0)}%` : "—"}
                    </td>
                    <td className="px-2 py-2">
                      <div className="flex flex-wrap gap-1">
                        {why.map((line, idx) => (
                          <span
                            key={idx}
                            title={line}
                            className="max-w-[14rem] truncate rounded border border-terminal-border/80 bg-white/[0.02] px-1.5 py-0.5 text-[10px] text-terminal-dim"
                          >
                            {line}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-2 py-2">
                      <div className="flex gap-1 opacity-70 group-hover:opacity-100">
                        <CopyButton value={w.wallet} label="Addr" />
                        <Link
                          href={`/wallets/${w.wallet}`}
                          className="rounded border border-terminal-border px-1.5 py-0.5 text-[10px] text-terminal-muted hover:text-terminal-accent"
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
        )}

        {!loading && tab === "success" && (
          <table className="w-full text-left text-[11px]">
            <thead className="sticky top-0 z-10 border-b border-terminal-border bg-[#0a0c0a]/95 text-[9px] uppercase tracking-wider text-terminal-muted backdrop-blur">
              <tr>
                <th className="w-10 px-3 py-2">#</th>
                <th className="px-2 py-2">Wallet</th>
                <th className="px-2 py-2 text-right">Success</th>
                <th className="px-2 py-2 text-right">Sample</th>
                <th className="px-2 py-2 text-right">Mega</th>
                <th className="px-2 py-2 text-right">Runner</th>
                <th className="px-2 py-2 text-right">Mid</th>
                <th className="px-2 py-2 text-right">Fade</th>
                <th className="px-2 py-2 text-right">Entries</th>
                <th className="px-2 py-2"> </th>
              </tr>
            </thead>
            <tbody>
              {successMeta.available === false && successRows.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-4 py-12 text-center text-terminal-muted">
                    {successMeta.message ||
                      "wallet_early_success empty — run learn-success after outcomes exist."}
                  </td>
                </tr>
              )}
              {successRows.map((r, i) => {
                const sr = ratePct(r.success_rate);
                return (
                  <tr
                    key={r.wallet}
                    className="group border-b border-terminal-border/40 hover:bg-terminal-accent/[0.04]"
                  >
                    <td className="px-3 py-2 tabular text-terminal-muted">{i + 1}</td>
                    <td className="px-2 py-2">
                      <Link
                        href={`/wallets/${r.wallet}`}
                        className="mono hover:text-terminal-accent"
                      >
                        {shortAddr(r.wallet, 5)}
                      </Link>
                    </td>
                    <td className={`px-2 py-2 text-right tabular font-semibold ${hitTone(sr)}`}>
                      {sr != null ? `${sr.toFixed(0)}%` : "—"}
                    </td>
                    <td className="px-2 py-2 text-right tabular text-terminal-dim">
                      {r.sample_size ?? "—"}
                    </td>
                    <td className="px-2 py-2 text-right tabular text-emerald-400/90">
                      {r.early_on_mega ?? 0}
                    </td>
                    <td className="px-2 py-2 text-right tabular text-terminal-accent">
                      {r.early_on_runner ?? 0}
                    </td>
                    <td className="px-2 py-2 text-right tabular text-terminal-dim">
                      {r.early_on_mid ?? 0}
                    </td>
                    <td className="px-2 py-2 text-right tabular text-rose-400/80">
                      {r.early_on_fade ?? 0}
                    </td>
                    <td className="px-2 py-2 text-right tabular text-terminal-dim">
                      {r.early_entries ?? "—"}
                    </td>
                    <td className="px-2 py-2">
                      <div className="flex gap-1 opacity-70 group-hover:opacity-100">
                        <CopyButton value={r.wallet} label="Addr" />
                        <Link
                          href={`/wallets/${r.wallet}`}
                          className="rounded border border-terminal-border px-1.5 py-0.5 text-[10px] text-terminal-muted hover:text-terminal-accent"
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
        )}
      </div>

      <div className="shrink-0 border-t border-terminal-border px-4 py-1.5 text-[10px] text-terminal-muted">
        {tab === "edge"
          ? `Watch edge · ${edgeRows.length} rows · from /v1/wallets/smart`
          : `Success book · ${successRows.length} rows · from wallet_early_success (learn-success)`}
        {" · "}
        <Link href="/wallets" className="text-terminal-dim hover:text-terminal-accent">
          Full wallets list →
        </Link>
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
      <div className="text-[9px] uppercase tracking-wide text-terminal-muted">{label}</div>
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
