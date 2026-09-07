from datetime import datetime, timezone

from stinky_api.command_center_readiness import summarize_readiness_records


def _readiness(ready: bool, blocker: str | None = None):
    return {
        "status": "READY_FOR_DESCRIPTIVE_CALIBRATION" if ready else "NOT_READY_FOR_DESCRIPTIVE_CALIBRATION",
        "ready": ready,
        "blockers": [] if ready else [blocker or "DEVELOPER_HISTORY_NOT_STABLE"],
        "components": {
            "developer_history": {
                "status": "STABLE_FOR_DESCRIPTIVE_CALIBRATION" if ready else "NOT_STABLE_FOR_DESCRIPTIVE_CALIBRATION",
                "passed": ready,
                "blockers": [] if ready else ["OUTCOME_REGIME_DRIFT"],
            },
            "relationship_history": {"status": "STABLE_FOR_DESCRIPTIVE_CALIBRATION", "passed": True, "blockers": []},
            "outcome_history": {"status": "OBSERVED", "passed": True, "blockers": []},
        },
    }


def test_operator_summary_explains_latest_state_and_regression_without_authority():
    rows = [
        {
            "id": 1,
            "entity_id": "11111111-1111-1111-1111-111111111111",
            "primary_wallet": "DevWallet",
            "display_label": "Developer entity",
            "readiness": _readiness(False),
            "observed_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
        },
        {
            "id": 2,
            "entity_id": "11111111-1111-1111-1111-111111111111",
            "primary_wallet": "DevWallet",
            "display_label": "Developer entity",
            "readiness": _readiness(True),
            "observed_at": datetime(2026, 9, 2, tzinfo=timezone.utc),
        },
        {
            "id": 3,
            "entity_id": "11111111-1111-1111-1111-111111111111",
            "primary_wallet": "DevWallet",
            "display_label": "Developer entity",
            "readiness": _readiness(False, "RELATIONSHIP_HISTORY_NOT_STABLE"),
            "observed_at": datetime(2026, 9, 3, tzinfo=timezone.utc),
        },
    ]
    item = summarize_readiness_records(rows)[0]
    assert item["status"] == "NOT_READY_FOR_DESCRIPTIVE_CALIBRATION"
    assert item["blockers"] == ["RELATIONSHIP_HISTORY_NOT_STABLE"]
    assert item["latest_transition"] == "REGRESSED_FROM_DESCRIPTIVE_CALIBRATION_READINESS"
    assert item["regression_count"] == 1
    assert item["snapshot_count"] == 3
    assert item["components"]["developer_history"]["passed"] is False
    assert item["predictive_authority"] is False
    assert item["risk_inferred"] is False
    assert item["quality_inferred"] is False
    assert item["trade_signal"] is False


def test_operator_summary_keeps_entities_separate_and_orders_latest_first():
    rows = [
        {"id": 1, "entity_id": "11111111-1111-1111-1111-111111111111", "readiness": _readiness(True), "observed_at": datetime(2026, 9, 1, tzinfo=timezone.utc)},
        {"id": 2, "entity_id": "22222222-2222-2222-2222-222222222222", "readiness": _readiness(False), "observed_at": datetime(2026, 9, 4, tzinfo=timezone.utc)},
    ]
    items = summarize_readiness_records(rows, limit=8)
    assert [x["entity_id"] for x in items] == [
        "22222222-2222-2222-2222-222222222222",
        "11111111-1111-1111-1111-111111111111",
    ]
    assert items[0]["latest_transition"] == "INITIAL_STATE"
    assert items[0]["regression_count"] == 0


def test_operator_summary_never_converts_blockers_to_score_or_signal():
    item = summarize_readiness_records([
        {"id": 1, "entity_id": "33333333-3333-3333-3333-333333333333", "readiness": _readiness(False, "INSUFFICIENT_OUTCOME_COVERAGE"), "observed_at": datetime(2026, 9, 5, tzinfo=timezone.utc)}
    ])[0]
    assert "score" not in item
    assert "confidence" not in item
    assert item["interpretation"] == "DESCRIPTIVE_READINESS_EXPLAINABILITY_ONLY"
    assert item["trade_signal"] is False
