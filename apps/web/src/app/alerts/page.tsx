"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, ageFrom, fmtUsd, shortAddr } from "@/lib/api/client";
import type { Alert } from "@/types";
import { CopyButton } from "@/components/ui/CopyButton";

const AXIOM_BASE =
  process.env.NEXT_PUBLIC_AXIOM_URL?.replace(/\/$/, "") || "https://axiom.trade/t";

type Filter = "all" | "gated" | "thin" | "scored";

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function scoreTone(s: number | null): string {
  if (s == null) return "text-terminal-muted";
  if (s >= 80) return "text-emerald-400";
  if (s >= 65) return "text-terminal-accent";
  if (s >= 55) return "text-amber-300";
  return "text-terminal-dim";
}

function ScoreBar({ score }: { score: number | null }) {
  const s = score ?? 0;
  const w = Math.max(0, Math.min(100, s));
  let bar = "bg-terminal-muted/40";
  if (s >= 80) bar = "bg-emerald-400";
  else if (s >= 65) bar = "bg-terminal-accent";
  else if (s >= 55) bar = "bg-amber-400/85";
  return (
    <div className="flex min-w-[4.5rem] items-center gap-2">
      <span className={`w-7 text-right text-[11px] font-semibold tabular ${scoreTone(score)}`}>
        {score != null ? Math.round(score) : "—"}
      </span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${w}%` }} />
      </div>
    </div>
  );
}

function GatePill({ a }: { a: Alert }) {
  const score = num(a.stinky_score);
  const mb = num(a.meaningful_buyer_count) ?? 0;
  const vol = num(a.volume_m5_usd) ?? 0;
  const passes =
    score != null && score >= 55 && mb >= 3 && vol >= 150000;
  if (passes) {
    return (
      <span className="rounded border border-emerald-500/40 bg-emerald-500/12 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-emerald-300">
        gate pass
      </span>
    );
  }
  if (score != null && score >= 55 && vol >= 150000 && mb < 3) {
    return (
      <span className="rounded border border-amber-500/35 bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-300">
        thin book
      </span>
    );
  }
  if (vol >= 150000) {
    return (
      <span className="rounded border border-terminal-border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-terminal-muted">
        candidate
      </span>
    );
  }
  return (
    <span className="rounded border border-terminal-border px-1.5 py-0.5 text-[9px] uppercase text-terminal-muted">
      —
    </span>
  );
}

/** Prefer newest event per mint */
function dedupeByMint(items: Alert[]): Alert[] {
  const seen = new Set<string>();
  const out: Alert[] = [];
  for (const a of items) {
    const m = a.mint || a.event_id || "";
    if (!m || seen.has(m)) continue;
    seen.add(m);
    out.push(a);
  }
  return out;
}

export default function AlertsPage() {
  const [raw, setRaw] = useState<Alert[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const [uniqueOnly, setUniqueOnly] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  useEffect(() => {
    let c = false;
    (async () => {
      try {
        const r = await api.alerts(120);
        if (!c) {
          setRaw(r.items || []);
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

  const unique = useMemo(() => dedupeByMint(raw), [raw]);

  const stats = useMemo(() => {
    const base = uniqueOnly ? unique : raw;
    let gated = 0;
    let thin = 0;
    let scored = 0;
    for (const a of base) {
      const score = num(a.stinky_score);
      const mb = num(a.meaningful_buyer_count) ?? 0;
      const vol = num(a.volume_m5_usd) ?? 0;
      if (score != null) scored += 1;
      if (score != null && score >= 55 && mb >= 3 && vol >= 150000) gated += 1;
      else if (score != null && score >= 55 && vol >= 150000 && mb < 3) thin += 1;
    }
    return {
      events: raw.length,
      unique: unique.length,
      gated,
      thin,
      scored,
      dupes: Math.max(0, raw.length - unique.length),
    };
  }, [raw, unique, uniqueOnly]);

  const rows = useMemo(() => {
    let list = uniqueOnly ? unique : raw;
    if (filter === "gated") {
      list = list.filter((a) => {
        const score = num(a.stinky_score);
        const mb = num(a.meaningful_buyer_count) ?? 0;
        const vol = num(a.volume_m5_usd) ?? 0;
        return score != null && score >= 55 && mb >= 3 && vol >= 150000;
      });
    } else if (filter === "thin") {
      list = list.filter((a) => {
        const score = num(a.stinky_score);
        const mb = num(a.meaningful_buyer_count) ?? 0;
        const vol = num(a.volume_m5_usd) ?? 0;
        return score != null && score >= 55 && vol >= 150000 && mb < 3;
      });
    } else if (filter === "scored") {
      list = list.filter((a) => num(a.stinky_score) != null);
    }
    const qq = q.trim().toLowerCase();
    if (qq) {
      list = list.filter(
        (a) =>
          (a.mint || "").toLowerCase().includes(qq) ||
          (a.symbol || "").toLowerCase().includes(qq) ||
          (a.name || "").toLowerCase().includes(qq) ||
          (a.creator || "").toLowerCase().includes(qq)
      );
    }
    return list;
  }, [raw, unique, uniqueOnly, filter, q]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-terminal-border bg-terminal-panel/40 px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-terminal-dim">
                Alerts
              </h1>
              <span className="rounded border border-terminal-border px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-terminal-muted">
                alert.candidate
              </span>
            </div>
            <p className="mt-1 max-w-xl text-[11px] leading-relaxed text-terminal-muted">
              Migration candidates that cleared volume screening. DM gate still requires
              score ≥55 and ≥3 meaningful buyers — most rows here are intel, not guaranteed DMs.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search token, CA, creator…"
              className="w-52 rounded border border-terminal-border bg-black/40 py-1.5 px-2.5 text-[11px] outline-none placeholder:text-terminal-muted focus:border-terminal-accent/40"
            />
            <label className="flex cursor-pointer items-center gap-1.5 rounded border border-terminal-border px-2 py-1.5 text-[10px] text-terminal-muted">
              <input
                type="checkbox"
                checked={uniqueOnly}
                onChange={(e) => setUniqueOnly(e.target.checked)}
                className="accent-terminal-accent"
              />
              Unique mint
            </label>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Stat label="Events" value={String(stats.events)} />
          <Stat label="Unique" value={String(stats.unique)} accent />
          <Stat label="Dupes hidden" value={String(stats.dupes)} />
          <Stat label="Gate pass" value={String(stats.gated)} />
          <Stat label="Thin book" value={String(stats.thin)} />

          {(
            [
              ["all", "All"],
              ["gated", "Gate pass"],
              ["thin", "Thin book"],
              ["scored", "Scored"],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              type="button"
              onClick={() => setFilter(k)}
              className={`rounded border px-2 py-1 text-[10px] ${
                filter === k
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
        <p className="border-b border-rose-500/30 bg-rose-500/10 px-4 py-2 text-xs text-rose-300">
          API: {error}
        </p>
      )}

      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full text-left text-[11px]">
          <thead className="sticky top-0 z-10 border-b border-terminal-border bg-[#0a0c0a]/95 text-[9px] uppercase tracking-wider text-terminal-muted backdrop-blur">
            <tr>
              <th className="w-14 px-3 py-2 font-medium">When</th>
              <th className="min-w-[8rem] px-2 py-2 font-medium">Token</th>
              <th className="min-w-[5.5rem] px-2 py-2 font-medium">Score</th>
              <th className="px-2 py-2 font-medium">Gate</th>
              <th className="px-2 py-2 text-right font-medium">Vol 5m</th>
              <th className="px-2 py-2 text-right font-medium">Meaningful</th>
              <th className="px-2 py-2 text-right font-medium">Conf</th>
              <th className="px-2 py-2 font-medium">CA</th>
              <th className="px-2 py-2 font-medium"> </th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={9} className="px-4 py-12 text-center text-terminal-muted">
                  Loading alerts…
                </td>
              </tr>
            )}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={9} className="px-4 py-12 text-center text-terminal-muted">
                  No alert.candidate events for this filter.
                </td>
              </tr>
            )}
            {rows.map((a) => {
              const score = num(a.stinky_score);
              const conf = num(a.confidence);
              const confPct = conf == null ? null : conf <= 1 ? conf * 100 : conf;
              const mb = num(a.meaningful_buyer_count);
              const mint = a.mint || "";
              return (
                <tr
                  key={a.event_id || mint}
                  className="group border-b border-terminal-border/40 hover:bg-terminal-accent/[0.04]"
                >
                  <td className="px-3 py-2 tabular text-terminal-muted">
                    {ageFrom(a.occurred_at)}
                  </td>
                  <td className="px-2 py-2">
                    <Link
                      href={mint ? `/tokens/${mint}` : "#"}
                      className="font-medium text-terminal-text hover:text-terminal-accent"
                    >
                      {a.symbol || a.name || shortAddr(mint)}
                    </Link>
                    {a.name && a.symbol && a.name !== a.symbol && (
                      <div className="truncate text-[10px] text-terminal-muted">
                        {a.name}
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    <ScoreBar score={score} />
                  </td>
                  <td className="px-2 py-2">
                    <GatePill a={a} />
                  </td>
                  <td className="px-2 py-2 text-right tabular text-terminal-dim">
                    {fmtUsd(a.volume_m5_usd)}
                  </td>
                  <td
                    className={`px-2 py-2 text-right tabular font-medium ${
                      (mb ?? 0) >= 3
                        ? "text-emerald-400"
                        : (mb ?? 0) >= 1
                          ? "text-amber-300"
                          : "text-terminal-muted"
                    }`}
                  >
                    {mb ?? "—"}
                  </td>
                  <td className="px-2 py-2 text-right tabular text-terminal-dim">
                    {confPct != null ? `${confPct.toFixed(0)}%` : "—"}
                  </td>
                  <td className="px-2 py-2">
                    {mint && (
                      <div className="flex items-center gap-1">
                        <span className="mono text-[10px] text-terminal-muted">
                          {shortAddr(mint, 4)}
                        </span>
                        <CopyButton value={mint} label="CA" />
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex gap-1 opacity-70 group-hover:opacity-100">
                      {mint && (
                        <>
                          <Link
                            href={`/tokens/${mint}`}
                            className="rounded border border-terminal-border px-1.5 py-0.5 text-[10px] text-terminal-muted hover:text-terminal-accent"
                          >
                            Open
                          </Link>
                          <a
                            href={`${AXIOM_BASE}/${mint}`}
                            target="_blank"
                            rel="noreferrer"
                            className="rounded border border-terminal-border px-1.5 py-0.5 text-[10px] text-terminal-muted hover:text-terminal-dim"
                          >
                            Axiom
                          </a>
                        </>
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
        Showing {rows.length} · {stats.events} raw events · unique-mint{" "}
        {uniqueOnly ? "on" : "off"} · gate = score≥55 + vol≥$25k + meaningful≥3
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
