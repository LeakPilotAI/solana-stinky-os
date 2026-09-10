from sentinel.reevaluation import EvidenceSignature, ReevaluatingVolumeMonitor


def test_signature_requires_existing_admission_evidence():
    assert EvidenceSignature(early_buyers=20, qualifying_wallets=0, creator_launches=0).has_admission_evidence is False
    assert EvidenceSignature(early_buyers=1, qualifying_wallets=1, creator_launches=0).has_admission_evidence is True
    assert EvidenceSignature(early_buyers=0, qualifying_wallets=0, creator_launches=3).has_admission_evidence is True


def test_reevaluation_is_evidence_change_driven_not_timer_driven():
    source = __import__("inspect").getsource(ReevaluatingVolumeMonitor._record_followup_tick)
    assert "previous == current" in source
    assert "current.has_admission_evidence" in source
    assert "sleep(" not in source
    assert "cooldown" not in source.lower()
    assert "_investigate_and_maybe_alert" in source


def test_reevaluation_preserves_original_decision_and_fails_closed():
    source = __import__("inspect").getsource(ReevaluatingVolumeMonitor._record_followup_tick)
    assert '"previous_decision_preserved": True' in source
    assert '"thresholds_changed": False' in source
    assert "except Exception" in source
    assert "_emit_alert" not in source


def test_only_latest_intelligence_insufficient_is_retryable():
    source = __import__("inspect").getsource(ReevaluatingVolumeMonitor._latest_insufficient)
    assert 'row.get("alert_reason") == "INTELLIGENCE_INSUFFICIENT"' in source
    assert 'row.get("alert_ok") is not True' in source
    assert "ORDER BY inspected_at DESC" in source


def test_alert_dedupe_is_per_mint():
    source = __import__("inspect").getsource(ReevaluatingVolumeMonitor._record_followup_tick)
    assert "mint in self._alerted_mints" in source
    assert "self._alerted_mints.add(mint)" in source
