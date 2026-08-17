"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, shortAddr } from "@/lib/api/client";
import type { PatternItem, PatternsResponse } from "@/types";
import { CopyButton } from "@/components/ui/CopyButton";

const KIND_LABEL: Record<string, string> = {
  repeat_early_buyer: "Repeat early buyer",
  serial_deployer: "Serial deployer",
  measured_edge: "Measured edge",
  co_buy_cluster: "Co-buy cluster",
  dense_early_book: "Dense early book",
};

const KIND_ORDER = [
  "repeat_early_buyer",
  "measured_edge",
  "serial_deployer",
  "co_buy_cluster",
  "dense_early_book",
];

function confPct(c?: number | null): number | null {
  if (c == null) return null;
  const n = Number(c);
  if (!Number.isFinite(n)) return null;
  return n <= 1 ? n * 100 : n;
}

function confTone(p: number | null): string {
  if (p == null) return "text-terminal-muted";
  if (p >= 85) return "text-emerald-400";
  if (p >= 60) return "text-terminal-accent";
  if (p >= 40) return "text-amber-300";
  return "text-terminal-dim";
}

function KindPill({ kind }: { kind: string }) {
  const label = KIND_LABEL[kind] || kind;
  const base =
    "inline-flex rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide";
  if (kind === "repeat_early_buyer")
    return (
      <span className={`${base} border-emerald-500/40 bg-emerald-500/12 text-emerald-300`}>
        {label}
      </span>
    );
  if (kind === "measured_edge")
    return (
      <span className={`${base} border-sky-500/35 bg-sky-500/12 text-sky-300`}>
        {label}
      </span>
    );
  if (kind === "serial_deployer")
    return (
      <span className={`${base} border-amber-500/40 bg-amber-500/12 text-amber-300`}>
        {label}
      </span>
    );
  if (kind === "co_buy_cluster")
    return (
      <span className={`${base} border-violet-500/35 bg-violet-500/12 text-violet-300`}>
        {label}
      </span>
    );
  if (kind === "dense_early_book")
    return (
      <span className={`${base} border-terminal-border bg-white/[0.03] text-terminal-dim`}>
        {label}
      </span>
    );
  return (
    <span className={`${base} border-terminal-border text-terminal-muted`}>{label}</span>
  );
}

