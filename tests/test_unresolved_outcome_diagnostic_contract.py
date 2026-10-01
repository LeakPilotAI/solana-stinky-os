from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_unresolved_diagnostic_reuses_canonical_classifier_and_is_read_only():
 t=(ROOT/"scripts"/"diagnose_unresolved_prospective_outcomes.py").read_text()
 assert "classify_completed_market_path" in t
 assert "entity_launch_outcome_labels" in t
 assert "migration_tracks" in t
 assert "market_snapshots" in t
 assert "post_migration.tracking_completed" in t
 for x in ['"read_only":True','"candidate_mutated":False','"automatic_activation":False','"classification_reused":True']:
  assert x in t
 low=t.lower()
 for forbidden in ("update paper_prospective_candidate","insert into paper_prospective_candidate","record_outcome(","provision_paper_policy","send_transaction","private_key"):
  assert forbidden not in low
def test_unresolved_diagnostic_has_explicit_evidence_states():
 t=(ROOT/"scripts"/"diagnose_unresolved_prospective_outcomes.py").read_text()
 for x in ("canonical_ledger_label_available","entity_launch_label_available","canonical_classification_possible_but_not_reconciled","missing_migration_track","migration_track_not_completed","canonical_evidence_insufficient"):
  assert x in t
def test_unresolved_diagnostic_launcher_starts_only_postgres():
 t=(ROOT/"Run-Unresolved-Outcome-Diagnostic.cmd").read_text()
 assert "docker compose -p project-genesis up -d postgres" in t
 assert "diagnose_unresolved_prospective_outcomes.py" in t
 assert "Start-Stinky-OS" not in t
