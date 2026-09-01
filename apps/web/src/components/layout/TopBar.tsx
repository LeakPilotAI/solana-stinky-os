"use client";

import { useEffect, useState } from "react";
import type { SystemHealth } from "@/types";
import { api } from "@/lib/api/client";

function StatusDot({
  ok,
  label,
  detail,
}: {
  ok: boolean;
  label: string;
  detail?: string;
}) {
  return (
    <span className="flex items-center gap-1.5 text-[11px]">
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          ok
            ? "bg-terminal-accent shadow-[0_0_6px_#39ff14]"
            : "bg-terminal-danger"
        }`}
      />
      <span className={ok ? "text-terminal-dim" : "text-terminal-danger"}>
        {label}
      </span>
      {detail && (
        <span className={ok ? "text-terminal-muted" : "text-terminal-danger/80"}>
          {detail}
        </span>
      )}
    </span>
  );
}

export function TopBar({ onOpenSearch }: { onOpenSearch: () => void }) {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    let fails = 0;
    const tick = async () => {
      const t0 = performance.now();
      try {
        const h = await api.health();
        const ms = Math.round(performance.now() - t0);
        if (!cancelled) {
          fails = 0;
          setHealth(h);
          setLatencyMs(ms);
        }
      } catch {
        // Sticky LIVE: one blip must not paint the whole OS offline
        fails += 1;
        if (!cancelled && fails >= 2) {
          setHealth({
            status: "down",
            service: "api",
            database: false,
            event_log: "down",
            live: false,
          });
          setLatencyMs(null);
        }
      }
    };
    tick();
    const id = setInterval(tick, 10000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const live = !!health?.live;
  const eventsOk =
    health?.event_log === "ok" ||
    health?.event_log === "up" ||
    health?.event_log === "connected" ||
    health?.event_log === "degraded";
  const apiOk = !!health?.database || health?.status === "ok";

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-terminal-border bg-[#070908] px-3">
      <button
        type="button"
        onClick={onOpenSearch}
        className="flex h-8 max-w-md flex-1 items-center gap-2 rounded-lg border border-terminal-border bg-[#0c100c] px-3 text-[12px] text-terminal-muted hover:border-terminal-accent/30"
      >
        <span className="text-terminal-muted">⌕</span>
        <span className="truncate">Search wallets, tokens, entities, patterns, CA…</span>
        <kbd className="ml-auto rounded border border-terminal-border bg-terminal-elevated px-1.5 py-0.5 text-[10px] text-terminal-muted">
          CTRL K
        </kbd>
      </button>

      <div className="hidden items-center gap-3 lg:flex">
        <StatusDot ok={live} label="Live" detail="Solana Mainnet" />
        <StatusDot
          ok={apiOk}
          label="API"
          detail={latencyMs != null ? `${latencyMs}ms` : undefined}
        />
        <StatusDot ok={eventsOk} label="Events" />
        <StatusDot ok={live} label="Sentinel" detail={live ? "Live" : "Down"} />
        <StatusDot ok={apiOk} label="Collector" detail={apiOk ? "Live" : "—"} />
      </div>

      <span
        className={`ml-auto rounded-md px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide ${
          live
            ? "bg-terminal-accent/15 text-terminal-accent"
            : "bg-terminal-danger/15 text-terminal-danger"
        }`}
      >
        {live ? "LIVE" : "OFFLINE"}
      </span>
    </header>
  );
}
