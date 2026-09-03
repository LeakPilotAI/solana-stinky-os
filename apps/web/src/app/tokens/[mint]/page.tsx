"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, fmtUsd, shortAddr } from "@/lib/api/client";
import { CopyButton } from "@/components/ui/CopyButton";

export default function TokenPage() {
  const params = useParams();
  const mint = String(params.mint || "");
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [happened, setHappened] = useState<Record<string, unknown> | null>(null);
  const [recipe, setRecipe] = useState<Record<string, unknown> | null>(null);
  const [quality, setQuality] = useState<Record<string, unknown> | null>(null);
  const [coord, setCoord] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (!mint) return;
    api.token(mint).then(setData).catch(() => setData({ available: false }));
    api.bookWhatHappened(mint).then(setHappened).catch(() => setHappened(null));
    api.bookRecipe({ mint, exclude_mint: mint }).then(setRecipe).catch(() => setRecipe(null));
    api
      .bookQuality({ mint })
      .then((r) => {
        const rows = r.states || [];
        setQuality(rows.find((s) => s.mint === mint) || rows[0] || null);
      })
      .catch(() => setQuality(null));
    api.coordinationCase(mint).then(setCoord).catch(() => setCoord(null));
  }, [mint]);

  if (!data) {
    return <div className="p-6 text-sm text-terminal-muted">Loading…</div>;
  }

  if (!data.available) {
    return (
      <div className="p-6">
        <div className="panel p-4 text-sm">
          <div className="font-medium">No stored intelligence</div>
          <p className="mt-1 text-terminal-muted mono text-xs">{mint}</p>
          <p className="mt-2 text-xs text-terminal-dim">
            This mint is not in migration_tracks / events yet.
          </p>
        </div>
      </div>
    );
  }

  const launch = (data.launch || {}) as Record<string, unknown>;
  const alert = (data.alert || {}) as Record<string, unknown>;
  const track = (data.track || {}) as Record<string, unknown>;
  const buyers = (data.buyers || []) as Array<Record<string, unknown>>;
  const explanation = (alert.score_explanation || []) as Array<{
    delta?: number;
    reason?: string;
  }>;

  const name = (launch.name || alert.name || shortAddr(mint)) as string;
  const symbol = (launch.symbol || alert.symbol || "") as string;
  const score = alert.stinky_score as number | undefined;
  const conf = alert.confidence as number | undefined;

  return (
    <div className="space-y-4 p-4">
      {coord && coord.empty !== true && (
        <div className="panel p-4 text-[11px]">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-terminal-muted">
            Coordinated case
          </div>
          <p className="mt-1 text-terminal-dim">
            {String(coord.lifecycle || "UNKNOWN")} · quality {String(coord.quality || "UNKNOWN")} · id{" "}
            <span className="font-mono">{String(coord.investigation_id || "—")}</span>
          </p>
          <p className="mt-1 text-terminal-muted">
            Unknowns:{" "}
            {Array.isArray(coord.unknowns) && coord.unknowns.length
              ? (coord.unknowns as string[]).join(", ")
              : "none recorded"}
            . Not a buy. calibrated_probability false.
          </p>
          <div className="mt-2 flex flex-wrap gap-3 text-[10px]">
            <a className="text-terminal-accent hover:underline" href="/investigations">Investigations</a>
            <a className="text-terminal-accent hover:underline" href="/observations">Observations</a>
            <a className="text-terminal-accent hover:underline" href="/dips">Quality</a>
            <a className="text-terminal-accent hover:underline" href="/wallets">Wallets</a>
          </div>
        </div>
      )}
      <div className="panel p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold">
              {name}
              {symbol ? ` · ${symbol}` : ""}
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
              <code className="mono text-terminal-dim">{mint}</code>
              <CopyButton value={mint} label="Copy CA" />
            </div>
            <div className="mt-2 flex flex-wrap gap-3 text-xs text-terminal-dim">
              <a
                className="hover:text-terminal-accent"
                href={`https://axiom.trade/t/${mint}`}
                target="_blank"
                rel="noreferrer"
              >
                Axiom
              </a>
              <a
                className="hover:text-terminal-accent"
                href={`https://dexscreener.com/solana/${mint}`}
                target="_blank"
                rel="noreferrer"
              >
                DexScreener
              </a>
              <a
                className="hover:text-terminal-accent"
                href={`https://solscan.io/token/${mint}`}
                target="_blank"
                rel="noreferrer"
              >
                Solscan
              </a>
            </div>
          </div>
          <div className="text-right">
            <div className="text-2xs uppercase text-terminal-muted">Stinky Score</div>
            <div className="text-3xl font-semibold tabular">
              {alert.has_intelligence && score != null ? Number(score).toFixed(0) : "UNK"}
              <span className="text-base text-terminal-muted">/100</span>
            </div>
            <div className="text-xs text-terminal-dim">
              {alert.has_intelligence
                ? `Confidence ${
                    conf != null
                      ? `${(Number(conf) <= 1 ? Number(conf) * 100 : Number(conf)).toFixed(0)}%`
                      : "—"
                  }`
                : "INSUFFICIENT EVIDENCE — not a grade"}
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="panel p-3">
          <h2 className="text-2xs uppercase tracking-wide text-terminal-muted">
            Why this score
          </h2>
          {explanation.length === 0 ? (
            <p className="mt-2 text-xs text-terminal-dim">
              No score_explanation on stored alert for this mint.
            </p>
          ) : (
            <ul className="mt-2 space-y-1 text-xs">
              {explanation.map((e, i) => (
                <li key={i} className="flex gap-2">
                  <span className="tabular text-terminal-dim">
                    {e.delta != null && e.delta >= 0 ? "+" : ""}
                    {e.delta}
                  </span>
                  <span>{e.reason}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="panel p-3">
          <h2 className="text-2xs uppercase tracking-wide text-terminal-muted">
            Migration track
          </h2>
          <dl className="mt-2 grid grid-cols-2 gap-2 text-xs">
            <div>
              <dt className="text-terminal-muted">Status</dt>
              <dd>{(track.status as string) || "—"}</dd>
            </div>
            <div>
              <dt className="text-terminal-muted">Buyers captured</dt>
              <dd className="tabular">{(track.buyers_captured as number) ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-terminal-muted">Pool</dt>
              <dd className="mono">{shortAddr(track.pool as string)}</dd>
            </div>
            <div>
              <dt className="text-terminal-muted">Creator</dt>
              <dd className="mono">{shortAddr(track.creator as string)}</dd>
            </div>
          </dl>
          {alert.volume_m5_usd != null && (
            <p className="mt-2 text-xs">
              Alert vol 5m: {fmtUsd(Number(alert.volume_m5_usd))}
            </p>
          )}
        </div>
      </div>

      {happened && (
        <div className="panel p-3">
          <h2 className="text-2xs uppercase tracking-wide text-terminal-muted">What happened next</h2>
          <p className="mt-1 text-[11px] text-terminal-dim">
            Stored ticks only. Missing offsets stay UNKNOWN. Outcome is later, not a decision input.
          </p>
          <dl className="mt-2 grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
            <div>
              <dt className="text-terminal-muted">Peak 5m vol</dt>
              <dd className="tabular">
                {happened.peak_volume == null && happened.peakVolume == null
                  ? "UNKNOWN"
                  : fmtUsd(Number(happened.peak_volume ?? happened.peakVolume))}
              </dd>
            </div>
            <div>
              <dt className="text-terminal-muted">Peak price</dt>
              <dd className="tabular">
                {happened.peak_price == null && happened.peakPrice == null
                  ? "UNKNOWN"
                  : String(happened.peak_price ?? happened.peakPrice)}
              </dd>
            </div>
            <div>
              <dt className="text-terminal-muted">Later outcome</dt>
              <dd>
                {(() => {
                  const oc = happened.outcome;
                  if (oc && typeof oc === "object" && oc !== null && "label" in oc) {
                    return String((oc as { label?: string }).label || "UNKNOWN");
                  }
                  return typeof oc === "string" ? oc : "UNKNOWN";
                })()}
              </dd>
            </div>
            <div>
              <dt className="text-terminal-muted">Source</dt>
              <dd>{String(happened.source || "—")}</dd>
            </div>
          </dl>
        </div>
      )}

      {quality && (
        <div className="panel p-3">
          <h2 className="text-2xs uppercase tracking-wide text-terminal-muted">Quality state</h2>
          <p className="mt-1 text-[11px] text-terminal-dim">
            Setup after Gate 1. Not a buy. Missing later ticks stay UNKNOWN.
          </p>
          <dl className="mt-2 grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
            <div>
              <dt className="text-terminal-muted">State</dt>
              <dd>{String(quality.state || "UNKNOWN")}</dd>
            </div>
            <div>
              <dt className="text-terminal-muted">Previous</dt>
              <dd>{String(quality.previous_state || "UNKNOWN")}</dd>
            </div>
            <div>
              <dt className="text-terminal-muted">Severity</dt>
              <dd>{String(quality.severity || "—")}</dd>
            </div>
            <div>
              <dt className="text-terminal-muted">Evidence</dt>
              <dd>{String(quality.evidence_quality || "UNKNOWN")}</dd>
            </div>
          </dl>
          {Array.isArray(quality.why) &&
            (quality.why as Array<{ explanation?: string }>).map((w, i) => (
              <p key={i} className="mt-1 text-[11px] text-terminal-muted">
                {typeof w === "string" ? w : w.explanation}
              </p>
            ))}
          {Array.isArray(quality.unknown) && (quality.unknown as string[]).length > 0 && (
            <p className="mt-1 text-[11px] text-terminal-dim">
              UNKNOWN: {(quality.unknown as string[]).join(", ")}
            </p>
          )}
        </div>
      )}

      {recipe && (
        <div className="panel p-3">
          <h2 className="text-2xs uppercase tracking-wide text-terminal-muted">Runner recipe</h2>
          <p className="mt-1 text-[11px] text-terminal-dim">{String(recipe.note || "Not a probability.")}</p>
          <p className="mt-2 text-xs text-terminal-muted">
            Analogues {String(recipe.analogue_count ?? 0)} · RUNNER {String(recipe.runner_count ?? 0)} / FADE{" "}
            {String(recipe.fade_count ?? 0)} / HELD {String(recipe.held_count ?? 0)}
          </p>
          {recipe.sample_sufficient !== true && (
            <p className="mt-1 text-[11px] text-terminal-muted">
              UNKNOWN — need 5 or more historical analogues as-of.
            </p>
          )}
        </div>
      )}

      <div className="panel overflow-x-auto">
        <div className="border-b border-terminal-border px-3 py-2 text-2xs uppercase text-terminal-muted">
          Early buyers
        </div>
        <table className="w-full text-left text-xs">
          <thead className="text-2xs text-terminal-muted">
            <tr className="border-b border-terminal-border">
              <th className="px-3 py-2">Rank</th>
              <th className="px-2 py-2">Wallet</th>
              <th className="px-2 py-2">SOL</th>
              <th className="px-2 py-2">Meaningful</th>
            </tr>
          </thead>
          <tbody>
            {buyers.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-6 text-terminal-muted">
                  No migration_buyers for this mint.
                </td>
              </tr>
            )}
            {buyers.map((b) => (
              <tr key={String(b.rank)} className="border-b border-terminal-border/40">
                <td className="px-3 py-1.5 tabular">{String(b.rank)}</td>
                <td className="px-2 py-1.5 mono">{shortAddr(b.wallet as string, 6)}</td>
                <td className="px-2 py-1.5 tabular">
                  {b.sol_spent != null ? Number(b.sol_spent).toFixed(3) : "—"}
                </td>
                <td className="px-2 py-1.5">{b.is_meaningful ? "yes" : "no"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