function ConfBar({ pct }: { pct: number | null }) {
  const w = pct == null ? 0 : Math.max(0, Math.min(100, pct));
  let bar = "bg-terminal-muted/40";
  if (pct != null && pct >= 85) bar = "bg-emerald-400";
  else if (pct != null && pct >= 60) bar = "bg-terminal-accent";
  else if (pct != null && pct >= 40) bar = "bg-amber-400/80";
  return (
    <div className="flex min-w-[4.5rem] items-center gap-2">
      <span className={`w-8 text-right text-[11px] font-semibold tabular ${confTone(pct)}`}>
        {pct != null ? `${pct.toFixed(0)}%` : "—"}
      </span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${w}%` }} />
      </div>
    </div>
  );
}

function evidenceBits(p: PatternItem): string[] {
  const e = p.evidence || {};
  const bits: string[] = [];
  const keys = [
    "mints",
    "early_entries",
    "buyers_captured",
    "meaningful_buyers",
    "hit_rate",
    "launches",
    "shared",
    "sample_size",
  ];
  for (const k of keys) {
    if (e[k] != null && e[k] !== "") bits.push(`${k.replace(/_/g, " ")}: ${e[k]}`);
  }
  return bits.slice(0, 4);
}

export default function PatternsPage() {
  const [data, setData] = useState<PatternsResponse | null>(null);
  const [kind, setKind] = useState<string>("all");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  useEffect(() => {
    let c = false;
    (async () => {
      try {
        const r = await api.patterns(100);
        if (!c) {
          setData(r);
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

  const counts = data?.counts_by_kind || {};

  const kinds = useMemo(() => {
    const keys = Object.keys(counts);
    return [
      ...KIND_ORDER.filter((k) => keys.includes(k)),
      ...keys.filter((k) => !KIND_ORDER.includes(k)).sort(),
    ];
  }, [counts]);

  const items = useMemo(() => {
    let list = data?.items || [];
    if (kind !== "all") list = list.filter((p) => p.kind === kind);
    const qq = q.trim().toLowerCase();
    if (qq) {
      list = list.filter(
        (p) =>
          p.title.toLowerCase().includes(qq) ||
          p.summary.toLowerCase().includes(qq) ||
          p.kind.toLowerCase().includes(qq) ||
          (p.links?.wallet || "").toLowerCase().includes(qq) ||
          (p.links?.mint || "").toLowerCase().includes(qq) ||
          (p.links?.entity_id || "").toLowerCase().includes(qq)
      );
    }
    return [...list].sort(
      (a, b) => (confPct(b.confidence) ?? 0) - (confPct(a.confidence) ?? 0)
    );
  }, [data, kind, q]);

  const topConf = useMemo(() => {
    const list = data?.items || [];
    if (!list.length) return null;
    const avg =
      list.reduce((s, p) => s + (confPct(p.confidence) ?? 0), 0) / list.length;
    return avg;
  }, [data]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-terminal-border bg-terminal-panel/40 px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-terminal-dim">
                Pattern Discovery
              </h1>
              <span className="rounded border border-terminal-border px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-terminal-muted">
                measured
              </span>
            </div>
            <p className="mt-1 max-w-2xl text-[11px] leading-relaxed text-terminal-muted">
              Deterministic findings from migrations, early buyers, wallet performance,
              and entities — no invented narratives.
            </p>
            {data?.engine && (
              <p className="mt-1 font-mono text-[10px] text-terminal-muted">{data.engine}</p>
            )}
          </div>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search pattern, wallet, mint…"
            className="w-56 rounded border border-terminal-border bg-black/40 py-1.5 px-2.5 text-[11px] outline-none placeholder:text-terminal-muted focus:border-terminal-accent/40"
          />
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Stat label="Findings" value={String(data?.total ?? 0)} accent />
          <Stat
            label="Avg conf"
            value={topConf != null ? `${topConf.toFixed(0)}%` : "—"}
          />
          {kinds.map((k) => (
            <Stat
              key={k}
              label={KIND_LABEL[k] || k}
              value={String(counts[k] ?? 0)}
            />
          ))}

          <button
            type="button"
            onClick={() => setKind("all")}
            className={`rounded border px-2 py-1 text-[10px] ${
              kind === "all"
                ? "border-terminal-accent/45 bg-terminal-accent/10 text-terminal-accent"
                : "border-terminal-border text-terminal-muted"
            }`}
          >
            All ({data?.total ?? 0})
          </button>
          {kinds.map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setKind(k)}
              className={`rounded border px-2 py-1 text-[10px] ${
                kind === k
                  ? "border-terminal-accent/45 bg-terminal-accent/10 text-terminal-accent"
                  : "border-terminal-border text-terminal-muted hover:text-terminal-dim"
              }`}
            >
              {KIND_LABEL[k] || k} ({counts[k] ?? 0})
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
        <p className="border-b border-rose-500/30 bg-rose-500/10 px-4 py-2 text-xs text-rose-300">
          API: {error}
        </p>
      )}

      <div className="min-h-0 flex-1 overflow-auto">
        {loading && (
          <p className="p-8 text-center text-sm text-terminal-muted">Scanning store…</p>
        )}
        {!loading && items.length === 0 && (
          <p className="p-8 text-center text-sm text-terminal-muted">
            No patterns for this filter. Collector fills migration_buyers / performance
            as migrations land.
          </p>
        )}

        <table className="w-full text-left text-[11px]">
          <thead className="sticky top-0 z-10 border-b border-terminal-border bg-[#0a0c0a]/95 text-[9px] uppercase tracking-wider text-terminal-muted backdrop-blur">
            <tr>
              <th className="w-10 px-3 py-2">#</th>
              <th className="px-2 py-2">Kind</th>
              <th className="min-w-[12rem] px-2 py-2">Finding</th>
              <th className="min-w-[5rem] px-2 py-2">Confidence</th>
              <th className="px-2 py-2">Evidence</th>
              <th className="px-2 py-2">Links</th>
              <th className="px-2 py-2"> </th>
            </tr>
          </thead>
          <tbody>
            {items.map((p, i) => {
              const pct = confPct(p.confidence);
              const bits = evidenceBits(p);
              const wallet = p.links?.wallet;
              const walletB = p.links?.wallet_b;
              const mint = p.links?.mint;
              const entity = p.links?.entity_id;
              return (
                <tr
                  key={p.id}
                  className="group border-b border-terminal-border/40 hover:bg-terminal-accent/[0.04]"
                >
                  <td className="px-3 py-2 tabular text-terminal-muted">{i + 1}</td>
                  <td className="px-2 py-2">
                    <KindPill kind={p.kind} />
                  </td>
                  <td className="px-2 py-2">
                    <div className="font-medium text-terminal-text">{p.title}</div>
                    <div className="mt-0.5 max-w-md text-[10px] leading-snug text-terminal-muted">
                      {p.summary}
                    </div>
                  </td>
                  <td className="px-2 py-2">
                    <ConfBar pct={pct} />
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex max-w-xs flex-wrap gap-1">
                      {bits.length === 0 && (
                        <span className="text-terminal-muted">—</span>
                      )}
                      {bits.map((b) => (
                        <span
                          key={b}
                          className="rounded border border-terminal-border/80 bg-white/[0.02] px-1.5 py-0.5 text-[10px] text-terminal-dim"
                        >
                          {b}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex flex-wrap items-center gap-2 font-mono text-[10px]">
                      {wallet && (
                        <Link
                          href={`/wallets/${wallet}`}
                          className="text-terminal-accent hover:underline"
                        >
                          {shortAddr(wallet, 4)}
                        </Link>
                      )}
                      {walletB && (
                        <Link
                          href={`/wallets/${walletB}`}
                          className="text-terminal-accent hover:underline"
                        >
                          +{shortAddr(walletB, 4)}
                        </Link>
                      )}
                      {mint && (
                        <Link
                          href={`/tokens/${mint}`}
                          className="text-terminal-dim hover:text-terminal-accent"
                        >
                          mint {shortAddr(mint, 4)}
                        </Link>
                      )}
                      {entity && (
                        <Link
                          href={`/entities/${entity}`}
                          className="text-terminal-dim hover:text-terminal-accent"
                        >
                          entity
                        </Link>
                      )}
                    </div>
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex gap-1 opacity-70 group-hover:opacity-100">
                      {wallet && <CopyButton value={wallet} label="Addr" />}
                      {mint && <CopyButton value={mint} label="CA" />}
                      {wallet && (
                        <Link
                          href={`/wallets/${wallet}`}
                          className="rounded border border-terminal-border px-1.5 py-0.5 text-[10px] text-terminal-muted hover:text-terminal-accent"
                        >
                          Open
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
        Showing {items.length} of {data?.total ?? 0} · sorted by confidence · engine{" "}
        {data?.engine || "—"}
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
      <div className="max-w-[7rem] truncate text-[9px] uppercase tracking-wide text-terminal-muted">
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
