"use client";

import { useState } from "react";
import { copyText } from "@/lib/api/client";

export function CopyButton({
  value,
  label = "Copy",
  variant = "ghost",
}: {
  value: string;
  label?: string;
  variant?: "ghost" | "solid" | "outline";
}) {
  const [done, setDone] = useState(false);
  const base =
    variant === "solid"
      ? "rounded bg-terminal-elevated px-2 py-0.5 text-2xs font-medium text-terminal-text hover:bg-terminal-panel border border-terminal-border"
      : variant === "outline"
        ? "rounded border border-terminal-border px-2 py-0.5 text-2xs text-terminal-dim hover:border-terminal-accent/50 hover:text-terminal-accent"
        : "rounded border border-terminal-border bg-terminal-elevated px-2 py-0.5 text-2xs text-terminal-dim hover:text-terminal-text";
  return (
    <button
      type="button"
      onClick={async () => {
        const ok = await copyText(value);
        if (ok) {
          setDone(true);
          setTimeout(() => setDone(false), 1200);
        }
      }}
      className={base}
    >
      {done ? "Copied" : label}
    </button>
  );
}
