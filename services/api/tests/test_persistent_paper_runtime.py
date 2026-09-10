from pathlib import Path

from stinky_api.paper_runtime_worker import canonical_sha256, process_frozen_bundle
from stinky_api.shadow_paper_decision import build_shadow_paper_decision
from stinky_api.shadow_paper_runtime_adapter import adapt_shadow_decision_for_paper

ROOT = Path(__file__).resolve().parents[3]

def distribution():
    return {"status":"CALIBRATED_EMPIRICAL","pattern_hash":"p1","outcome_distribution":{"probabilities":{"RUNNER":.6,"HELD":.2,"FADE":.2}},"market_cap_change_distributions":{"1h":{"status":"CALIBRATED_EMPIRICAL","probabilities":{"DOWN_GT_50":.1,"DOWN_0_TO_50":.2,"UP_0_TO_100":.4,"UP_GTE_100":.3}}},"calibrated_horizons":["1h"],"live_execution":False,"trading_authority":False,"trade_signal":False}
def context():
    return {"mint":"mint-1","decided_at":"2026-09-10T06:00:00Z","evidence_snapshot":{"frozen":True},"temporal_cutoff_enforced":True,"future_evidence_used":False}
def policy():
    return {"policy_version":"shadow-v1","horizon":"1h","min_runner_probability":.5,"max_fade_probability":.3,"min_nonnegative_market_cap_probability":.6}
def bundle():
    return {"probability_distribution":distribution(),"decision_context":context(),"paper_policy":policy(),"execution_assumptions":{"entry_slippage_bps":100,"exit_slippage_bps":150,"entry_fee_bps":50,"exit_fee_bps":50,"latency_ms":750},"reference_entry_price":1.0,"reference_exit_price":1.5,"paper_notional_usd":20.0}

def test_actual_shadow_output_adapts_into_actual_paper_simulator():
    shadow=build_shadow_paper_decision(distribution(),context(),policy())
    adapted=adapt_shadow_decision_for_paper(shadow)
    assert shadow["status"]=="SHADOW_DECISION" and adapted["status"]=="OBSERVED"
    assert adapted["shadow_action"]=="WOULD_ENTER"
    assert adapted["t0_snapshot"]["future_evidence_used"] is False
    assert adapted["live_execution"] is False and adapted["order_submitted"] is False

def test_full_frozen_bundle_produces_closed_paper_record_without_authority():
    result=process_frozen_bundle(bundle())
    assert result["status"]=="OBSERVED"
    assert result["shadow"]["action"]=="WOULD_ENTER"
    assert result["paper"]["status"]=="SIMULATED_CLOSED"
    for key in ("live_execution","trading_authority","trade_signal","rpc_contacted","transaction_signed","order_submitted","wallet_mutated"):
        assert result[key] is False

def test_unknown_is_preserved_instead_of_inventing_probability():
    bad=bundle(); bad["probability_distribution"]["status"]="UNKNOWN"
    result=process_frozen_bundle(bad)
    assert result["status"]=="UNKNOWN"
    assert result["paper"]["status"]=="NOT_SIMULATED"

def test_would_skip_is_persistable_but_never_simulated_as_entry():
    bad=bundle(); bad["paper_policy"]["min_runner_probability"]=.9
    result=process_frozen_bundle(bad)
    assert result["shadow"]["action"]=="WOULD_SKIP"
    assert result["paper"]["status"]=="NOT_SIMULATED"

def test_canonical_hash_is_order_independent_and_content_sensitive():
    assert canonical_sha256({"a":1,"b":2})==canonical_sha256({"b":2,"a":1})
    assert canonical_sha256({"a":1})!=canonical_sha256({"a":2})

def test_migration_is_immutable_and_launcher_wires_worker_after_main_start():
    migration=(ROOT/"services/api/migrations/005_paper_runtime.sql").read_text()
    launcher=(ROOT/"Start-Stinky-OS.cmd").read_text()
    starter=(ROOT/"scripts/start_paper_runtime.py").read_text()
    assert "paper_runtime_intake" in migration and "paper_runtime_record" in migration
    assert "paper_runtime_record is immutable" in migration
    assert launcher.index("start_genesis.py") < launcher.index("start_paper_runtime.py")
    assert "stinky_api.paper_runtime_worker" in starter
    forbidden=("solana.rpc","send_transaction","sign_transaction","private_key")
    corpus=(migration+starter+(ROOT/"services/api/src/stinky_api/paper_runtime_worker.py").read_text()).lower()
    assert not any(token in corpus for token in forbidden)
