"use client";

import { useState } from "react";

/**
 * Token / CA image via DexScreener CDN with letter fallback.
 * No API key. Fails soft if image 404.
 */
export function TokenImage({
  mint,
  label,
  size = 28,
  className = "",
}: {
  mint?: string | null;
  label?: string | null;
  size?: number;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const ch = (label || mint || "?")
    .replace(/^\$/, "")
    .charAt(0)
    .toUpperCase();
  const src =
    mint && mint.length >= 32 && !failed
      ? `https://dd.dexscreener.com/ds-data/tokens/solana/${mint}.png`
      : null;

  if (!src) {
    return (
      <div
        className={`flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-emerald-500/25 to-zinc-800 text-[10px] font-bold text-emerald-300 ${className}`}
        style={{ width: size, height: size }}
        title={mint || label || undefined}
      >
        {ch}
      </div>
    );
  }

  return (
    <div
      className={`relative shrink-0 overflow-hidden rounded-full bg-zinc-900 ring-1 ring-white/10 ${className}`}
      style={{ width: size, height: size }}
      title={mint || label || undefined}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={label || short(mint)}
        width={size}
        height={size}
        className="h-full w-full object-cover"
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
      />
    </div>
  );
}

function short(s?: string | null) {
  if (!s) return "?";
  return s.length > 8 ? `${s.slice(0, 4)}…` : s;
}

/** Wallet avatar — deterministic gradient from address (no external fetch). */
export function WalletImage({
  address,
  size = 28,
  className = "",
}: {
  address: string;
  size?: number;
  className?: string;
}) {
  const a = address || "?";
  let h = 0;
  for (let i = 0; i < a.length; i++) h = (h * 31 + a.charCodeAt(i)) >>> 0;
  const hue = h % 360;
  const ch = a.slice(0, 2);
  return (
    <div
      className={`flex shrink-0 items-center justify-center rounded-full text-[9px] font-bold text-white/90 ring-1 ring-white/10 ${className}`}
      style={{
        width: size,
        height: size,
        background: `linear-gradient(135deg, hsl(${hue} 55% 32%), hsl(${(hue + 40) % 360} 50% 18%))`,
      }}
      title={address}
    >
      {ch}
    </div>
  );
}
