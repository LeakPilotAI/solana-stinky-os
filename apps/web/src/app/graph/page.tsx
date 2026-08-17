"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, fmtPct, shortAddr } from "@/lib/api/client";
import type { GraphData, GraphNode, GraphEdge, GraphEgo } from "@/types";
import { CopyButton } from "@/components/ui/CopyButton";

type EdgeFilter = "all" | "co_buy" | "entity_link";

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function TypePill({ type }: { type: string }) {
  const base =
    "inline-flex rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide";
  if (type === "co_buy")
    return (
      <span className={`${base} border-terminal-accent/40 bg-terminal-accent/12 text-terminal-accent`}>
        co_buy
      </span>
    );
  if (type === "entity_link")
    return (
      <span className={`${base} border-violet-500/40 bg-violet-500/12 text-violet-300`}>
        entity_link
      </span>
    );
  return (
    <span className={`${base} border-terminal-border text-terminal-muted`}>{type}</span>
  );
}

function WeightBar({ w, max }: { w: number; max: number }) {
  const pct = max > 0 ? Math.min(100, (w / max) * 100) : 0;
  return (
    <div className="flex min-w-[4rem] items-center gap-2">
      <span className="w-6 text-right text-[11px] font-semibold tabular text-terminal-text">
        {w}
      </span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
        <div
          className="h-full rounded-full bg-terminal-accent/80"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function GraphPage() {
  const [data, setData] = useState<GraphData | null>(null);
  const [ego, setEgo] = useState<GraphEgo | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState<EdgeFilter>("all");
  const [minShared, setMinShared] = useState(2);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  useEffect(() => {
    let c = false;
    setLoading(true);
    api
      .graph(minShared, 120)
      .then((d) => {
        if (!c) {
          setData(d);
          setUpdatedAt(new Date());
          setError(null);
        }
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
  }, [minShared]);

  useEffect(() => {
    if (!selected) {
      setEgo(null);
      return;
    }
    api
      .graphWallet(selected, 1)
      .then(setEgo)
      .catch(() => setEgo(null));
  }, [selected]);

  const edges = useMemo(() => {
    let list = data?.edges || [];
    if (filter !== "all") list = list.filter((e) => e.type === filter);
    const qq = q.trim().toLowerCase();
    if (qq) {
      list = list.filter(
        (e) =>
          e.source.toLowerCase().includes(qq) ||
          e.target.toLowerCase().includes(qq) ||
          (e.label || "").toLowerCase().includes(qq)
      );
    }
    return [...list].sort((a, b) => (b.weight || 0) - (a.weight || 0));
  }, [data, filter, q]);

  const maxWeight = useMemo(
    () => edges.reduce((m, e) => Math.max(m, e.weight || 0), 0) || 1,
    [edges]
  );

  const nodeMap = useMemo(() => {
    const m = new Map<string, GraphNode>();
    for (const n of data?.nodes || []) m.set(n.id, n);
    return m;
  }, [data]);

  const canvasNodes = useMemo(() => {
    const nodes = data?.nodes || [];
    // Prefer high-degree nodes for radial view
    return [...nodes]
      .sort((a, b) => (b.degree || 0) - (a.degree || 0))
      .slice(0, 48);
  }, [data]);

  const selectedNode = selected ? nodeMap.get(selected) : undefined;

  const hubCount = useMemo(() => {
    return (data?.nodes || []).filter((n) => (n.degree || 0) >= 5).length;
  }, [data]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header */}
      <div className="shrink-0 border-b border-terminal-border bg-terminal-panel/40 px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-terminal-dim">
                Stinky Graph
              </h1>
              <span className="rounded border border-terminal-border px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-terminal-muted">
                postgres
              </span>
            </div>
            <p className="mt-1 max-w-xl text-[11px] leading-relaxed text-terminal-muted">
              Co-buy overlap and multi-wallet entity links — measured relationships only.
              Neo4j not required for this layer.
            </p>
            {data?.engine && (
              <p className="mt-1 font-mono text-[10px] text-terminal-muted">{data.engine}</p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filter wallet in edges…"
              className="w-48 rounded border border-terminal-border bg-black/40 py-1.5 px-2.5 text-[11px] outline-none placeholder:text-terminal-muted focus:border-terminal-accent/40"
            />
            <label className="flex items-center gap-1.5 text-[10px] text-terminal-muted">
              min shared
              <select
                className="rounded border border-terminal-border bg-black/40 px-1.5 py-1.5 text-[11px] text-terminal-dim outline-none"
                value={minShared}
                onChange={(e) => setMinShared(Number(e.target.value))}
              >
                {[1, 2, 3, 4, 5, 8].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Stat label="Nodes" value={String(data?.stats?.nodes ?? data?.nodes?.length ?? 0)} />
          <Stat
            label="Edges"
            value={String(data?.stats?.edges ?? data?.edges?.length ?? 0)}
            accent
          />
          <Stat label="Co-buy" value={String(data?.stats?.co_buy_edges ?? "—")} />
          <Stat label="Entity links" value={String(data?.stats?.entity_edges ?? "—")} />
          <Stat label="Hubs (≥5)" value={String(hubCount)} />

          {(["all", "co_buy", "entity_link"] as const).map((k) => (
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
              {k === "all" ? "All edges" : k}
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

      {/* Body: canvas + edges + side */}
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <div className="flex min-w-0 min-h-0 flex-1 flex-col overflow-hidden">
          {/* Canvas */}
          <div className="relative min-h-[220px] flex-1 border-b border-terminal-border bg-black/20">
            {loading && (
              <p className="absolute inset-0 flex items-center justify-center text-sm text-terminal-muted">
                Loading graph…
              </p>
            )}
            {!loading && canvasNodes.length === 0 && (
              <p className="absolute inset-0 flex items-center justify-center text-sm text-terminal-muted">
                No graph nodes yet. Need migration_buyers overlap.
              </p>
            )}
            {!loading && canvasNodes.length > 0 && (
              <GraphCanvas
                nodes={canvasNodes}
                edges={edges}
                selected={selected}
                onSelect={setSelected}
              />
            )}
            <div className="pointer-events-none absolute bottom-2 left-3 text-[9px] uppercase tracking-wide text-terminal-muted">
              Radial · top {canvasNodes.length} by degree · click node to inspect
            </div>
          </div>

          {/* Strongest edges table */}
          <div className="max-h-[40%] min-h-[160px] overflow-auto">
            <div className="sticky top-0 z-10 border-b border-terminal-border bg-[#0a0c0a]/95 px-3 py-1.5 text-[9px] uppercase tracking-wider text-terminal-muted backdrop-blur">
              Strongest edges · {edges.length} shown
            </div>
            <table className="w-full text-left text-[11px]">
              <thead className="sticky top-7 z-10 border-b border-terminal-border bg-[#0a0c0a]/95 text-[9px] uppercase tracking-wider text-terminal-muted backdrop-blur">
                <tr>
                  <th className="w-10 px-3 py-2">#</th>
                  <th className="px-2 py-2">Type</th>
                  <th className="px-2 py-2">Source</th>
                  <th className="px-2 py-2">Target</th>
                  <th className="min-w-[5rem] px-2 py-2">Weight</th>
                  <th className="px-2 py-2">Label</th>
                </tr>
              </thead>
              <tbody>
                {edges.length === 0 && !loading && (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-terminal-muted">
                      No edges at this threshold. Lower min shared or wait for more
                      co-buys.
                    </td>
                  </tr>
                )}
                {edges.slice(0, 60).map((e, i) => {
                  const hi =
                    selected &&
                    (e.source === selected || e.target === selected);
                  return (
                    <tr
                      key={e.id}
                      className={`border-b border-terminal-border/40 hover:bg-terminal-accent/[0.04] ${
                        hi ? "bg-terminal-accent/[0.06]" : ""
                      }`}
                    >
                      <td className="px-3 py-1.5 tabular text-terminal-muted">
                        {i + 1}
                      </td>
                      <td className="px-2 py-1.5">
                        <TypePill type={e.type} />
                      </td>
                      <td className="px-2 py-1.5">
                        <button
                          type="button"
                          className="font-mono text-terminal-accent hover:underline"
                          onClick={() => setSelected(e.source)}
                        >
                          {shortAddr(e.source, 4)}
                        </button>
                      </td>
                      <td className="px-2 py-1.5">
                        <button
                          type="button"
                          className="font-mono text-terminal-accent hover:underline"
                          onClick={() => setSelected(e.target)}
                        >
                          {shortAddr(e.target, 4)}
                        </button>
                      </td>
                      <td className="px-2 py-1.5">
                        <WeightBar w={e.weight || 0} max={maxWeight} />
                      </td>
                      <td className="max-w-[12rem] truncate px-2 py-1.5 text-terminal-muted">
                        {e.label || "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Side panel */}
        <aside className="w-full shrink-0 overflow-y-auto border-t border-terminal-border lg:w-80 lg:border-l lg:border-t-0">
          <div className="border-b border-terminal-border px-3 py-2">
            <div className="text-[9px] uppercase tracking-wide text-terminal-muted">
              Selected node
            </div>
            {!selected && (
              <p className="mt-2 text-[11px] text-terminal-muted">
                Click a node or edge endpoint to inspect neighborhood.{" "}
                <span className="text-terminal-dim">
                  co_buy = early on same migrations · entity_link = same resolved
                  operator.
                </span>
              </p>
            )}
            {selected && (
              <div className="mt-2 space-y-2 text-[11px]">
                <div className="flex items-start gap-2">
                  <code className="break-all font-mono text-[10px] text-terminal-text">
                    {selected}
                  </code>
                  <CopyButton value={selected} label="Copy" />
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <Link
                    href={`/wallets/${selected}`}
                    className="rounded border border-terminal-border px-1.5 py-0.5 text-[10px] text-terminal-muted hover:border-terminal-accent/40 hover:text-terminal-accent"
                  >
                    Wallet
                  </Link>
                  {selectedNode?.entity_id && (
                    <Link
                      href={`/entities/${selectedNode.entity_id}`}
                      className="rounded border border-terminal-border px-1.5 py-0.5 text-[10px] text-terminal-muted hover:border-violet-500/40 hover:text-violet-300"
                    >
                      Entity
                    </Link>
                  )}
                  <button
                    type="button"
                    onClick={() => setSelected(null)}
                    className="rounded border border-terminal-border px-1.5 py-0.5 text-[10px] text-terminal-muted hover:text-terminal-dim"
                  >
                    Clear
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-2 rounded border border-terminal-border bg-black/25 p-2">
                  <Metric label="Degree" value={String(selectedNode?.degree ?? "—")} />
                  <Metric
                    label="Early mints"
                    value={String(
                      selectedNode?.early_mints ??
                        ego?.early_entries?.length ??
                        "—"
                    )}
                  />
                  <Metric
                    label="Hit rate"
                    value={fmtPct(selectedNode?.hit_rate) || "—"}
                  />
                  <Metric
                    label="Launches"
                    value={String(selectedNode?.launch_count ?? "—")}
                  />
                </div>
              </div>
            )}
          </div>

          {ego?.available && (
            <div>
              <div className="border-b border-terminal-border px-3 py-2 text-[9px] uppercase tracking-wide text-terminal-muted">
                Neighbors · {ego.neighbor_count ?? (ego.neighbors || []).length}
              </div>
              <ul className="max-h-48 overflow-y-auto">
                {(ego.neighbors || []).map((n) => (
                  <li
                    key={n.neighbor}
                    className="flex items-center justify-between border-b border-terminal-border/40 px-3 py-1.5 text-[11px]"
                  >
                    <button
                      type="button"
                      className="font-mono text-terminal-accent hover:underline"
                      onClick={() => n.neighbor && setSelected(n.neighbor)}
                    >
                      {shortAddr(n.neighbor || "", 5)}
                    </button>
                    <span className="tabular text-terminal-dim">
                      {n.shared_mints ?? "—"} shared
                    </span>
                  </li>
                ))}
                {(ego.neighbors || []).length === 0 && (
                  <li className="px-3 py-4 text-[11px] text-terminal-muted">
                    No neighbors at min_shared=1
                  </li>
                )}
              </ul>
            </div>
          )}

          {ego?.early_entries && ego.early_entries.length > 0 && (
            <div>
              <div className="border-b border-terminal-border px-3 py-2 text-[9px] uppercase tracking-wide text-terminal-muted">
                Early entries · {ego.early_entries.length}
              </div>
              <ul className="max-h-40 overflow-y-auto">
                {ego.early_entries.slice(0, 15).map((e, i) => (
                  <li
                    key={`${e.mint}-${i}`}
                    className="flex items-center justify-between border-b border-terminal-border/40 px-3 py-1.5 text-[11px]"
                  >
                    {e.mint ? (
                      <Link
                        href={`/tokens/${e.mint}`}
                        className="font-mono text-terminal-dim hover:text-terminal-accent"
                      >
                        {shortAddr(e.mint, 4)}
                      </Link>
                    ) : (
                      <span>—</span>
                    )}
                    <span className="tabular text-terminal-muted">
                      #{e.rank ?? "—"}
                      {e.sol_spent != null
                        ? ` · ${Number(e.sol_spent).toFixed(2)} SOL`
                        : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="border-t border-terminal-border px-3 py-2 text-[10px] text-terminal-muted">
            Edge types:{" "}
            <span className="text-terminal-accent">co_buy</span> = early on same
            migrations ·{" "}
            <span className="text-violet-300">entity_link</span> = same resolved
            operator identity.
          </div>
        </aside>
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

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[9px] uppercase text-terminal-muted">{label}</div>
      <div className="tabular font-medium text-terminal-text">{value}</div>
    </div>
  );
}

function GraphCanvas({
  nodes,
  edges,
  selected,
  onSelect,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const W = 640;
  const H = 360;
  const cx = W / 2;
  const cy = H / 2;
  const R = Math.min(W, H) * 0.38;

  const positions = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>();
    const n = Math.max(nodes.length, 1);
    nodes.forEach((node, i) => {
      const angle = (2 * Math.PI * i) / n - Math.PI / 2;
      const deg = Math.min(1, (node.degree || 0) / 10);
      // Higher degree → slightly closer to center (hub pull)
      const r = R * (0.5 + 0.5 * (1 - deg * 0.55));
      map.set(node.id, {
        x: cx + r * Math.cos(angle),
        y: cy + r * Math.sin(angle),
      });
    });
    return map;
  }, [nodes]);

  const nodeIds = new Set(nodes.map((n) => n.id));
  const visibleEdges = edges.filter(
    (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
  );

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full" role="img">
      {visibleEdges.map((e) => {
        const a = positions.get(e.source);
        const b = positions.get(e.target);
        if (!a || !b) return null;
        const active =
          selected && (e.source === selected || e.target === selected);
        const isEntity = e.type === "entity_link";
        return (
          <line
            key={e.id}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
            stroke={
              active ? "#39ff14" : isEntity ? "#a78bfa" : "rgba(57,255,20,0.22)"
            }
            strokeWidth={
              active ? 1.8 : Math.min(2.8, 0.4 + (e.weight || 1) * 0.2)
            }
            opacity={active ? 0.95 : 0.55}
          />
        );
      })}
      {nodes.map((node) => {
        const p = positions.get(node.id);
        if (!p) return null;
        const isSel = selected === node.id;
        const r = 3.5 + Math.min(7, (node.degree || 0) * 0.55);
        return (
          <g
            key={node.id}
            transform={`translate(${p.x},${p.y})`}
            className="cursor-pointer"
            onClick={() => onSelect(node.id)}
          >
            <circle
              r={r}
              fill={isSel ? "#39ff14" : "#0d1a0d"}
              stroke={isSel ? "#9aff7a" : "rgba(57,255,20,0.45)"}
              strokeWidth={isSel ? 2 : 1.2}
            />
            <title>
              {node.id}
              {"\n"}degree {node.degree ?? 0}
            </title>
          </g>
        );
      })}
    </svg>
  );
}
