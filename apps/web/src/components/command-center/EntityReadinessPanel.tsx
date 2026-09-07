"use client";

import { useEffect, useState } from "react";

interface ReadinessComponent {
  status?: string | null;
  passed?: boolean;
  blockers?: string[];
}

interface ReadinessItem {
  entity_id: string;
  primary_wallet?: string | null;
  display_label?: string | null;
  status: string;
  ready: boolean;
  blockers: string[];
  components: {
    developer_history?: ReadinessComponent;
    relationship_history?: ReadinessComponent;
    outcome_history?: ReadinessComponent;
  };
  latest_transition: string;
  regression_count: number;
  snapshot_count: number;
  observed_at?: string | null;
}

interface ReadinessResponse {
  status: string;
  items: ReadinessItem[];
  count?: number;
  note?: string;
}

const label = (value?: string | null) => (value || "UNKNOWN").replaceAll("_", " ");
const short = (value?: string | null) => {
  if (!value) return "unknown entity";
  return value.length > 16 ? `${value.slice(0, 7)}…${value.slice(-5)}` : value;
};

function ComponentState({ name, value }: { name: string; value?: ReadinessComponent }) {
  return (
    <div className="rounded border border-terminal-border bg-black/20 px-2 py-1.5">
      <div className="text-[9px] uppercase tracking-wide text-terminal-dim">{name}</div>
      <div className="mt-0.5 text-[10px] text-terminal-muted">
        {value?.passed ? "PASS" : label(value?.status)}
      </div>
    </div>
  );
}

export function EntityReadinessPanel() {
  const [data, setData] = useState<ReadinessResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch("/api/stinky/v1/entity-graph/command-center-readiness?limit=8", {
          cache: "no-store",
          signal: AbortSignal.timeout(10000),
        });
        if (!res.ok) throw new Error(`readiness ${res.status}`);
        const body = (await res.json()) as ReadinessResponse;
        if (!cancelled) {
          setData(body);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "readiness unavailable");
      }
    };
    void load();
    const id = setInterval(load, 12000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <section className="mx-2.5 mt-2.5 rounded-xl border border-terminal-border bg-[#0a0e0a] px-3 py-2 lg:mx-3 lg:mt-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[10px] font-semibold uppercase tracking-wider text-terminal-muted">
            Entity calibration readiness
          </h2>
          <p className="mt-0.5 text-[10px] text-terminal-dim">
            Evidence sufficiency and stability only. Not quality, risk, prediction, or a trade signal.
          </p>
        </div>
        <span className="text-[9px] uppercase text-terminal-dim">{data?.status || (error ? "UNAVAILABLE" : "LOADING")}</span>
      </div>

      {error && !data ? (
        <p className="py-3 text-[11px] text-terminal-muted">Readiness history unavailable: {error}</p>
      ) : !(data?.items || []).length ? (
        <p className="py-3 text-[11px] text-terminal-muted">NO ENTITY READINESS SNAPSHOTS YET</p>
      ) : (
        <div className="mt-2 grid gap-2 xl:grid-cols-2">
          {data!.items.map((item) => (
            <article key={item.entity_id} className="rounded-lg border border-terminal-border bg-black/15 p-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-mono text-[11px] text-terminal-fg">{item.display_label || short(item.primary_wallet || item.entity_id)}</div>
                  <div className="mt-0.5 text-[9px] text-terminal-dim">{short(item.entity_id)} · {item.snapshot_count} snapshots</div>
                </div>
                <span className={`rounded border px-2 py-0.5 text-[9px] font-semibold uppercase ${item.ready ? "border-terminal-accent/40 bg-terminal-accent/10 text-terminal-accent" : "border-terminal-border bg-white/5 text-terminal-muted"}`}>
                  {item.ready ? "READY — DESCRIPTIVE" : "NOT READY"}
                </span>
              </div>

              <div className="mt-2 grid grid-cols-3 gap-1.5">
                <ComponentState name="Developer" value={item.components?.developer_history} />
                <ComponentState name="Relationships" value={item.components?.relationship_history} />
                <ComponentState name="Outcomes" value={item.components?.outcome_history} />
              </div>

              <div className="mt-2 text-[10px] text-terminal-muted">
                <span className="text-terminal-dim">Latest transition:</span> {label(item.latest_transition)}
                {item.regression_count > 0 ? <span className="ml-2">· regressions {item.regression_count}</span> : null}
              </div>
              <div className="mt-1 text-[10px] text-terminal-dim">
                {item.blockers.length ? `Blocked by: ${item.blockers.map(label).join(" · ")}` : "No readiness blockers in the latest stored evidence."}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
