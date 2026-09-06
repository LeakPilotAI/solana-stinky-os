export type DeveloperHistoryState = "KNOWN_HISTORY" | "NEW-UNKNOWN" | "UNKNOWN" | string;

export type DeveloperLongitudinalEvidence = {
  status?: string;
  history_state?: DeveloperHistoryState;
  reference_mint?: string | null;
  reference_mint_inferred_from_latest_visible_launch?: boolean;
  current_mint_excluded_from_history?: boolean;
  fresh_entity_interpretation?: "NEW-UNKNOWN" | string | null;
  launch_history?: {
    historical_launch_count?: number;
    outcome_counts?: Record<string, number>;
    known_outcome_count?: number;
    unknown_outcome_count?: number;
  };
  associated_wallets?: {
    count?: number;
    ownership_inferred?: boolean;
  };
  funding_relationships?: {
    observation_count?: number;
    ownership_inferred?: boolean;
    intent_inferred?: boolean;
  };
  recurring_early_buyers?: {
    status?: string;
    count?: number;
    coordination_inferred?: boolean;
    ownership_inferred?: boolean;
  };
  interpretation?: "DESCRIPTIVE_EVIDENCE_ONLY" | string;
  risk_inferred?: boolean;
  quality_inferred?: boolean;
  predictive_authority?: boolean;
  trade_signal?: boolean;
  evidence_only?: boolean;
};
