"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, ageFrom, fmtPct, shortAddr, tierClass } from "@/lib/api/client";
import type { WalletDetail } from "@/types";
import { CopyButton } from "@/components/ui/CopyButton";

export default function WalletDetailPage() {
  const params = useParams();
  const address = String(params.address || "");
  const [data, setData] = useState<WalletDetail | null>(null);

  useEffect(() => {
    if (!address) return;
    api
      .wallet(address)
      .then(setData)
      .catch(() =>
        setData({ available: false, wallet: address, message: "API error" })
      );
  }, [address]);

  if (!data) {
    return <div className="p-6 text-sm text-terminal-muted">Loading wallet…</div>;
  }

  if (!data.available) {
    return (
      <div className="p-6">
        <div className="panel p-4 text-sm">
          <div className="font-medium">No stored intelligence</div>
          <p className="mt-1 mono text-xs text-terminal-dim">{address}</p>
          <p className="mt-2 text-xs text-terminal-muted">
            {data.message || "Not seen in performance or early buyers yet."}
          </p>
          <a
            className="mt-3 inline-block text-xs text-terminal-accent"
            href={`https://solscan.io/account/${address}`}
            target="_blank"
            rel="noreferrer"
          >
            Open on Solscan →
          </a>
        </div>
      </div>
    );
  }

  const p = data.performance;

  return (
    <div className="space-y-4 p-4">
      <div className="panel p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-sm font-medium uppercase tracking-wide text-terminal-dim">
              Wallet
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <code className="mono text-xs">{address}</code>
              <CopyButton value={address} label="Copy" />
              <a
                className="text-xs text-terminal-accent hover:underline"
                href={`https://solscan.io/account/${address}`}
                target="_blank"
                rel="noreferrer"
              >
                Solscan
              </a>
            </div>
          </div>
          <div className="text-right">
            <div className="text-2xs uppercase text-terminal-muted">Watch score</div>
            <div className="text-3xl font-semibold tabular">
              {data.watch_score != null ? data.watch_score.toFixed(0) : "—"}
            </div>
            <div className={`text-xs ${tierClass(data.watch_tier)}`}>
              {data.watch_tier} · conf{" "}
              {data.watch_confidence != null
                ? `${(data.watch_confidence * 100).toFixed(0)}%`
                : "—"}
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="panel p-3">
          <h2 className="text-2xs uppercase tracking-wide text-terminal-muted">
            Why watch
          </h2>
          <ul className="mt-2 space-y-1 text-xs">
            {(data.why_watch || []).length === 0 && (
              <li className="text-terminal-dim">No measured signals yet.</li>
            )}
            {(data.why_watch || []).map((r, i) => (
              <li key={i}>· {r}</li>
            ))}
          </ul>
        </div>
        <div className="panel p-3">
          <h2 className="text-2xs uppercase tracking-wide text-terminal-muted">
            Performance
          </h2>
          <dl className="mt-2 grid grid-cols-2 gap-2 text-xs">
            <div>
              <dt className="text-terminal-muted">Early</dt>
              <dd className="tabular">{p?.early_buy_count ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-terminal-muted">Tokens</dt>
              <dd className="tabular">{p?.tokens_purchased ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-terminal-muted">Buys / Sells</dt>
              <dd className="tabular">
                {p?.total_buys ?? 0} / {p?.total_sells ?? 0}
              </dd>
            </div>
            <div>
              <dt className="text-terminal-muted">Hit rate</dt>
              <dd className="tabular">{fmtPct(p?.hit_rate)}</dd>
            </div>
            <div>
              <dt className="text-terminal-muted">Avg return</dt>
              <dd className="tabular">
                {p?.avg_return_pct != null
                  ? `${Number(p.avg_return_pct).toFixed(0)}%`
                  : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-terminal-muted">Best</dt>
              <dd className="tabular">
                {p?.max_return_pct != null
                  ? `${Number(p.max_return_pct).toFixed(0)}%`
                  : "—"}
              </dd>
            </div>
          </dl>
        </div>
      </div>

      {data.entity && (
        <div className="panel p-3 text-xs">
          <h2 className="text-2xs uppercase tracking-wide text-terminal-muted">
            Linked entity
          </h2>
          <div className="mt-2 flex flex-wrap gap-4">
            <Link
              href={`/entities/${data.entity.entity_id}`}
              className="text-terminal-accent hover:underline"
            >
              Open entity
            </Link>
            <span>role {data.entity.role || "—"}</span>
            <span>launches {data.entity.launch_count ?? 0}</span>
          </div>
        </div>
      )}

      <div className="panel overflow-x-auto">
        <div className="border-b border-terminal-border px-3 py-2 text-2xs uppercase text-terminal-muted">
          Early migration entries
        </div>
        <table className="w-full text-left text-xs">
          <thead className="text-2xs text-terminal-muted">
            <tr className="border-b border-terminal-border">
              <th className="px-3 py-2">Mint</th>
              <th className="px-2 py-2">Rank</th>
              <th className="px-2 py-2">SOL</th>
              <th className="px-2 py-2">When</th>
              <th className="px-2 py-2">Creator</th>
            </tr>
          </thead>
          <tbody>
            {(data.early_entries || []).length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-terminal-muted">
                  No migration_buyers for this wallet.
                </td>
              </tr>
            )}
            {(data.early_entries || []).map((e, i) => (
              <tr key={i} className="border-b border-terminal-border/40">
                <td className="px-3 py-1.5">
                  {e.mint ? (
                    <Link
                      href={`/tokens/${e.mint}`}
                      className="mono hover:text-terminal-accent"
                    >
                      {shortAddr(e.mint, 5)}
                    </Link>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-2 py-1.5 tabular">{e.rank ?? "—"}</td>
                <td className="px-2 py-1.5 tabular">
                  {e.sol_spent != null ? Number(e.sol_spent).toFixed(3) : "—"}
                </td>
                <td className="px-2 py-1.5 tabular">{ageFrom(e.bought_at)}</td>
                <td className="px-2 py-1.5 mono">{shortAddr(e.creator, 4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel overflow-x-auto">
        <div className="border-b border-terminal-border px-3 py-2 text-2xs uppercase text-terminal-muted">
          Recent trades
        </div>
        <table className="w-full text-left text-xs">
          <thead className="text-2xs text-terminal-muted">
            <tr className="border-b border-terminal-border">
              <th className="px-3 py-2">Side</th>
              <th className="px-2 py-2">Mint</th>
              <th className="px-2 py-2">SOL</th>
              <th className="px-2 py-2">Early</th>
              <th className="px-2 py-2">When</th>
            </tr>
          </thead>
          <tbody>
            {(data.recent_trades || []).length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-terminal-muted">
                  No wallet_trades yet.
                </td>
              </tr>
            )}
            {(data.recent_trades || []).map((t, i) => (
              <tr key={i} className="border-b border-terminal-border/40">
                <td className="px-3 py-1.5">{t.side}</td>
                <td className="px-2 py-1.5 mono">
                  {t.mint ? (
                    <Link
                      href={`/tokens/${t.mint}`}
                      className="hover:text-terminal-accent"
                    >
                      {shortAddr(t.mint, 5)}
                    </Link>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-2 py-1.5 tabular">
                  {t.sol_amount != null ? Number(t.sol_amount).toFixed(3) : "—"}
                </td>
                <td className="px-2 py-1.5">
                  {t.is_early_buyer ? `yes #${t.early_rank ?? ""}` : "—"}
                </td>
                <td className="px-2 py-1.5 tabular">{ageFrom(t.traded_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
