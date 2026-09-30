from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from stinky_api.paper_cohort_report import report_paper_cohort
from stinky_api.paper_runtime_worker import canonical_sha256, process_frozen_bundle
from test_persistent_paper_runtime import bundle, bind_policy


def row(intake_id="close-1", at="2026-09-10T07:00:00Z", sha=None, version="shadow-v1", backed=False):
    payload = bundle()
    payload["paper_policy"]["policy_version"] = version
    payload["policy_identity"] = {"policy_sha256": sha, "provenance": {
        "mode": "EVIDENCE_BACKED_SCORE_CANDIDATE" if backed else "MANUAL_OPERATOR_SUPPLIED", "evidence_backed": backed}}
    payload["paper_close_evidence"] = {"snapshot_id": intake_id, "captured_at": at,
        "source": "fixture", "strictly_later_than_t0": True, "t0_bundle_recomputed": False}
    if backed:
        provenance = payload["policy_identity"]["provenance"]
        provenance.update(candidate_version="score-paper-candidate-v1:" + "a" * 16,
            candidate_evidence_sha256="a" * 64, candidate_cutoff="2026-09-01T00:00:00Z",
            comparison_as_of="2026-09-02T00:00:00Z", readiness_criteria={"min_later_sample": 1},
            readiness_checks={"sufficient_later_sample": True})
        provenance["provenance_sha256"] = canonical_sha256(provenance)
    bind_policy(payload)
    actual_sha = payload["policy_identity"]["policy_sha256"]
    record = process_frozen_bundle(payload)
    if sha is not None:
        payload["policy_identity"]["policy_sha256"] = sha
        record["policy_identity"]["policy_sha256"] = sha
    else:
        sha = actual_sha
    return {"intake_id": intake_id, "mint": "mint-1", "intake_mint": "mint-1",
        "decided_at": payload["decision_context"]["decided_at"], "observed_at": at,
        "created_at": at, "intake_created_at": at, "policy_version": version,
        "policy_sha256": sha, "policy_evidence_backed": backed,
        "paper_status": record["paper"]["status"], "record": record,
        "payload": payload, "payload_sha256": canonical_sha256(payload)}


def session(rows):
    result = Mock()
    result.mappings.return_value.all.return_value = rows
    return Mock(execute=AsyncMock(return_value=result))


def selection(**overrides):
    return {"policy_sha256": bundle()["policy_identity"]["policy_sha256"], "policy_version": "shadow-v1", "evidence_backed": False,
            "as_of": "2026-09-11T00:00:00Z", **overrides}


def criteria(**overrides):
    return {"minimum_closed_trades": 1, "minimum_mean_net_return_pct": -100,
            "maximum_drawdown_pct": 100, "minimum_win_rate": 0, **overrides}


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [{"policy_sha256": None}, {"policy_sha256": "z" * 64},
    {"policy_version": None}, {"evidence_backed": 0}, {"as_of": None},
    {"as_of": "2026-09-11"}, {"record_limit": True}, {"record_limit": 2001}])
