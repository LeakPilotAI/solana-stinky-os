"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, shortAddr } from "@/lib/api/client";
import type { Entity } from "@/types";
import { CopyButton } from "@/components/ui/CopyButton";

type SortKey = "launches" | "wallets" | "early" | "confidence";
type TypeFilter = "all" | "deployer" | "multi" | "other";

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function confPct(c: number | null | undefined): number | null {
  if (c == null) return null;
  const n = Number(c);
  if (!Number.isFinite(n)) return null;
  return n <= 1 ? n * 100 : n;
}

function TypePill({ type }: { type?: string | null }) {
  const t = (type || "unknown").toLowerCase();
  const base =
    "inline-flex rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide";
  if (t === "deployer")
    return (
      <span className={`${base} border-amber-500/40 bg-amber-500/12 text-amber-300`}>
        deployer
      </span>
    );
  if (t.includes("smart") || t === "trader")
    return (
      <span className={`${base} border-sky-500/35 bg-sky-500/12 text-sky-300`}>
        {t}
      </span>
    );
  return (
    <span className={`${base} border-terminal-border bg-white/[0.03] text-terminal-muted`}>
      {t}
    </span>
  );
}

function LaunchBar({ n, max }: { n: number; max: number }) {
  const pct = max > 0 ? Math.min(100, (n / max) * 100) : 0;
  let bar = "bg-terminal-muted/50";
  if (n >= 40) bar = "bg-rose-400/90";
  else if (n >= 20) bar = "bg-amber-400/85";
  else if (n >= 8) bar = "bg-terminal-accent/80";
  return (
    <div className="flex min-w-[5.5rem] items-center gap-2">
      <span className="w-7 text-right text-[11px] font-semibold tabular text-terminal-text">
        {n}
      </span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function ConfCell({ c }: { c: number | null }) {
  if (c == null) return <span className="text-terminal-muted">—</span>;
  let tone = "text-terminal-muted";
  if (c >= 80) tone = "text-emerald-400";
  else if (c >= 55) tone = "text-terminal-accent";
  else if (c >= 30) tone = "text-amber-300";
  return <span className={`tabular font-medium ${tone}`}>{c.toFixed(0)}%</span>;
}

export default function EntitiesPage() {
  const [items, setItems] = useState<Entity[]>([]);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<SortKey>("launches");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  useEffect(() => {
    let c = false;
    (async () => {
      try {
        const r = await api.entities(150);
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

  const maxLaunches = useMemo(
    () => items.reduce((m, e) => Math.max(m, num(e.launch_count) ?? 0), 0) || 1,
    [items]
  );

  const stats = useMemo(() => {
    let multi = 0;
    let serial = 0;
    let deployers = 0;
    let early = 0;
    for (const e of items) {
      if ((num(e.wallet_count) ?? 0) > 1) multi += 1;
      if ((num(e.launch_count) ?? 0) >= 10) serial += 1;
      if ((e.entity_type || "").toLowerCase() === "deployer") deployers += 1;
      if ((num(e.early_buy_count) ?? 0) > 0) early += 1;
    }
    return { total: items.length, multi, serial, deployers, early };
  }, [items]);

  const filtered = useMemo(() => {
    let list = items;
    if (typeFilter === "deployer") {
      list = list.filter((e) => (e.entity_type || "").toLowerCase() === "deployer");
    } else if (typeFilter === "multi") {
      list = list.filter((e) => (num(e.wallet_count) ?? 0) > 1);
    } else if (typeFilter === "other") {
      list = list.filter((e) => (e.entity_type || "").toLowerCase() !== "deployer");
    }
    const qq = q.trim().toLowerCase();
    if (qq) {
      list = list.filter(
        (e) =>
          (e.primary_wallet || "").toLowerCase().includes(qq) ||
          (e.entity_id || "").toLowerCase().includes(qq) ||
          (e.display_label || "").toLowerCase().includes(qq) ||
          (e.entity_type || "").toLowerCase().includes(qq)
      );
    }
    const sorted = [...list].sort((a, b) => {
      const av =
        sort === "launches"
          ? num(a.launch_count) ?? 0
          : sort === "wallets"
            ? num(a.wallet_count) ?? 0
            : sort === "early"
              ? num(a.early_buy_count) ?? 0
              : confPct(a.confidence) ?? 0;
      const bv =
        sort === "launches"
          ? num(b.launch_count) ?? 0
          : sort === "wallets"
            ? num(b.wallet_count) ?? 0
            : sort === "early"
              ? num(b.early_buy_count) ?? 0
              : confPct(b.confidence) ?? 0;
      return bv - av;
    });
    return sorted;
  }, [items, q, sort, typeFilter]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-terminal-border bg-terminal-panel/40 px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-terminal-dim">
                Entities
              </h1>
              <span className="rounded border border-terminal-border px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-terminal-muted">
                operators
              </span>
            </div>
            <p className="mt-1 max-w-xl text-[11px] leading-relaxed text-terminal-muted">
              Operator identities resolved from deployers and linked wallets. Serial
              launchers and multi-wallet clusters surface first — one person can own many
              addresses.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search wallet, label, id…"
              className="w-52 rounded border border-terminal-border bg-black/40 py-1.5 pl-2.5 pr-2 text-[11px] text-terminal-text outline-none placeholder:text-terminal-muted focus:border-terminal-accent/40"
            />
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
              className="rounded border border-terminal-border bg-black/40 px-2 py-1.5 text-[11px] text-terminal-dim outline-none"
            >
              <option value="launches">Sort: Launches</option>
              <option value="wallets">Sort: Wallet count</option>
              <option value="early">Sort: Early buys</option>
              <option value="confidence">Sort: Confidence</option>
            </select>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Stat label="Entities" value={String(stats.total)} />
          <Stat label="Deployers" value={String(stats.deployers)} />
          <Stat label="Serial (≥10)" value={String(stats.serial)} accent />
          <Stat label="Multi-wallet" value={String(stats.multi)} />
          <Stat label="With early buys" value={String(stats.early)} />

          {(
            [
              ["all", "All"],
              ["deployer", "Deployers"],
              ["multi", "Multi-wallet"],
              ["other", "Other types"],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              type="button"
              onClick={() => setTypeFilter(k)}
              className={`rounded border px-2 py-1 text-[10px] transition ${
                typeFilter === k
                  ? "border-terminal-accent/45 bg-terminal-accent/10 text-terminal-accent"
                  : "border-terminal-border text-terminal-muted hover:text-terminal-dim"
              }`}
            >
              {label}
            </button>
          ))}
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

      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full text-left text-[11px]">
          <thead className="sticky top-0 z-10 border-b border-terminal-border bg-[#0a0c0a]/95 text-[9px] uppercase tracking-wider text-terminal-muted backdrop-blur">
            <tr>
              <th className="w-10 px-3 py-2 font-medium">#</th>
              <th className="min-w-[10rem] px-2 py-2 font-medium">Primary wallet</th>
              <th className="px-2 py-2 font-medium">Type</th>
              <th className="min-w-[6.5rem] px-2 py-2 font-medium">Launches</th>
              <th className="px-2 py-2 text-right font-medium">Wallets</th>
              <th className="px-2 py-2 text-right font-medium">Early buys</th>
              <th className="px-2 py-2 text-right font-medium">Confidence</th>
              <th className="px-2 py-2 font-medium">Label</th>
              <th className="px-2 py-2 font-medium"> </th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={9} className="px-4 py-12 text-center text-terminal-muted">
                  Loading entities…
                </td>
              </tr>
            )}
            {!loading && filtered.length === 0 && (
              <tr>
                <td colSpan={9} className="px-4 py-12 text-center text-terminal-muted">
                  No entities for this filter. Entity resolver seeds from deployers on
                  launches.
                </td>
              </tr>
            )}
            {filtered.map((e, i) => {
              const launches = num(e.launch_count) ?? 0;
              const wallets = num(e.wallet_count) ?? 0;
              const early = num(e.early_buy_count) ?? 0;
              const conf = confPct(e.confidence);
              const multi = wallets > 1;
              return (
                <tr
                  key={e.entity_id}
                  className={`group border-b border-terminal-border/40 transition hover:bg-terminal-accent/[0.04] ${
                    multi ? "bg-violet-500/[0.03]" : ""
                  }`}
                >
                  <td className="px-3 py-2 tabular text-terminal-muted">{i + 1}</td>
                  <td className="px-2 py-2">
                    <Link
                      href={`/entities/${e.entity_id}`}
                      className="mono text-[11px] text-terminal-text hover:text-terminal-accent"
                    >
                      {shortAddr(e.primary_wallet || e.entity_id, 5)}
                    </Link>
                    {multi && (
                      <span className="ml-1.5 rounded border border-violet-500/35 px-1 py-0.5 text-[8px] font-semibold uppercase tracking-wide text-violet-300">
                        cluster
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    <TypePill type={e.entity_type} />
                  </td>
                  <td className="px-2 py-2">
                    <LaunchBar n={launches} max={maxLaunches} />
                  </td>
                  <td
                    className={`px-2 py-2 text-right tabular ${
                      multi ? "font-semibold text-violet-300" : "text-terminal-dim"
                    }`}
                  >
                    {wallets}
                  </td>
                  <td className="px-2 py-2 text-right tabular text-terminal-dim">
                    {early}
                  </td>
                  <td className="px-2 py-2 text-right">
                    <ConfCell c={conf} />
                  </td>
                  <td className="max-w-[10rem] truncate px-2 py-2 text-terminal-muted">
                    {e.display_label || "—"}
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex items-center gap-1 opacity-70 group-hover:opacity-100">
                      {e.primary_wallet && (
                        <CopyButton value={e.primary_wallet} label="Addr" />
                      )}
                      <Link
                        href={`/entities/${e.entity_id}`}
                        className="rounded border border-terminal-border px-1.5 py-0.5 text-[10px] text-terminal-muted hover:border-terminal-accent/40 hover:text-terminal-accent"
                      >
                        Open
                      </Link>
                      {e.primary_wallet && (
                        <Link
                          href={`/wallets/${e.primary_wallet}`}
                          className="rounded border border-terminal-border px-1.5 py-0.5 text-[10px] text-terminal-muted hover:text-terminal-dim"
                        >
                          Wallet
                        </Link>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="shrink-0 border-t border-terminal-border px-4 py-1.5 text-[10px] text-terminal-muted">
        Showing {filtered.length} of {items.length} · from entities table · multi-wallet
        rows tinted · confidence is resolution confidence, not Stinky Score
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
