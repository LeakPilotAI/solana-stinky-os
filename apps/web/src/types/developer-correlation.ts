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

export type DeveloperCorrelationRepetitionRecord = {
  kind?: string;
  identity?: Record<string, string | null | undefined>;
  independent_observation_count?: number | null;
  distinct_launch_count?: number | null;
  distinct_related_entity_count?: number | null;
  first_observed_at?: string | null;
  last_observed_at?: string | null;
  temporal_spread_seconds?: number | null;
  repetition_state?: "SINGLE_OBSERVATION" | "REPEATED_OBSERVATION" | "MULTI_LAUNCH_REPETITION" | "UNKNOWN" | string;
};

export type DeveloperCorrelationRepetition = {
  status?: string;
  relationship_count_observed?: number;
  repeated_relationship_count?: number;
  multi_launch_relationship_count?: number;
  total_independent_observation_count?: number | null;
  max_temporal_spread_seconds?: number | null;
  records?: DeveloperCorrelationRepetitionRecord[];
  missing?: string[];
  repetition_is_not_strength_score?: true;
  interpretation?: "DESCRIPTIVE_EVIDENCE_ONLY" | string;
  ownership_inferred?: false;
  coordination_inferred?: false;
  risk_inferred?: false;
  quality_inferred?: false;
  predictive_authority?: false;
  trade_signal?: false;
  evidence_only?: true;
};

export type DeveloperCorrelationMotifRecord = {
  motif_kind?: "CROSS_ENTITY_RELATIONSHIP_MOTIF" | "SHARED_FUNDER_CONSTELLATION" | string;
  motif_state?: string;
  funder_wallet?: string | null;
  other_entity_ids?: string[];
  component_kinds?: string[];
  component_count?: number;
  repeated_component_count?: number;
  multi_launch_component_count?: number;
  independent_observation_count?: number | null;
  temporal_spread_seconds?: number | null;
};

export type DeveloperCorrelationMotifs = {
  status?: string;
  motif_count?: number;
  repeated_motif_count?: number;
  multi_launch_motif_count?: number;
  multi_entity_constellation_count?: number;
  records?: DeveloperCorrelationMotifRecord[];
  motif_is_not_ownership_or_coordination?: true;
  motif_is_not_risk_or_quality_inference?: true;
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

export type DeveloperMotifOutcomeLaunch = {
  entity_id?: string;
  mint?: string;
  deployer_wallet?: string | null;
  launch_observed_at?: string | null;
  outcome?: "RUNNER" | "HELD" | "FADE" | "UNKNOWN" | string;
  outcome_observed_at?: string | null;
  ingested_at?: string | null;
};

export type DeveloperMotifOutcomeAnalogue = {
  motif_kind?: string;
  motif_state?: string;
  component_kinds?: string[];
  related_entity_ids?: string[];
  historical_launch_count?: number;
  outcome_counts?: Record<"RUNNER" | "HELD" | "FADE" | "UNKNOWN", number>;
  launches?: DeveloperMotifOutcomeLaunch[];
  analogue_basis?: string;
  analogue_is_not_prediction?: true;
};

export type DeveloperMotifOutcomeChange = {
  status?: string;
  changed?: boolean;
  observed_at?: string | null;
  evidence_hash?: string | null;
  changes?: Array<{
    kind?: string;
    launch?: string;
    before?: unknown;
    after?: unknown;
    fields?: string[];
    added?: string[];
    removed?: string[];
  }>;
};

export type DeveloperMotifOutcomeAudit = {
  status?: string;
  entity_id?: string;
  snapshot_count?: number;
  latest_change?: DeveloperMotifOutcomeChange | null;
  records?: Array<Record<string, unknown>>;
  changes?: DeveloperMotifOutcomeChange[];
  as_of?: string;
  temporal_cutoff_enforced?: boolean;
};

export type DeveloperMotifOutcomeContext = {
  status?: string;
  entity_id?: string;
  motif_analogue_count?: number;
  launch_analogue_count?: number;
  outcome_counts?: Record<"RUNNER" | "HELD" | "FADE" | "UNKNOWN", number>;
  records?: DeveloperMotifOutcomeAnalogue[];
  snapshot_count?: number;
  latest_change?: DeveloperMotifOutcomeChange | null;
  audit?: DeveloperMotifOutcomeAudit;
  analogue_history_is_not_prediction?: true;
  as_of?: string;
  temporal_cutoff_enforced?: boolean;
  predictive_authority?: false;
  trade_signal?: false;
  risk_inferred?: false;
  quality_inferred?: false;
  evidence_only?: true;
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
  repetition_analysis?: DeveloperCorrelationRepetition;
  network_motifs?: DeveloperCorrelationMotifs;
  motif_outcome_context?: DeveloperMotifOutcomeContext;
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
