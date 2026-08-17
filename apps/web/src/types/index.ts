export type LiveStatus = "live" | "stale" | "offline" | "reconnecting";

export interface SystemHealth {
  status: string;
  service: string;
  database: boolean;
  event_log: string;
  live: boolean;
}

export interface Counts {
  migrations?: number;
  launches?: number;
  alerts?: number;
  tracks?: number;
  buyers?: number;
  entities?: number;
  wallets_perf?: number;
}

export interface Runner {
  fees_sol?: number | null;
  dex_id?: string | null;
  mint: string;
  pool?: string | null;
  creator?: string | null;
  migration_at?: string | null;
  status?: string;
  buyers_captured?: number;
  trades_observed?: number;
  meaningful_buyers?: number;
  volume_m5_usd?: number | null;
  liquidity_usd?: number | null;
  price_usd?: number | null;
  name?: string | null;
  symbol?: string | null;
  stinky_score?: string | number | null;
  confidence?: string | number | null;
}

export interface Alert {
  event_id?: string;
  occurred_at?: string;
  mint?: string;
  name?: string | null;
  symbol?: string | null;
  creator?: string | null;
  pool?: string | null;
  volume_m5_usd?: number | null;
  liquidity_usd?: number | null;
  stinky_score?: number | null;
  confidence?: number | null;
  meaningful_buyer_count?: number | null;
  early_buyer_count?: number | null;
  smart_wallet_count?: number | null;
  score_model?: string | null;
  score_explanation?: Array<{ delta?: number; reason?: string }> | null;
}

export interface Entity {
  entity_id: string;
  entity_type?: string;
  display_label?: string | null;
  primary_wallet?: string | null;
  wallet_count?: number;
  launch_count?: number;
  early_buy_count?: number;
  confidence?: number;
  updated_at?: string;
}

export interface SmartWallet {
  wallet: string;
  early_buy_count?: number;
  total_buys?: number;
  total_sells?: number;
  total_trades?: number;
  hit_rate?: number | null;
  avg_return_pct?: number | null;
  median_return_pct?: number | null;
  max_return_pct?: number | null;
  tokens_purchased?: number;
  realized_pnl_sol?: number | null;
  realized_pnl_usd?: number | null;
  updated_at?: string;
  watch_score?: number;
  watch_tier?: "high" | "medium" | "emerging" | "thin" | string;
  watch_confidence?: number;
  sample_size?: number;
  why_watch?: string[];
}

export interface Opportunity {
  mint?: string;
  name?: string | null;
  symbol?: string | null;
  score?: number;
  confidence?: number | null;
  volume_m5_usd?: number | null;
  meaningful_buyer_count?: number | null;
  reason?: string;
  occurred_at?: string;
}

export interface AlertPrecision {
  available: boolean;
  total_unique_mints?: number;
  counts?: Record<string, number>;
  runner_rate?: number | null;
  precision_runner?: number | null;
  gate_passed?: number;
  runners_among_passed?: number;
  source?: string;
  engine?: string;
}

export interface TrendingItem {
  mint: string;
  name?: string | null;
  symbol?: string | null;
  volume_m5_usd?: number | null;
  liquidity_usd?: number | null;
  price_usd?: number | null;
  market_cap_usd?: number | null;
  fees_sol?: number | null;
  dex_id?: string | null;
  pair_address?: string | null;
  captured_at?: string | null;
  migration_at?: string | null;
  creator?: string | null;
  buyers_captured?: number | null;
}

export interface TrendingResponse {
  available: boolean;
  min_volume_m5_usd?: number;
  min_fees_sol?: number;
  engine?: string;
  message?: string;
  items: TrendingItem[];
  count: number;
}

export interface CommandCenterData {

  pipeline?: {
    available?: boolean;
    tables?: Record<string, number | null>;
    maintain_last_utc?: string | null;
  };
  alert_precision?: AlertPrecision;

  status: string;
  counts: Counts;
  runners: Runner[];
  alerts: Alert[];
  entities: Entity[];
  smart_wallets: SmartWallet[];
  launches: Array<Record<string, unknown>>;
  opportunity_queue: Opportunity[];
  trending?: TrendingResponse;
  patterns: {
    available: boolean;
    message: string;
    items: unknown[];
  };
}

export interface SearchResult {
  tokens: Array<{ mint?: string; name?: string; symbol?: string }>;
  wallets: Array<{ wallet?: string; early_buy_count?: number; hit_rate?: number }>;
  entities: Array<{
    entity_id?: string;
    primary_wallet?: string;
    launch_count?: number;
  }>;
  alerts: Array<{ mint?: string; name?: string; stinky_score?: number }>;
}