async def test_invalid_explicit_selection_never_accesses_database(overrides):
    db = session([row()])
    result = await report_paper_cohort(db, **selection(**overrides))
    assert result["status"] == "UNKNOWN"
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_runtime_to_adapter_to_evaluator_preserves_selected_manual_identity():
    db = session([row()])
    report = await report_paper_cohort(db, **selection(), release_criteria=criteria())
    assert report["status"] == "OBSERVED"
    assert report["walk_forward_evaluated"] is True
    assert report["walk_forward"]["evaluated_policy_identity"] == report["selected_policy_identity"]
    assert report["provenance_classification"] == "MANUAL"
    assert report["selected_policy_identity"]["provenance"]["evidence_backed"] is False
    assert report["counts"]["closed_simulations"] == 1
    assert report["walk_forward"]["evaluated_records"][0]["closed_at"] == "2026-09-10T07:00:00+00:00"
    assert report["automatic_activation"] is report["live_execution"] is report["thresholds_invented"] is False
    sql, params = db.execute.call_args.args
    assert "paper_policy_active" not in str(sql)
    assert "WHERE r.policy_sha256 = :policy_sha256" in str(sql)
    assert "ORDER BY r.created_at ASC, r.intake_id ASC" in str(sql)
    assert params["fetch_limit"] == 501
    assert params["as_of"] == datetime(2026, 9, 11, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_missing_criteria_report_facts_without_evaluation_or_defaults():
    report = await report_paper_cohort(session([row()]), **selection())
    assert report["status"] == "OBSERVED"
    assert report["structurally_eligible"] is True
    assert report["release_criteria_supplied"] is False
    assert report["walk_forward_evaluated"] is False
    assert report["walk_forward"] is report["deficits"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("other", [
    {"sha": "b" * 64}, {"version": "other"}, {"backed": True}])
async def test_mixed_stored_identities_cannot_enter_evaluation(other):
    report = await report_paper_cohort(session([row(), row("second", **other)]), **selection(), release_criteria=criteria())
    assert report["status"] == "UNKNOWN"
    assert report["walk_forward"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["policy_version", "policy_sha256", "policy_evidence_backed"])
async def test_legacy_null_identity_fails_closed(field):
    value = row(); value[field] = None
    report = await report_paper_cohort(session([value]), **selection())
    assert report["status"] == "UNKNOWN"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation,reason", [
    (lambda r: r["record"]["policy_identity"]["provenance"].update(evidence_backed=0), "stored_policy_identity_mismatch"),
    (lambda r: r["record"]["policy_identity"]["provenance"].update(mode="UNKNOWN"), "stored_policy_identity_mismatch"),
    (lambda r: r.update(payload_sha256="b" * 64), "frozen_intake_hash_mismatch"),
    (lambda r: r.update(decided_at=None), "invalid_evidence_chronology"),
    (lambda r: r.update(created_at="2026-09-12T00:00:00Z"), "invalid_evidence_chronology"),
    (lambda r: r["record"].update(transaction_signed=True), "unsafe_runtime_record"),
    (lambda r: r["record"]["paper"].update(order_submitted=True), "invalid_paper_record"),
    (lambda r: r["record"]["paper"].update(policy_identity={}), "simulation_policy_mismatch"),
])
async def test_malformed_evidence_rejected(mutation, reason):
    value = row(); mutation(value)
    report = await report_paper_cohort(session([value]), **selection(), release_criteria=criteria())
    assert report["status"] == "UNKNOWN"
    assert report["reasons"] == [reason]
    assert report["walk_forward"] is None


@pytest.mark.asyncio
async def test_close_time_must_be_stored_matching_and_strictly_after_t0():
    for at in ["2026-09-10T06:00:00Z", "2026-09-10T05:59:00Z"]:
        report = await report_paper_cohort(session([row(at=at)]), **selection())
        assert report["status"] == "UNKNOWN"
    value = row(); value["payload"]["paper_close_evidence"].pop("captured_at")
    value["payload_sha256"] = canonical_sha256(value["payload"])
    report = await report_paper_cohort(session([value]), **selection())
    assert report["reasons"] == ["invalid_stored_close_chronology"]


@pytest.mark.asyncio
async def test_cohort_empty_overflow_and_database_failure_never_look_evaluable():
    for db, args, reason in [
        (session([]), {}, "selected_cohort_not_found_as_of"),
        (session([row(), row("second")]), {"record_limit": 1}, "cohort_exceeds_record_limit"),
        (Mock(execute=AsyncMock(side_effect=RuntimeError("secret connection detail"))), {}, "cohort_evidence_unavailable"),
    ]:
        report = await report_paper_cohort(db, **selection(**args), release_criteria=criteria())
        assert report["status"] == "UNKNOWN"
        assert report["counts"] is None
        assert report["walk_forward"] is None
        assert report["reasons"] == [reason]
        assert "secret" not in str(report)


@pytest.mark.asyncio
async def test_duplicate_record_or_closed_simulation_rejected():
    value = row()
    for duplicate in [deepcopy(value), {**deepcopy(value), "intake_id": "alias"}]:
        report = await report_paper_cohort(session([value, duplicate]), **selection())
        assert report["status"] == "UNKNOWN"
        assert "duplicate" in report["reasons"][0]


@pytest.mark.asyncio
async def test_full_provenance_cannot_mix_even_if_sha_version_and_boolean_match():
    value = row("second")
    value["record"]["policy_identity"]["provenance"]["extra"] = "different"
    report = await report_paper_cohort(session([row(), value]), **selection())
    assert report["reasons"] == ["mixed_policy_provenance"]


@pytest.mark.asyncio
async def test_empty_criteria_is_explicitly_unknown_and_sample_deficit_is_caller_supplied():
    report = await report_paper_cohort(session([row()]), **selection(), release_criteria={})
    assert report["release_criteria_supplied"] is True
    assert report["walk_forward"]["status"] == "UNKNOWN"
    assert not report["walk_forward_evaluated"]
    report = await report_paper_cohort(session([row()]), **selection(), release_criteria=criteria(minimum_closed_trades=3))
    assert report["deficits"] == {"closed_simulations_needed": 2}
    assert report["walk_forward"]["selected_policy_identity"] == report["selected_policy_identity"]


