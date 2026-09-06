export type DeveloperChangeFeedItem = {
  entity_id?: string;
  primary_wallet?: string | null;
  display_label?: string | null;
  reference_mint?: string | null;
  history_state?: string | null;
  observed_at?: string | null;
  change_status?: string;
  change_kinds?: string[];
};

export type DeveloperChangeFeed = {
  status?: string;
  items?: DeveloperChangeFeedItem[];
  count?: number;
  interpretation?: "DESCRIPTIVE_EVIDENCE_ONLY" | string;
  risk_inferred?: boolean;
  quality_inferred?: boolean;
  predictive_authority?: boolean;
  trade_signal?: boolean;
  evidence_only?: boolean;
};
