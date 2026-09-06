from pathlib import Path


def test_motif_outcome_audit_has_no_score_probability_or_trade_semantics():
    text = Path("services/api/src/stinky_api/developer_motif_outcome_audit.py").read_text().lower()
    for forbidden in ("risk_score", "quality_score", "probability", "confidence_score", "bullish", "bearish", "buy_signal", "sell_signal"):
        assert forbidden not in text
    assert '"predictive_authority": false' in text
    assert '"trade_signal": false' in text
    assert '"analogue_history_is_not_prediction": true' in text
