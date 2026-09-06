from pathlib import Path


def test_correlation_attaches_motif_outcome_audit_and_persists_current_views_only():
    text = Path("services/api/src/stinky_api/developer_identity_correlation.py").read_text()
    assert "persist_motif_outcome_snapshot" in text
    assert "motif_outcome_audit_history" in text
    assert "if cutoff is None:" in text
    assert 'context["audit"] = audit' in text
    assert 'context["latest_change"] = audit.get("latest_change")' in text
    assert 'context["snapshot_count"] = audit.get("snapshot_count", 0)' in text


def test_motif_outcome_context_always_carries_entity_id_for_snapshot_addressing():
    text = Path("services/api/src/stinky_api/developer_motif_outcome_context.py").read_text()
    assert 'entity_key = str(entity_id)' in text
    assert '"entity_id": entity_key' in text
