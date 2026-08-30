"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, shortAddr } from "@/lib/api/client";

type Why = {
  explanation?: string;
  metric?: string;
  previous_value?: number | null;
  current_value?: number | null;
  change?: number | null;
  timestamp?: string | null;
};

type Dip = {
  mint?: string;
  current_state?: string;
  previous_state?: string;
  severity?: string | null;
  time?: string;
  why?: Why[];
  evidence_quality?: string;
  known?: string[];
  unknown?: string[];
  note?: string;
};

const ORDER = ["CRITICAL", "WARNING", "WATCH", "RESOLVED"] as const;

export default function DipsPage() {
  const [dips, setDips] = useState<Dip[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<string>("");

  useEffect(() => {
    let c = false;
    api
      .bookDips()
      .then((r) => {
        if (c) return;
        const rows = (r.dips || []) as Dip[];
        setDips(rows);
        setNote((r.empty_note as string) || null);
        setSource(String(r.source || ""));
      })
      .catch((e) => {
        if (!c) setError(e instanceof Error ? e.message : "failed");
      });
    return () => {
      c = true;
    };
  }, []);

  const grouped = ORDER.map((sev) => ({
    sev,
    rows: dips.filter((d) => (d.severity || "WATCH") === sev),
  }));

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-terminal-border px-4 py-3">
        <h1 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-terminal-dim">Quality dips</h1>
        <p className="mt-1 text-[11px] text-terminal-muted">
          Setup deterioration after Gate 1. Not price-down. Not a buy. Source {source || "—"}.
        </p>
      </div>
      {error && <p className="px-4 py-2 text-xs text-rose-300">API: {error}</p>}
      <div className="min-h-0 flex-1 overflow-auto p-4">
        {dips.length === 0 ? (
          <p className="py-10 text-center text-sm text-terminal-muted">
            {note || "NO ACTIVE QUALITY DETERIORATION"}
          </p>
        ) : (
          <div className="space-y-4">
            {grouped.map(
              (g) =>
                g.rows.length > 0 && (
                  <section key={g.sev} className="panel">
                    <header className="border-b border-terminal-border px-3 py-2 text-[10px] uppercase tracking-wide text-terminal-dim">
                      {g.sev} · {g.rows.length}
                    </header>
                    <ul className="divide-y divide-terminal-border">
                      {g.rows.map((d, i) => (
                        <li key={`${d.mint}-${i}`} className="space-y-2 p-3 text-xs">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <Link href={`/tokens/${d.mint}`} className="font-mono text-terminal-accent hover:underline">
                              {shortAddr(d.mint, 4)}
                            </Link>
                            <span className="text-terminal-muted">
                              {d.previous_state} → {d.current_state}
                            </span>
                            <span className="uppercase text-terminal-dim">{d.severity || d.current_state}</span>
                            <span className="text-terminal-dim">{(d.time || "").slice(0, 19) || "—"}</span>
                          </div>
                          <div>
                            <div className="text-[10px] uppercase text-terminal-dim">Why</div>
                            {(d.why || []).map((w, wi) => (
                              <p key={`${w.metric}-${wi}`} className="text-[11px] text-terminal-muted">
                                {w.explanation}
                                {w.previous_value != null && w.current_value != null
                                  ? ` · ${w.previous_value} → ${w.current_value}`
                                  : ""}
                              </p>
                            ))}
                          </div>
                          <div className="grid grid-cols-2 gap-2 text-[11px] md:grid-cols-4">
                            <p>
                              <span className="text-terminal-dim">Known </span>
                              {(d.known || []).join(", ") || "—"}
                            </p>
                            <p>
                              <span className="text-terminal-dim">UNKNOWN </span>
                              {(d.unknown || []).join(", ") || "—"}
                            </p>
                            <p>
                              <span className="text-terminal-dim">Evidence </span>
                              {d.evidence_quality || "UNKNOWN"}
                            </p>
                            <p className="text-terminal-dim">Not a probability. Not a buy.</p>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </section>
                ),
            )}
          </div>
        )}
      </div>
    </div>
  );
}
