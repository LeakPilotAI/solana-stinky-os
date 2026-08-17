"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, shortAddr } from "@/lib/api/client";
import type { SearchResult } from "@/types";

const BASE58_RE =
  /^[1-9A-HJ-NP-Za-km-z]{32,50}$/;

function looksLikeAddress(s: string): boolean {
  return BASE58_RE.test(s.trim());
}

function looksLikeMint(s: string): boolean {
  const t = s.trim();
  return looksLikeAddress(t) && (t.endsWith("pump") || t.length >= 40);
}

export function CommandPalette({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    if (!open) {
      setQ("");
      setResult(null);
      setError(null);
      return;
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open || q.trim().length < 2) {
      setResult(null);
      return;
    }
    let cancelled = false;
    const t = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const r = await api.search(q.trim());
        if (!cancelled) setResult(r);
      } catch (e) {
        if (!cancelled) {
          setResult(null);
          setError(e instanceof Error ? e.message : "search failed");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 150);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [q, open]);

  const go = (path: string) => {
    router.push(path);
    onClose();
  };

  const openDirect = () => {
    const t = q.trim();
    if (!t) return;
    if (looksLikeMint(t)) go(`/tokens/${t}`);
    else if (looksLikeAddress(t)) go(`/wallets/${t}`);
    else go(`/research?q=${encodeURIComponent(t)}`);
  };

  if (!open) return null;

  const trimmed = q.trim();
  const hasHits =
    result &&
    (result.tokens.length > 0 ||
      result.wallets.length > 0 ||
      result.entities.length > 0);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 pt-[12vh]">
      <div className="w-full max-w-xl overflow-hidden rounded-lg border border-terminal-border bg-terminal-panel shadow-2xl">
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (result?.tokens?.[0]?.mint) go(`/tokens/${result.tokens[0].mint}`);
              else if (result?.wallets?.[0]?.wallet)
                go(`/wallets/${result.wallets[0].wallet}`);
              else openDirect();
            }
          }}
          placeholder="Paste CA / wallet — Enter opens · Ctrl+K"
          className="w-full border-b border-terminal-border bg-transparent px-4 py-3 font-mono text-sm outline-none placeholder:font-sans placeholder:text-terminal-muted"
        />
        <div className="max-h-96 overflow-y-auto p-2 text-sm">
          {loading && (
            <div className="px-2 py-3 text-xs text-terminal-muted">Searching store…</div>
          )}
          {error && (
            <div className="px-2 py-2 text-xs text-rose-300">API: {error}</div>
          )}

          {trimmed.length >= 2 && looksLikeAddress(trimmed) && (
            <Section title="Open directly">
              {looksLikeMint(trimmed) && (
                <Row
                  label="Token / CA page"
                  sub={shortAddr(trimmed, 6)}
                  onClick={() => go(`/tokens/${trimmed}`)}
                />
              )}
              <Row
                label="Wallet page"
                sub={shortAddr(trimmed, 6)}
                onClick={() => go(`/wallets/${trimmed}`)}
              />
              <Row
                label="Research this CA"
                sub="measured lookup"
                onClick={() => go(`/research?q=${encodeURIComponent(trimmed)}`)}
              />
            </Section>
          )}

          {!loading && trimmed.length >= 2 && result && (
            <>
              <Section title="Tokens in store">
                {result.tokens.length === 0 && <Empty />}
                {result.tokens.map((t) => (
                  <Row
                    key={t.mint}
                    label={t.symbol || t.name || shortAddr(t.mint)}
                    sub={shortAddr(t.mint, 6)}
                    onClick={() => go(`/tokens/${t.mint}`)}
                  />
                ))}
              </Section>
              <Section title="Wallets">
                {result.wallets.length === 0 && <Empty />}
                {result.wallets.map((w) => (
                  <Row
                    key={w.wallet}
                    label={shortAddr(w.wallet, 6)}
                    sub={`early ${w.early_buy_count ?? 0}`}
                    onClick={() => go(`/wallets/${w.wallet}`)}
                  />
                ))}
              </Section>
              <Section title="Entities">
                {result.entities.length === 0 && <Empty />}
                {result.entities.map((e) => (
                  <Row
                    key={e.entity_id}
                    label={shortAddr(e.primary_wallet || e.entity_id, 6)}
                    sub={`launches ${e.launch_count ?? 0}`}
                    onClick={() => go(`/entities/${e.entity_id}`)}
                  />
                ))}
              </Section>
              {!hasHits && !looksLikeAddress(trimmed) && (
                <div className="px-2 py-2 text-xs text-terminal-muted">
                  No store matches. Try a full CA or wallet address.
                </div>
              )}
            </>
          )}

          {trimmed.length < 2 && (
            <div className="px-2 py-3 text-xs text-terminal-muted">
              Paste a full mint (…pump) or wallet. Enter opens the page even if the
              store has not indexed it yet.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-2">
      <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-terminal-muted">
        {title}
      </div>
      {children}
    </div>
  );
}

function Empty() {
  return <div className="px-2 py-1 text-xs text-terminal-muted">No matches</div>;
}

function Row({
  label,
  sub,
  onClick,
}: {
  label: string;
  sub?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left hover:bg-terminal-elevated"
    >
      <span>{label}</span>
      {sub && (
        <span className="font-mono text-xs text-terminal-muted">{sub}</span>
      )}
    </button>
  );
}
