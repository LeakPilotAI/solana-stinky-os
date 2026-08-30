"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";

export default function HealthPage() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let c = false;
    api
      .bookHealth()
      .then((d) => {
        if (!c) setData(d);
      })
      .catch((e) => {
        if (!c) setError(e instanceof Error ? e.message : "failed");
      })
      .finally(() => {
        if (!c) setLoading(false);
      });
    return () => {
      c = true;
    };
  }, []);

  const health = (data?.health || {}) as Record<string, unknown>;
  const coverage = (health.data_coverage || {}) as Record<string, unknown>;
  const patterns = (health.patterns || {}) as Record<string, unknown>;
  const warnings = (Array.isArray(health.warnings) ? health.warnings : []) as string[];

  return (
    <div className="space-y-3 p-4">
      <header>
        <h1 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-terminal-dim">
          Dataset health
        </h1>
        <p className="mt-1 text-[11px] text-terminal-muted">
          Coverage of the stored book. Empty layers stay 0 / UNKNOWN. Source: {String(data?.source || "—")}.
        </p>
      </header>
      {error && <p className="text-xs text-rose-300">API: {error}</p>}
      {loading && <p className="text-xs text-terminal-muted">Loading health…</p>}
      {!loading && (
        <>
          <section className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Stat label="Investigated" value={String(health.investigated_tokens ?? 0)} />
            <Stat label="Resolved" value={String(health.resolved_outcomes ?? 0)} />
            <Stat label="Unlabeled" value={String(health.unlabeled_outcomes ?? 0)} />
            <Stat label="Fingerprints" value={String(patterns.known_fingerprints ?? 0)} />
            <Stat label="RUNNER" value={String(patterns.runner_examples ?? 0)} />
            <Stat label="FADE" value={String(patterns.fade_examples ?? 0)} />
            <Stat label="HELD" value={String(patterns.held_examples ?? 0)} />
            <Stat
              label="Outcome coverage"
              value={coverage.outcome_coverage == null ? "UNKNOWN" : `${coverage.outcome_coverage}%`}
            />
          </section>
          {warnings.length > 0 && (
            <ul className="panel space-y-1 p-3 text-[11px] text-amber-300">
              {warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
          <p className="text-[11px] text-terminal-muted">{String(health.note || coverage.note || "")}</p>
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-terminal-border bg-black/25 px-3 py-2">
      <div className="text-[9px] uppercase tracking-wide text-terminal-muted">{label}</div>
      <div className="mt-1 font-mono text-lg tabular">{value}</div>
    </div>
  );
}