@pytest.mark.asyncio
async def test_report_sorts_by_actual_close_not_persistence_order():
    early, late = row("early"), row("late", at="2026-09-10T09:00:00Z")
    late["mint"] = late["intake_mint"] = late["payload"]["decision_context"]["mint"] = "mint-2"
    late["payload_sha256"] = canonical_sha256(late["payload"])
    late["record"] = process_frozen_bundle(late["payload"])
    report = await report_paper_cohort(session([late, early]), **selection(), release_criteria=criteria())
    assert report["walk_forward_evaluated"]
    assert [r["mint"] for r in report["walk_forward"]["evaluated_records"]] == ["mint-1", "mint-2"]


@pytest.mark.asyncio
async def test_open_and_not_simulated_records_remain_factual_without_counting_as_closed():
    values = []
    for status in ["SIMULATED_OPEN", "NOT_SIMULATED"]:
        value = row(status)
        value["payload"].pop("reference_exit_price")
        value["payload"].pop("paper_close_evidence")
        value["observed_at"] = value["decided_at"]
        if status == "NOT_SIMULATED":
            value["payload"]["probability_distribution"]["status"] = "UNKNOWN"
        value["record"] = process_frozen_bundle(value["payload"])
        value["paper_status"] = value["record"]["paper"]["status"]
        value["payload_sha256"] = canonical_sha256(value["payload"])
        values.append(value)
    report = await report_paper_cohort(session(values), **selection())
    assert report["counts"] == {"total_immutable_records": 2, "open_simulation_records": 1,
                                "closed_simulations": 0, "not_simulated_records": 1}
    assert report["available_for_walk_forward"] == 0
    assert not report["structurally_eligible"]


@pytest.mark.asyncio
async def test_closed_record_must_match_frozen_inputs_and_policy_horizon():
    value = row(); value["record"]["paper"]["notional_usd"] = 10
    report = await report_paper_cohort(session([value]), **selection())
    assert report["reasons"] == ["simulation_frozen_inputs_mismatch"]
    report = await report_paper_cohort(session([row(at="2026-09-10T06:59:00Z")]), **selection())
    assert report["reasons"] == ["invalid_frozen_close_horizon_or_price"]


@pytest.mark.asyncio
async def test_http_route_uses_explicit_body_without_active_policy():
    import httpx
    from stinky_api.main import app
    from stinky_api.db import get_session
    db = session([row()])
    async def dependency():
        yield db
    app.dependency_overrides[get_session] = dependency
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            absent = await client.post("/v1/paper/cohort-report", json={})
            assert absent.json()["status"] == "UNKNOWN"
            db.execute.assert_not_awaited()
            response = await client.post("/v1/paper/cohort-report", json=selection())
            assert response.status_code == 200
            assert response.json()["counts"]["closed_simulations"] == 1
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_later_close_copies_original_t0_despite_active_policy_switch(monkeypatch):
    import json
    from stinky_api.prospective_paper_intake_producer import _enqueue_due_closes
    frozen = bundle(); frozen.pop("reference_exit_price")
    original = deepcopy(frozen)
    monkeypatch.setenv("STINKY_PAPER_POLICY_VERSION", "later-active-policy")
    monkeypatch.setenv("STINKY_PAPER_POLICY_SHA256", "b" * 64)
    candidates = Mock()
    candidates.mappings.return_value.all.return_value = [{
        "candidate_id": "event-1", "mint": "mint-1", "frozen_bundle": frozen,
        "frozen_bundle_sha256": canonical_sha256(frozen),
        "close_due_at": datetime(2026, 9, 10, 7, tzinfo=timezone.utc), "open_intake_id": "open-1",
        "paper_status": "SIMULATED_OPEN"}]
    snapshot = Mock()
    snapshot.mappings.return_value.first.return_value = {"snapshot_id": "snapshot-1",
        "captured_at": datetime(2026, 9, 10, 7, tzinfo=timezone.utc), "price_usd": 2, "source": "fixture"}
    db = Mock(execute=AsyncMock(side_effect=[candidates, snapshot, Mock(), Mock(rowcount=1)]), commit=AsyncMock())
    assert await _enqueue_due_closes(db) == 1
    emitted = json.loads(db.execute.call_args_list[2].args[1]["payload"])
    assert emitted.pop("reference_exit_price") == 2
    assert emitted.pop("paper_close_evidence")["t0_bundle_recomputed"] is False
    assert emitted == original == frozen
    assert "paper_policy_active" not in " ".join(str(c.args[0]) for c in db.execute.call_args_list)
