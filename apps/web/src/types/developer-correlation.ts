export type DeveloperCorrelationRecord = {
  relationship?: string;
  other_entity_id?: string | null;
  wallet?: string | null;
  funder_wallet?: string | null;
  observation_count?: number | null;
  ownership_inferred?: false;
  coordination_inferred?: false;
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
