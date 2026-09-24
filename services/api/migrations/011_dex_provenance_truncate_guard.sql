-- Preserve append-only provenance history against table-wide removal.
-- Additive upgrade: existing rows and UPDATE/DELETE guards remain unchanged.
DROP TRIGGER IF EXISTS dex_provenance_evidence_no_truncate ON dex_provenance_evidence_snapshots;
CREATE TRIGGER dex_provenance_evidence_no_truncate
BEFORE TRUNCATE ON dex_provenance_evidence_snapshots
FOR EACH STATEMENT EXECUTE FUNCTION reject_dex_provenance_evidence_mutation();
