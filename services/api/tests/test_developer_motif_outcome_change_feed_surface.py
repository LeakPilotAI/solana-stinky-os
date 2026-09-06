from pathlib import Path


def test_entity_graph_exposes_bounded_motif_outcome_change_feed():
    text = Path("services/api/src/stinky_api/entity_graph.py").read_text()
    assert '@router.get("/developer-motif-outcome-changes")' in text
    assert "motif_outcome_change_feed" in text
    assert "limit: int = Query(50, ge=1, le=200)" in text
    assert "include_unchanged: bool = Query(False)" in text


def test_operator_reads_persisted_feed_without_deep_correlation_loop():
    text = Path("apps/web/src/app/operator/page.tsx").read_text()
    assert "/api/stinky/v1/entity-graph/developer-motif-outcome-changes?limit=50" in text
    assert "Historical motif outcome changes" in text
    assert "HISTORICAL" not in text or "outcome" in text.lower()
    assert "developer-correlation/${" not in text
    assert "/command-center" not in text


def test_operator_keeps_descriptive_authority_copy():
    text = Path("apps/web/src/app/operator/page.tsx").read_text().lower()
    assert "outcome resolution is factual history, not prediction or a trade signal" in text
    assert "risk score" not in text
    assert "quality score" not in text
    assert "probability" not in text
