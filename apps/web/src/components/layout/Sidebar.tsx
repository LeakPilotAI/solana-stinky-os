"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import clsx from "clsx";
import { api, shortAddr, fmtPct } from "@/lib/api/client";
import type { SmartWallet } from "@/types";

const NAV = [
  { href: "/command-center", label: "Command Center", key: "C", icon: "⌂" },
  { href: "/runners", label: "Live Runners", key: "R", icon: "◎" },
  { href: "/investigations", label: "Investigations", key: "V", icon: "▣" },
  { href: "/wallets", label: "Wallets", key: "W", icon: "◇" },
  { href: "/entities", label: "Entities", key: "E", icon: "⬡" },
  { href: "/smart-money", label: "Smart Money", key: "S", icon: "◈" },
  { href: "/alerts", label: "Alerts", key: "A", icon: "◉" },
  { href: "/patterns", label: "Patterns", key: "P", icon: "✦" },
  { href: "/recipes", label: "Runner Recipes", key: "Y", icon: "≡" },
  { href: "/observations", label: "Observation Book", key: "O", icon: "◷" },
  { href: "/unknown", label: "Unknown Queue", key: "U", icon: "?" },
  { href: "/dips", label: "Quality Dips", key: "D", icon: "!" },
  { href: "/graph", label: "Graph", key: "G", icon: "⎔" },
  { href: "/time-machine", label: "Time Machine", key: "T", icon: "◷" },
  { href: "/research", label: "Research", key: "Q", icon: "⌕" },
  { href: "/backtest", label: "Backtest", key: "B", icon: "▣" },
  { href: "/health", label: "Dataset Health", key: "H", icon: "▦" },
];

const TIER_COLORS = [
  "bg-terminal-accent",
  "bg-sky-400",
  "bg-emerald-400",
  "bg-amber-400",
  "bg-fuchsia-400",
];

export function Sidebar() {
  const path = usePathname();
  const router = useRouter();
  const [watch, setWatch] = useState<SmartWallet[]>([]);

  const prefetch = useCallback(
    (href: string) => {
      try {
        router.prefetch(href);
      } catch {
        /* ignore */
      }
    },
    [router]
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await api.commandCenter();
        if (!cancelled) setWatch((d.smart_wallets || []).slice(0, 5));
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <aside className="flex h-full w-[210px] shrink-0 flex-col border-r border-terminal-border bg-[#070908]">
      <div className="flex h-12 items-center gap-2.5 border-b border-terminal-border px-3">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-terminal-accent/15 text-sm font-bold text-terminal-accent">
          S
        </div>
        <div className="min-w-0">
          <div className="text-[13px] font-semibold tracking-wide text-white">
            STINKY OS
          </div>
          <div className="text-[9px] text-terminal-muted">
            Solana Intelligence Terminal
          </div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto py-2">
        <ul className="space-y-0.5 px-2">
          {NAV.map((item) => {
            const active =
              path === item.href || path.startsWith(item.href + "/");
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  prefetch
                  onMouseEnter={() => prefetch(item.href)}
                  className={clsx(
                    "group flex items-center gap-2 rounded-md px-2.5 py-1.5 text-[12px] transition-colors",
                    active
                      ? "bg-terminal-accent/12 text-terminal-accent"
                      : "text-terminal-dim hover:bg-white/[0.03] hover:text-terminal-text"
                  )}
                >
                  <span
                    className={clsx(
                      "w-4 text-center text-[11px]",
                      active ? "text-terminal-accent" : "text-terminal-muted"
                    )}
                  >
                    {item.icon}
                  </span>
                  <span className="flex-1 truncate font-medium">{item.label}</span>
                  <span
                    className={clsx(
                      "text-[10px]",
                      active
                        ? "text-terminal-accent/60"
                        : "text-terminal-muted/50"
                    )}
                  >
                    {item.key}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>

        {/* Watchlist quick view — real smart wallets */}
        <div className="mt-3 border-t border-terminal-border px-2 pt-3">
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-terminal-muted">
              Watchlist
            </span>
            <Link
              href="/smart-money"
              className="text-[10px] text-terminal-muted hover:text-terminal-accent"
            >
              Manage
            </Link>
          </div>
          <ul className="space-y-1">
            {watch.length === 0 && (
              <li className="px-1 py-2 text-[10px] text-terminal-muted">
                No wallet perf yet
              </li>
            )}
            {watch.map((w, i) => (
              <li key={w.wallet}>
                <Link
                  href={`/wallets/${w.wallet}`}
                  className="flex items-center gap-2 rounded-md px-1.5 py-1 hover:bg-white/[0.03]"
                >
                  <span
                    className={`h-2 w-2 shrink-0 rounded-full ${TIER_COLORS[i % TIER_COLORS.length]}`}
                  />
                  <span className="mono min-w-0 flex-1 truncate text-[11px] text-terminal-dim">
                    {shortAddr(w.wallet, 4)}
                  </span>
                  <span className="text-[11px] font-semibold tabular text-terminal-accent">
                    {w.watch_score != null
                      ? Math.round(w.watch_score)
                      : w.early_buy_count ?? 0}
                  </span>
                  <span className="text-[10px] tabular text-terminal-muted">
                    {fmtPct(w.hit_rate)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          <Link
            href="/smart-money"
            className="mt-2 block px-1 text-[10px] text-terminal-muted hover:text-terminal-accent"
          >
            View All Watchlist
          </Link>
        </div>
      </nav>

      <div className="border-t border-terminal-border p-3">
        <div className="flex items-center gap-2 rounded-md border border-terminal-border bg-terminal-panel/50 px-3 py-2">
          <span className="h-2 w-2 rounded-full bg-terminal-accent shadow-[0_0_8px_#39ff14]" />
          <div className="min-w-0">
            <div className="text-[11px] font-medium text-terminal-text">
              Stinky Operator
            </div>
            <div className="text-[9px] text-terminal-muted">Local · Premium</div>
          </div>
        </div>
      </div>
    </aside>
  );
}
