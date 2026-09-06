"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, shortAddr } from "@/lib/api/client";
import type { ResearchResponse, ResearchItem } from "@/types";
import { CopyButton } from "@/components/ui/CopyButton";

type Phase10Check = {
  criterion?: string;
  passed?: boolean;
  observed?: unknown;
  required?: unknown;
  detail?: string;
};

type Phase10Readiness = {
  completion_status?: string;
  ready_for_phase_11_research?: boolean;
  operator_note?: string;
  failed_criteria?: string[];
  persistence_write_status?: string;
  dataset?: {
    row_count?: number;
    coverage?: Record<string, number | null>;
    formation_status?: string;
    dataset_hash?: string;
  };
  discovery?: { pattern_count?: number; discovery_status?: string };
  validation?: { pattern_count?: number; stability_counts?: Record<string, number> };
  persistence?: {
    persisted_pattern_count?: number;
    min_snapshot_depth?: number;
    snapshot_depths?: Record<string, number>;
  };
  audit?: {
    check_count?: number;
    passed_check_count?: number;
    failed_check_count?: number;
    checks?: Phase10Check[];
  };
};

export default function ResearchPage() {
  return (
    <Suspense fallback={<div className="p-4 text-sm text-terminal-muted">Loading research…</div>}>
      <ResearchContent />
    </Suspense>
  );
}

