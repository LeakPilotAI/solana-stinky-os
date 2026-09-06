from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ENTITY_PAGE = ROOT / "apps" / "web" / "src" / "app" / "entities" / "[id]" / "page.tsx"
OPERATOR_PAGE = ROOT / "apps" / "web" / "src" / "app" / "operator" / "page.tsx"


def test_entity_case_file_renders_persisted_motif_outcome_before_after_timeline():
    source = ENTITY_PAGE.read_text(encoding="utf-8")
    assert 'id="motif-outcome-timeline"' in source
    assert "outcomes?.audit?.records" in source
    assert "outcomes?.audit?.changes" in source
    assert "Before snapshot" in source
    assert "After snapshot" in source
    assert "Affected historical launches" in source
    assert "analogue_history_is_not_prediction true" in source
    assert "predictive_authority false" in source
    assert "trade_signal false" in source


def test_timeline_uses_existing_entity_correlation_read_and_operator_already_drills_to_entity():
    entity_source = ENTITY_PAGE.read_text(encoding="utf-8")
    operator_source = OPERATOR_PAGE.read_text(encoding="utf-8")
    assert entity_source.count("/api/stinky/v1/entity-graph/developer-correlation/${id}?limit=100") == 1
    assert "developer-motif-outcome-timeline" not in entity_source
    assert "Historical motif outcome changes" in operator_source
    assert "href={`/entities/${r.entity_id}`}" in operator_source
