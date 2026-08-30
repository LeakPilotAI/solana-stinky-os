import type {
  CommandCenterData,
  SearchResult,
  SystemHealth,
  Runner,
  Alert,
  Entity,
  SmartWallet,
  WalletDetail,
  EntityDetail,
  PatternsResponse,
  GraphData,
  GraphEgo,
  TimeMachineResponse,
  ResearchResponse,
  OutcomesResponse,
} from "@/types";

const BASE = "/api/stinky";

async function getJson<T>(
  path: string,
  init?: RequestInit & { timeoutMs?: number }
): Promise<T> {
  const timeoutMs = init?.timeoutMs ?? 12_000;
  const { timeoutMs: _t, ...rest } = init || {};
  const res = await fetch(`${BASE}${path}`, {
    ...rest,
    headers: {
      Accept: "application/json",
      ...(rest.headers || {}),
    },
    cache: "no-store",
    signal: rest.signal ?? AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) {
    throw new Error(`API ${path} ? ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => getJson<SystemHealth>("/health", { timeoutMs: 4_000 }),
  commandCenter: () =>
    getJson<CommandCenterData>("/v1/command-center", { timeoutMs: 20_000 }),
  runners: (limit = 50, minFeesSol = 0, minVolumeM5 = 150000) =>
    getJson<{ items: Runner[]; count: number }>(
      `/v1/runners?limit=${limit}&min_fees_sol=${minFeesSol}&min_volume_m5_usd=${minVolumeM5}&pump_only=true`,
      { timeoutMs: 20_000 }
    ),
  alerts: (limit = 50) =>
    getJson<{ items: Alert[]; count: number }>(`/v1/alerts?limit=${limit}`, {
      timeoutMs: 8_000,
    }),
  entities: (limit = 50) =>
    getJson<{ items: Entity[]; count: number }>(`/v1/entities?limit=${limit}`, {
      timeoutMs: 8_000,
    }),
  smartWallets: (limit = 50) =>
    getJson<{ items: SmartWallet[]; count: number }>(
      `/v1/wallets/smart?limit=${limit}`,
      { timeoutMs: 8_000 }
    ),
  walletsSuccess: (limit = 50) =>
    getJson<{
      available?: boolean;
      engine?: string;
      message?: string;
      items: Array<{
        wallet: string;
        early_entries?: number;
        early_on_mega?: number;
        early_on_runner?: number;
        early_on_mid?: number;
        early_on_fade?: number;
        success_rate?: number | null;
        sample_size?: number;
        last_success_at?: string | null;
        updated_at?: string | null;
      }>;
      count: number;
    }>(`/v1/wallets/success?limit=${limit}`, { timeoutMs: 8_000 }),
  wallet: (address: string) =>
    getJson<WalletDetail>(`/v1/wallets/${encodeURIComponent(address)}`, {
      timeoutMs: 10_000,
    }),
  entity: (id: string) =>
    getJson<EntityDetail>(`/v1/entities/${encodeURIComponent(id)}`, {
      timeoutMs: 10_000,
    }),
  search: (q: string) =>
    getJson<SearchResult>(`/v1/search?q=${encodeURIComponent(q)}`, {
      timeoutMs: 6_000,
    }),
  token: (mint: string) =>
    getJson<Record<string, unknown>>(`/v1/tokens/${encodeURIComponent(mint)}`, {
      timeoutMs: 10_000,
    }),
  patterns: (limit = 40) =>
    getJson<PatternsResponse>(`/v1/patterns?limit=${limit}`, {
      timeoutMs: 15_000,
    }),
  graph: (minShared = 2, edgeLimit = 80) =>
    getJson<GraphData>(
      `/v1/graph?min_shared=${minShared}&edge_limit=${edgeLimit}`,
      { timeoutMs: 15_000 }
    ),
  graphWallet: (address: string, minShared = 1) =>
    getJson<GraphEgo>(
      `/v1/graph/wallet/${encodeURIComponent(address)}?min_shared=${minShared}`,
      { timeoutMs: 12_000 }
    ),
  timeMachineWallet: (address: string) =>
    getJson<TimeMachineResponse>(
      `/v1/time-machine/wallet/${encodeURIComponent(address)}`,
      { timeoutMs: 12_000 }
    ),
  scoresBackfill: () =>
    fetch(`${BASE}/v1/scores/backfill`, {
      method: "POST",
      signal: AbortSignal.timeout(60_000),
    }).then((r) => r.json()),
  scoreSeries: (subjectType: string, subjectId: string) =>
    getJson<{ items: Array<Record<string, unknown>>; count: number }>(
      `/v1/scores/${encodeURIComponent(subjectType)}/${encodeURIComponent(subjectId)}`,
      { timeoutMs: 8_000 }
    ),
  timeMachineEntity: (entityId: string) =>
    getJson<TimeMachineResponse>(
      `/v1/time-machine/entity/${encodeURIComponent(entityId)}`,
      { timeoutMs: 12_000 }
    ),
  outcomes: (limit = 50, recompute = false) =>
    getJson<OutcomesResponse>(
      `/v1/outcomes?limit=${limit}&recompute=${recompute ? "true" : "false"}`,
      { timeoutMs: 15_000 }
    ),
  replayFunnel: () =>
    getJson<Record<string, unknown>>(`/v1/replay/funnel`, { timeoutMs: 10_000 }),
  replayBacktest: (minScore = 55, limit = 200) =>
    getJson<Record<string, unknown>>(
      `/v1/replay/backtest?min_score=${minScore}&limit=${limit}`,
      { timeoutMs: 20_000 }
    ),
  research: (q = "", preset?: string, limit = 25) => {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (preset) params.set("preset", preset);
    params.set("limit", String(limit));
    return getJson<ResearchResponse>(`/v1/research?${params.toString()}`, {
      timeoutMs: 12_000,
    });
  },
  bookHealth: (body: Record<string, unknown> = {}) =>
    postJson<Record<string, unknown>>("/v1/book/health", body),
  bookDesk: (body: Record<string, unknown> = {}) =>
    postJson<Record<string, unknown>>("/v1/book/desk", body),
  bookObservations: (body: Record<string, unknown> = {}) =>
    postJson<{ observations: Array<Record<string, unknown>>; count: number; source?: string }>(
      "/v1/book/observations",
      body
    ),
  bookWhatHappened: (mint: string, extra: Record<string, unknown> = {}) =>
    postJson<Record<string, unknown>>("/v1/book/what-happened", { mint, ...extra }),
  bookRecipe: (body: Record<string, unknown>) =>
    postJson<Record<string, unknown>>("/v1/book/recipe", body),
  bookInsights: (body: Record<string, unknown> = {}) =>
    postJson<Record<string, unknown>>("/v1/book/insights", body),
  bookQuality: (body: Record<string, unknown> = {}) =>
    postJson<{ states: Array<Record<string, unknown>>; count: number; source?: string }>("/v1/book/quality", body),
  bookDips: (body: Record<string, unknown> = {}) =>
    postJson<{ dips: Array<Record<string, unknown>>; count: number; empty_note?: string | null; source?: string }>(
      "/v1/book/dips",
      body
    ),
};

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body ?? {}),
    cache: "no-store",
    signal: AbortSignal.timeout(20_000),
  });
  if (!res.ok) {
    throw new Error(`API ${path} → ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function shortAddr(addr?: string | null, n = 4): string {
  if (!addr) return "?";
  if (addr.length <= n * 2 + 1) return addr;
  return `${addr.slice(0, n)}?${addr.slice(-n)}`;
}

export function fmtUsd(v?: number | null): string {
  if (v == null || Number.isNaN(Number(v))) return "?";
  const n = Number(v);
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${n.toFixed(0)}`;
}

export function fmtPct(v?: number | null): string {
  if (v == null || Number.isNaN(Number(v))) return "?";
  const n = Number(v);
  const p = n <= 1 ? n * 100 : n;
  return `${p.toFixed(0)}%`;
}

export function ageFrom(iso?: string | null): string {
  if (!iso) return "?";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "?";
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function tierClass(tier?: string): string {
  switch (tier) {
    case "high":
      return "text-terminal-accent";
    case "medium":
      return "text-terminal-info";
    case "emerging":
      return "text-terminal-warn";
    default:
      return "text-terminal-muted";
  }
}
