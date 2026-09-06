export type DeveloperCorrelationRecord = {
  relationship?: string;
  other_entity_id?: string | null;
  buyer_entity_id?: string | null;
  wallet?: string | null;
  funder_wallet?: string | null;
  observation_count?: number | null;
  ownership_inferred?: false;
  coordination_inferred?: false;
};

export type DeveloperCorrelationChange = {
  status?: string;
  changed?: boolean;
  observed_at?: string | null;
  evidence_hash?: string | null;
  changes?: Array<{ kind?: string; field?: string; fields?: string[]; added?: string[]; removed?: string[] }>;
};

export type DeveloperCorrelationAudit = {
  status?: string;
  entity_id?: string;
  snapshot_count?: number;
  latest_change?: DeveloperCorrelationChange | null;
  records?: Array<Record<string, unknown>>;
  changes?: DeveloperCorrelationChange[];
  as_of?: string;
  temporal_cutoff_enforced?: boolean;
};

export type DeveloperIdentityCorrelation = {
  status?: "OBSERVED" | "NEW-UNKNOWN" | "UNKNOWN" | string;
  entity_id?: string;
  wallets?: string[];
  shared_funders?: DeveloperCorrelationRecord[];
  cross_entity_wallet_reuse?: DeveloperCorrelationRecord[];
  deployer_buyer_recurrence?: DeveloperCorrelationRecord[];
  shared_relationship_structures?: DeveloperCorrelationRecord[];
  missing?: string[];
  snapshot_count?: number;
  latest_change?: DeveloperCorrelationChange | null;
  audit?: DeveloperCorrelationAudit;
  as_of?: string;
  temporal_cutoff_enforced?: boolean;
  interpretation?: "DESCRIPTIVE_EVIDENCE_ONLY" | string;
  ownership_inferred?: false;
  coordination_inferred?: false;
  intent_inferred?: false;
  risk_inferred?: false;
  quality_inferred?: false;
  predictive_authority?: false;
  trade_signal?: false;
  evidence_only?: true;
};
