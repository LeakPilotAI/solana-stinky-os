"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { shortAddr } from "@/lib/api/client";

export default function CreatorPage() {
  const params = useParams();
  const address = String(params.address || "");

  return (
    <div className="space-y-3 p-4">
      <Link href="/entities" className="text-[11px] text-terminal-muted hover:text-terminal-text">
        ← Entities
      </Link>
      <section className="panel p-4">
        <h1 className="font-mono text-sm">{shortAddr(address, 8)}</h1>
        <p className="mt-1 break-all font-mono text-[11px] text-terminal-dim">{address}</p>
      </section>
      <section className="panel p-4">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-terminal-muted">
          Creator intelligence
        </h2>
        <dl className="mt-3 grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
          <Item label="Launches as-of" value="UNKNOWN" />
          <Item label="Runners / fades" value="UNKNOWN" />
          <Item label="Success rate" value="UNKNOWN" />
          <Item label="Reputation" value="UNKNOWN" />
        </dl>
        <p className="mt-3 text-[11px] text-terminal-muted">
          Deployer history hydrates from stored creator_observations. UNKNOWN is not a risk call.
          Need 3 or more prior launches as-of to leave OBSERVED.
        </p>
      </section>
    </div>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-terminal-muted">{label}</dt>
      <dd className="mt-0.5 text-terminal-dim">{value}</dd>
    </div>
  );
}
