"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, shortAddr } from "@/lib/api/client";

export default function RecipesPage() {
  const [mint, setMint] = useState("");
  const [fp, setFp] = useState("");
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    setLoading(true);
    setError(null);
    try {
      const r = await api.bookRecipe({
        mint: mint.trim() || undefined,
        fingerprint: fp.trim() || undefined,
        exclude_mint: mint.trim() || undefined,
      });
      setData(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed");
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    api
      .bookObservations()
      .then((r) => {
        const first = (r.observations || [])[0] as { mint?: string; fingerprint?: string } | undefined;
        if (first?.mint && !mint) setMint(first.mint);
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const traits = (Array.isArray(data?.common_traits) ? data?.common_traits : []) as Array<{
    band?: string;
    note?: string;
  }>;
  const runners = (Array.isArray(data?.runner_matches) ? data?.runner_matches : []) as Array<{
    mint?: string;
    strength?: string;
  }>;
  const fades = (Array.isArray(data?.fade_matches) ? data?.fade_matches : []) as Array<{
    mint?: string;
    strength?: string;
  }>;

  return (
    <div className="space-y-3 p-4">
      <header>
        <h1 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-terminal-dim">
          Runner recipes
        </h1>
        <p className="mt-1 text-[11px] text-terminal-muted">
          Historical RUNNER analogues as-of the current fingerprint. Not a probability. Sample under 5 stays UNKNOWN.
        </p>
      </header>
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void run();
        }}
      >
        <input
          value={mint}
          onChange={(e) => setMint(e.target.value)}
          placeholder="Mint / CA"
          className="w-64 rounded border border-terminal-border bg-black/40 px-2 py-1.5 font-mono text-[11px] outline-none"
        />
        <input
          value={fp}
          onChange={(e) => setFp(e.target.value)}
          placeholder="Fingerprint (optional)"
          className="min-w-[16rem] flex-1 rounded border border-terminal-border bg-black/40 px-2 py-1.5 font-mono text-[11px] outline-none"
        />
        <button
          type="submit"
          className="rounded border border-terminal-border px-3 py-1.5 text-[11px] text-terminal-text hover:border-terminal-accent/40"
        >
          Compare
        </button>
      </form>
      {error && <p className="text-xs text-rose-300">API: {error}</p>}
      {loading && <p className="text-xs text-terminal-muted">Querying book…</p>}
      {data && (
        <>
          <section className="panel p-3 text-[11px]">
            <div className="text-[10px] uppercase tracking-wider text-terminal-muted">Analogues</div>
            <p className="mt-1 text-terminal-dim">
              {String(data.analogue_count ?? 0)} historical · RUNNER {String(data.runner_count ?? 0)} / HELD{" "}
              {String(data.held_count ?? 0)} / FADE {String(data.fade_count ?? 0)} · not a probability
            </p>
            <p className="mt-1 text-terminal-muted">{String(data.note || "")}</p>
          </section>
          <section className="panel p-3 text-[11px]">
            <div className="text-[10px] uppercase tracking-wider text-terminal-muted">Common traits among RUNNER analogues</div>
            {data.sample_sufficient !== true ? (
              <p className="mt-2 text-terminal-muted">UNKNOWN — need 5 or more historical analogues as-of.</p>
            ) : traits.length === 0 ? (
              <p className="mt-2 text-terminal-muted">No shared observed bands among RUNNER analogues.</p>
            ) : (
              <ul className="mt-2 space-y-1">
                {traits.map((t) => (
                  <li key={t.band}>{t.note}</li>
                ))}
              </ul>
            )}
          </section>
          <section className="panel p-3 text-[11px]">
            <div className="text-[10px] uppercase tracking-wider text-terminal-muted">Matches</div>
            {runners.length + fades.length === 0 ? (
              <p className="mt-2 text-terminal-muted">No analogues stored yet.</p>
            ) : (
              <ul className="mt-2 space-y-1 font-mono">
                {runners.map((m) => (
                  <li key={`r-${m.mint}`}>
                    {m.mint ? (
                      <Link href={`/tokens/${m.mint}`} className="hover:text-terminal-accent">
                        RUNNER {shortAddr(m.mint, 4)} · {m.strength}
                      </Link>
                    ) : null}
                  </li>
                ))}
                {fades.map((m) => (
                  <li key={`f-${m.mint}`}>
                    {m.mint ? (
                      <Link href={`/tokens/${m.mint}`} className="hover:text-terminal-accent">
                        FADE {shortAddr(m.mint, 4)} · {m.strength}
                      </Link>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