function ResearchContent() {
  const searchParams = useSearchParams();
  const [q, setQ] = useState(() => searchParams.get("q") || "");
  const [data, setData] = useState<ResearchResponse | null>(null);
  const [readiness, setReadiness] = useState<Phase10Readiness | null>(null);
  const [readinessError, setReadinessError] = useState<string | null>(null);
  const [readinessLoading, setReadinessLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const initial = searchParams.get("q");
    if (initial && initial.trim().length >= 2) {
      setQ(initial);
      run(undefined, initial);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    api
      .research("", "overview")
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "failed"));
    runReadiness();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function runReadiness() {
    setReadinessLoading(true);
    setReadinessError(null);
    try {
      const result = await api.phase10Readiness();
      setReadiness(result as Phase10Readiness);
    } catch (e) {
      setReadinessError(e instanceof Error ? e.message : "readiness audit failed");
    } finally {
      setReadinessLoading(false);
    }
  }

  async function run(preset?: string, query?: string) {
    setLoading(true);
    setError(null);
    try {
      const res = await api.research(query ?? q, preset);
      setData(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed");
    } finally {
      setLoading(false);
    }
  }

  const presets = data?.presets || [
    { id: "repeat_early", label: "Repeat early buyers" },
    { id: "serial_deployer", label: "Serial deployers" },
    { id: "co_buy", label: "Co-buy clusters" },
    { id: "measured_edge", label: "Measured edge" },
    { id: "dense_early", label: "Dense early books" },
    { id: "worth_watching", label: "Worth watching" },
  ];

  const coverage = readiness?.dataset?.coverage || {};
  const failedChecks = (readiness?.audit?.checks || []).filter((check) => check.passed === false);
  const complete = readiness?.completion_status === "PHASE_10_COMPLETE";

  return (
    <div className="space-y-3 p-4">
      <div>
        <h1 className="text-sm font-medium uppercase tracking-wide text-terminal-dim">Research</h1>
        <p className="mt-1 max-w-2xl text-xs text-terminal-muted">
          Query measured intelligence only. Keywords route to the same SQL as Patterns /
          Graph / Wallets — no fabricated AI answers.
        </p>
        {data?.engine && <p className="mt-1 text-2xs text-terminal-muted mono">{data.engine}</p>}
      </div>

      <section className="panel space-y-3 p-3" aria-label="Phase 10 research readiness">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="text-2xs uppercase tracking-wide text-terminal-muted">Phase 10 evidence audit</div>
            <div className={`mt-1 text-sm font-medium ${complete ? "text-terminal-accent" : "text-terminal-warn"}`}>
              {readinessLoading && !readiness ? "RUNNING LIVE AUDIT…" : readiness?.completion_status || "UNAVAILABLE"}
            </div>
            <p className="mt-1 max-w-3xl text-xs text-terminal-dim">
              {readiness?.operator_note || "Checks the real persisted Genesis history before any Phase 11 statistical-learning research is allowed."}
            </p>
          </div>
          <button
            type="button"
            onClick={runReadiness}
            disabled={readinessLoading}
            className="rounded border border-terminal-border px-2 py-1 text-2xs text-terminal-muted hover:text-terminal-text disabled:opacity-40"
          >
            {readinessLoading ? "Auditing…" : "Run audit"}
          </button>
        </div>

        {readinessError && <p className="text-xs text-terminal-danger">{readinessError}</p>}

        {readiness && (
          <>
            <dl className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4 lg:grid-cols-8">
              <Metric label="Rows" value={readiness.dataset?.row_count} />
              <Metric label="Labels" value={pct(coverage.label_coverage)} />
              <Metric label="Developer" value={pct(coverage.developer_snapshot_coverage)} />
              <Metric label="Correlation" value={pct(coverage.correlation_snapshot_coverage)} />
              <Metric label="Lifecycle" value={pct(coverage.lifecycle_any_coverage)} />
              <Metric label="Patterns" value={readiness.discovery?.pattern_count} />
              <Metric label="Validated" value={readiness.validation?.pattern_count} />
              <Metric label="Persisted" value={readiness.persistence?.persisted_pattern_count} />
            </dl>

            <div className="grid gap-2 md:grid-cols-3">
              <div className="rounded border border-terminal-border p-2 text-xs">
                <div className="text-terminal-muted">Temporal classifications</div>
                <div className="mt-1 mono text-terminal-dim">
                  STABLE {readiness.validation?.stability_counts?.STABLE ?? 0} · UNSTABLE {readiness.validation?.stability_counts?.UNSTABLE ?? 0} · INSUFFICIENT {readiness.validation?.stability_counts?.INSUFFICIENT_EVIDENCE ?? 0}
                </div>
              </div>
              <div className="rounded border border-terminal-border p-2 text-xs">
                <div className="text-terminal-muted">Persistence depth</div>
                <div className="mt-1 mono text-terminal-dim">
                  min snapshots {readiness.persistence?.min_snapshot_depth ?? 0} · {readiness.persistence_write_status || "UNKNOWN"}
                </div>
              </div>
              <div className="rounded border border-terminal-border p-2 text-xs">
                <div className="text-terminal-muted">Audit checks</div>
                <div className="mt-1 mono text-terminal-dim">
                  {readiness.audit?.passed_check_count ?? 0}/{readiness.audit?.check_count ?? 0} passed · {readiness.audit?.failed_check_count ?? 0} blocked
                </div>
              </div>
            </div>

            {failedChecks.length > 0 ? (
              <div className="rounded border border-terminal-warn/30 p-2">
                <div className="text-2xs uppercase tracking-wide text-terminal-warn">Blocking evidence criteria</div>
                <div className="mt-2 grid gap-1">
                  {failedChecks.map((check) => (
                    <div key={check.criterion} className="text-xs text-terminal-dim">
                      <span className="mono text-terminal-warn">{check.criterion}</span>{" — "}
                      {check.detail || "criterion failed"}{" "}
                      <span className="text-terminal-muted">observed {String(check.observed ?? "—")} · required {String(check.required ?? "—")}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : complete ? (
              <div className="rounded border border-terminal-accent/30 p-2 text-xs text-terminal-dim">
                All Phase 10 readiness criteria pass. This authorizes controlled Phase 11 research design only — not predictive authority, confidence, risk scoring, or trading.
              </div>
            ) : null}
          </>
        )}
      </section>

      <div className="panel flex flex-wrap items-end gap-2 p-3">
        <input
          className="min-w-[240px] flex-1 rounded border border-terminal-border bg-terminal-bg px-2 py-1.5 text-xs"
          placeholder='Try: "repeat early buyers" · "co-buy" · "serial deployer" · "hit rate"'
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run(undefined, q)}
        />
        <button
          type="button"
          onClick={() => run(undefined, q)}
          disabled={loading}
          className="rounded bg-terminal-accent/20 px-3 py-1.5 text-xs text-terminal-accent hover:bg-terminal-accent/30 disabled:opacity-40"
        >
          {loading ? "Running…" : "Run"}
        </button>
      </div>

      <div className="flex flex-wrap gap-1">
        {presets.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => run(p.id)}
            className={`rounded border px-2 py-1 text-2xs ${
              data?.kind === p.id
                ? "border-terminal-accent/50 bg-terminal-elevated"
                : "border-terminal-border text-terminal-muted hover:text-terminal-text"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {error && <p className="text-xs text-terminal-danger">{error}</p>}

      {data && (
        <div className="text-xs text-terminal-dim">
          <span className="text-terminal-muted">Kind</span>{" "}
          <span className="mono">{data.kind}</span>{" · "}
          {data.explanation}{" · "}
          <span className="tabular">{data.count} results</span>
        </div>
      )}

      <div className="grid gap-2">
        {(data?.items || []).map((item, i) => (
          <ResultCard key={`${item.type}-${i}-${item.wallet || item.mint || i}`} item={item} />
        ))}
        {data && data.count === 0 && (
          <div className="panel p-4 text-sm text-terminal-muted">
            No rows for this query yet. Collector fills migration_buyers and performance
            as migrations land.
          </div>
        )}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <dt className="text-terminal-muted">{label}</dt>
      <dd className="tabular font-medium">{String(value ?? "—")}</dd>
    </div>
  );
}

function pct(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function ResultCard({ item }: { item: ResearchItem }) {
  return (
    <div className="panel p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-2xs uppercase tracking-wide text-terminal-muted">{item.type}</div>
          <div className="mt-0.5 text-sm font-medium">{item.title}</div>
          <p className="mt-1 text-xs text-terminal-dim">{item.summary}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-2xs">
          {item.wallet && (
            <>
              <Link href={`/wallets/${item.wallet}`} className="mono text-terminal-accent hover:underline">
                {shortAddr(item.wallet, 5)}
              </Link>
              <CopyButton value={item.wallet} label="CA" />
              <Link href="/time-machine" className="text-terminal-muted hover:underline" title="Paste wallet in Time Machine">
                Timeline
              </Link>
            </>
          )}
          {item.wallet_b && (
            <Link href={`/wallets/${item.wallet_b}`} className="mono text-terminal-accent hover:underline">
              + {shortAddr(item.wallet_b, 5)}
            </Link>
          )}
          {item.mint && (
            <Link href={`/tokens/${item.mint}`} className="mono text-terminal-accent hover:underline">
              mint {shortAddr(item.mint, 4)}
            </Link>
          )}
          {item.entity_id && (
            <Link href={`/entities/${item.entity_id}`} className="text-terminal-accent hover:underline">
              entity
            </Link>
          )}
        </div>
      </div>
      {item.type === "meta" && item.metrics && (
        <dl className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
          {Object.entries(item.metrics).map(([k, v]) => (
            <div key={k}>
              <dt className="text-terminal-muted">{k}</dt>
              <dd className="tabular font-medium">{String(v ?? "—")}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
