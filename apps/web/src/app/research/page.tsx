"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, shortAddr } from "@/lib/api/client";
import type { ResearchResponse, ResearchItem } from "@/types";
import { CopyButton } from "@/components/ui/CopyButton";

export default function ResearchPage() {
  const searchParams = useSearchParams();
  const [q, setQ] = useState(() => searchParams.get("q") || "");
  const [data, setData] = useState<ResearchResponse | null>(null);
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
    // load overview on mount
    api
      .research("", "overview")
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "failed"));
  }, []);

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

  return (
    <div className="space-y-3 p-4">
      <div>
        <h1 className="text-sm font-medium uppercase tracking-wide text-terminal-dim">
          Research
        </h1>
        <p className="mt-1 max-w-2xl text-xs text-terminal-muted">
          Query measured intelligence only. Keywords route to the same SQL as Patterns /
          Graph / Wallets — no fabricated AI answers.
        </p>
        {data?.engine && (
          <p className="mt-1 text-2xs text-terminal-muted mono">{data.engine}</p>
        )}
      </div>

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
          <span className="mono">{data.kind}</span>
          {" · "}
          {data.explanation}
          {" · "}
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

function ResultCard({ item }: { item: ResearchItem }) {
  return (
    <div className="panel p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-2xs uppercase tracking-wide text-terminal-muted">
            {item.type}
          </div>
          <div className="mt-0.5 text-sm font-medium">{item.title}</div>
          <p className="mt-1 text-xs text-terminal-dim">{item.summary}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-2xs">
          {item.wallet && (
            <>
              <Link
                href={`/wallets/${item.wallet}`}
                className="mono text-terminal-accent hover:underline"
              >
                {shortAddr(item.wallet, 5)}
              </Link>
              <CopyButton value={item.wallet} label="CA" />
              <Link
                href={`/time-machine`}
                className="text-terminal-muted hover:underline"
                title="Paste wallet in Time Machine"
              >
                Timeline
              </Link>
            </>
          )}
          {item.wallet_b && (
            <Link
              href={`/wallets/${item.wallet_b}`}
              className="mono text-terminal-accent hover:underline"
            >
              + {shortAddr(item.wallet_b, 5)}
            </Link>
          )}
          {item.mint && (
            <Link
              href={`/tokens/${item.mint}`}
              className="mono text-terminal-accent hover:underline"
            >
              mint {shortAddr(item.mint, 4)}
            </Link>
          )}
          {item.entity_id && (
            <Link
              href={`/entities/${item.entity_id}`}
              className="text-terminal-accent hover:underline"
            >
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
