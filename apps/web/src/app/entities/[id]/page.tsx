"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, ageFrom, shortAddr } from "@/lib/api/client";
import type { EntityDetail } from "@/types";
import { CopyButton } from "@/components/ui/CopyButton";

export default function EntityDetailPage() {
  const params = useParams();
  const id = String(params.id || "");
  const [data, setData] = useState<EntityDetail | null>(null);

  useEffect(() => {
    if (!id) return;
    api
      .entity(id)
      .then(setData)
      .catch(() =>
        setData({ available: false, entity_id: id, message: "API error" })
      );
  }, [id]);

  if (!data) {
    return <div className="p-6 text-sm text-terminal-muted">Loading entity…</div>;
  }

  if (!data.available || !data.entity) {
    return (
      <div className="p-6">
        <div className="panel p-4 text-sm">
          <div className="font-medium">Entity not found</div>
          <p className="mt-1 text-xs text-terminal-muted mono">{id}</p>
        </div>
      </div>
    );
  }

  const e = data.entity;

  return (
    <div className="space-y-4 p-4">
      <div className="panel p-4">
        <h1 className="text-sm font-medium uppercase tracking-wide text-terminal-dim">
          Entity
        </h1>
        <div className="mt-2 grid gap-3 text-xs md:grid-cols-4">
          <div>
            <div className="text-terminal-muted">Primary wallet</div>
            <div className="mt-0.5 flex items-center gap-2 mono">
              {shortAddr(e.primary_wallet, 6)}
              {e.primary_wallet && (
                <CopyButton value={e.primary_wallet} label="Copy" />
              )}
            </div>
          </div>
          <div>
            <div className="text-terminal-muted">Type</div>
            <div>{e.entity_type || "—"}</div>
          </div>
          <div>
            <div className="text-terminal-muted">Launches</div>
            <div className="tabular text-lg font-semibold">{e.launch_count ?? 0}</div>
          </div>
          <div>
            <div className="text-terminal-muted">Confidence</div>
            <div className="tabular">
              {e.confidence != null
                ? `${(Number(e.confidence) * 100).toFixed(0)}%`
                : "—"}
            </div>
          </div>
        </div>
        <p className="mt-3 text-2xs text-terminal-muted mono">id {e.entity_id}</p>
      </div>

      <div className="panel overflow-x-auto">
        <div className="border-b border-terminal-border px-3 py-2 text-2xs uppercase text-terminal-muted">
          Linked wallets
        </div>
        <table className="w-full text-left text-xs">
          <thead className="text-2xs text-terminal-muted">
            <tr className="border-b border-terminal-border">
              <th className="px-3 py-2">Wallet</th>
              <th className="px-2 py-2">Role</th>
              <th className="px-2 py-2">Link</th>
              <th className="px-2 py-2">Conf</th>
            </tr>
          </thead>
          <tbody>
            {(data.wallets || []).length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-6 text-terminal-muted">
                  No entity_wallets rows.
                </td>
              </tr>
            )}
            {(data.wallets || []).map((w, i) => (
              <tr key={i} className="border-b border-terminal-border/40">
                <td className="px-3 py-1.5">
                  {w.wallet ? (
                    <Link
                      href={`/wallets/${w.wallet}`}
                      className="mono hover:text-terminal-accent"
                    >
                      {shortAddr(w.wallet, 6)}
                    </Link>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-2 py-1.5">{w.role || "—"}</td>
                <td className="px-2 py-1.5 text-terminal-dim">{w.link_reason || "—"}</td>
                <td className="px-2 py-1.5 tabular">
                  {w.confidence != null
                    ? `${(Number(w.confidence) * 100).toFixed(0)}%`
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel overflow-x-auto">
        <div className="border-b border-terminal-border px-3 py-2 text-2xs uppercase text-terminal-muted">
          Launch history (primary deployer)
        </div>
        <table className="w-full text-left text-xs">
          <thead className="text-2xs text-terminal-muted">
            <tr className="border-b border-terminal-border">
              <th className="px-3 py-2">Token</th>
              <th className="px-2 py-2">When</th>
              <th className="px-2 py-2">Score</th>
              <th className="px-2 py-2">CA</th>
            </tr>
          </thead>
          <tbody>
            {(data.launches || []).length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-6 text-terminal-muted">
                  No token.launch events for primary wallet.
                </td>
              </tr>
            )}
            {(data.launches || []).map((l, i) => (
              <tr key={i} className="border-b border-terminal-border/40">
                <td className="px-3 py-1.5">
                  {l.mint ? (
                    <Link
                      href={`/tokens/${l.mint}`}
                      className="hover:text-terminal-accent"
                    >
                      {l.symbol || l.name || shortAddr(l.mint)}
                    </Link>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-2 py-1.5 tabular">{ageFrom(l.occurred_at)}</td>
                <td className="px-2 py-1.5 tabular">
                  {l.stinky_score != null ? Number(l.stinky_score).toFixed(0) : "—"}
                </td>
                <td className="px-2 py-1.5 mono text-terminal-dim">
                  {shortAddr(l.mint)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