export interface WalletDetail {
  available: boolean;
  wallet?: string;
  message?: string;
  performance?: SmartWallet;
  entity?: {
    entity_id?: string;
    entity_type?: string;
    primary_wallet?: string;
    launch_count?: number;
    wallet_count?: number;
    confidence?: number;
    role?: string;
    link_reason?: string;
  } | null;
  early_entries?: Array<{
    mint?: string;
    rank?: number;
    sol_spent?: number;
    bought_at?: string;
    is_meaningful?: boolean;
    creator?: string;
    migration_at?: string;
    status?: string;
  }>;
  recent_trades?: Array<{
    mint?: string;
    side?: string;
    traded_at?: string;
    sol_amount?: number;
    is_early_buyer?: boolean;
    early_rank?: number;
  }>;
  why_watch?: string[];
  watch_score?: number;
  watch_tier?: string;
  watch_confidence?: number;
}

export interface EntityDetail {
  available: boolean;
  entity_id?: string;
  message?: string;
  entity?: Entity & { meta?: unknown };
  wallets?: Array<{
    wallet?: string;
    role?: string;
    link_reason?: string;
    confidence?: number;
  }>;
  launches?: Array<{
    mint?: string;
    name?: string;
    symbol?: string;
    occurred_at?: string;
    stinky_score?: number;
  }>;
}


export interface PatternItem {
  id: string;
  kind: string;
  title: string;
  summary: string;
  confidence?: number;
  evidence?: Record<string, unknown>;
  links?: {
    wallet?: string;
    wallet_b?: string;
    mint?: string;
    entity_id?: string;
  };
}

export interface PatternsResponse {
  available: boolean;
  engine?: string;
  message?: string;
  counts_by_kind?: Record<string, number>;
  items: PatternItem[];
  total: number;
}


export interface GraphNode {
  id: string;
  type?: string;
  label?: string;
  degree?: number;
  early_mints?: number;
  early_buy_count?: number;
  hit_rate?: number | null;
  total_sells?: number;
  entity_id?: string;
  launch_count?: number;
  display_label?: string;
}

export interface GraphEdge {
  id: string;
  type: string;
  source: string;
  target: string;
  weight: number;
  label?: string;
  meta?: Record<string, unknown>;
}

export interface GraphData {
  available: boolean;
  engine?: string;
  message?: string;
  stats?: {
    nodes?: number;
    edges?: number;
    co_buy_edges?: number;
    entity_edges?: number;
    min_shared?: number;
  };
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphEgo {
  available: boolean;
  wallet?: string;
  message?: string;
  neighbor_count?: number;
  neighbors?: Array<{ neighbor?: string; shared_mints?: number }>;
  early_entries?: Array<{
    mint?: string;
    rank?: number;
    sol_spent?: number;
    bought_at?: string;
  }>;
}


export interface TimeMachineSeriesPoint {
  day: string;
  launches?: number;
  early_buys?: number;
  buys?: number;
  sells?: number;
  cum_launches?: number;
  cum_early_buys?: number;
  cum_buys?: number;
  cum_sells?: number;
  activity?: number;
}

export interface TimeMachineEvent {
  at?: string;
  kind?: string;
  mint?: string;
  name?: string;
  symbol?: string;
  rank?: number;
  sol_spent?: number;
  sol_amount?: number;
  is_early_buyer?: boolean;
  wallet?: string;
}

export interface TimeMachineResponse {
  available: boolean;
  engine?: string;
  message?: string;
  wallet?: string;
  entity_id?: string;
  entity?: Record<string, unknown> & {
    entity_id?: string;
    display_label?: string;
    launch_count?: number;
    confidence?: number;
    primary_wallet?: string;
  };
  wallets?: string[];
  summary?: {
    event_count?: number;
    days_active?: number;
    launches?: number;
    early_buys?: number;
    buys?: number;
    sells?: number;
    first_at?: string;
    last_at?: string;
  };
  series?: TimeMachineSeriesPoint[];
  events?: TimeMachineEvent[];
}


export interface ResearchItem {
  type: string;
  title: string;
  summary?: string;
  wallet?: string;
  wallet_b?: string;
  mint?: string;
  entity_id?: string;
  metrics?: Record<string, unknown>;
}

export interface ResearchResponse {
  available: boolean;
  engine?: string;
  kind?: string;
  query?: string;
  preset?: string | null;
  explanation?: string;
  count?: number;
  items?: ResearchItem[];
  presets?: Array<{ id: string; label: string }>;
}


export interface OutcomesResponse {
  available: boolean;
  engine?: string;
  counts?: Record<string, number>;
  total_alerts?: number;
  runner_rate?: number | null;
  items?: Array<Record<string, unknown>>;
  message?: string;
}
