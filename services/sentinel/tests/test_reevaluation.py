from sentinel.reevaluation import (
    EvidenceSignature,
    ReevaluatingVolumeMonitor,
    normalize_wallet_performance_row,
)


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
    assert "_reevaluate_with_complete_wallet_history" in source


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


def test_measured_early_success_fields_map_to_core_vocabulary():
    row = normalize_wallet_performance_row(
        {
            "wallet": "wallet-a",
            "early_buy_count": 7,
            "tokens_purchased": 9,
            "hit_rate": None,
            "early_success_rate": 0.625,
            "early_success_sample": 8,
            "early_on_runner": 5,
        }
    )
    assert row["sample_resolved"] == 8
    assert row["sample_size"] == 8
    assert row["hit_rate"] == 0.625
    assert row["runners"] == 5


def test_native_core_wallet_fields_are_never_overwritten():
    row = normalize_wallet_performance_row(
        {
            "wallet": "wallet-a",
            "sample_resolved": 12,
            "sample_size": 12,
            "hit_rate": 0.8,
            "runners": 9,
            "early_success_rate": 0.2,
            "early_success_sample": 4,
            "early_on_runner": 1,
        }
    )
    assert row["sample_resolved"] == 12
    assert row["sample_size"] == 12
    assert row["hit_rate"] == 0.8
    assert row["runners"] == 9


def test_reevaluation_still_uses_normal_admission_gate_before_alert_emitter():
    source = __import__("inspect").getsource(
        ReevaluatingVolumeMonitor._reevaluate_with_complete_wallet_history
    )
    gate_pos = source.index("can_alert_investigation")
    persist_pos = source.index("_persist_inspection")
    emit_pos = source.index("_emit_alert")
    assert gate_pos < persist_pos < emit_pos
    assert "if not alert_ok" in source
    assert "return False" in source


def test_reevaluation_loads_persisted_labeled_outcome_fields():
    source = __import__("inspect").getsource(
        ReevaluatingVolumeMonitor._load_reevaluation_wallet_history
    )
    assert "early_success_rate" in source
    assert "early_success_sample" in source
    assert "early_on_runner" in source
    assert "wallet_performance" in source
