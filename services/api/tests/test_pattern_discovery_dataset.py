from datetime import datetime, timezone

import pytest

from stinky_api.pattern_discovery_dataset import form_pattern_discovery_dataset


class _Mappings:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows


class _Result:
    def __init__(self, rows): self.rows = rows
    def mappings(self): return _Mappings(self.rows)


class _Session:
    def __init__(self, responses): self.responses = list(responses); self.calls = []
    async def execute(self, statement, params):
        self.calls.append((str(statement), dict(params)))
        return _Result(self.responses.pop(0))


@pytest.mark.asyncio
async def test_dataset_separates_feature_cutoff_from_later_immutable_label():
    launch_at = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
    feature_at = datetime(2026, 9, 1, 0, 5, tzinfo=timezone.utc)
    session = _Session([
        [{
            "launch_id": 1, "entity_id": "11111111-1111-1111-1111-111111111111", "mint": "M1", "deployer_wallet": "D1",
            "launch_observed_at": launch_at, "launch_ingested_at": launch_at, "feature_as_of": feature_at,
            "developer_evidence_hash": "devhash", "developer_evidence": {"history_state": "NEW-UNKNOWN"},
            "developer_observed_at": feature_at, "developer_ingested_at": feature_at,
            "correlation_evidence_hash": "corhash", "correlation_evidence": {"status": "NEW-UNKNOWN", "network_motifs": {"records": []}},
            "correlation_observed_at": feature_at, "correlation_ingested_at": feature_at,
        }],
        [{"mint": "M1", "horizon": "5m", "horizon_seconds": 300, "observed_at": feature_at, "ingested_at": feature_at,
          "source": "dexscreener", "evidence_basis": "market_snapshot_observation", "metrics": {"liquidity_usd": 10000}, "event_id": "obs1", "signature": None}],
        [{"mint": "M1", "event_id": "label1", "event_type": "post_migration.tracking_completed",
          "occurred_at": datetime(2026, 9, 1, 0, 30, tzinfo=timezone.utc), "ingested_at": datetime(2026, 9, 1, 0, 31, tzinfo=timezone.utc),
          "signature": None, "producer": "tracker", "payload": {"outcome_status": "RUNNER"}}],
    ])
    result = await form_pattern_discovery_dataset(session, limit=10, as_of="2026-09-02T00:00:00Z", feature_horizon="5m", min_rows=1)
    row = result["rows"][0]
    assert row["feature_as_of"] == feature_at.isoformat()
    assert row["features"]["market_lifecycle"]["observed_horizons"] == ["5m"]
    assert row["label"]["outcome"] == "RUNNER"
    assert row["label"]["observed_at"] > row["feature_as_of"]
    assert row["future_feature_leakage_allowed"] is False
    assert result["pattern_discovery_authority"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False


@pytest.mark.asyncio
async def test_dataset_queries_gate_snapshot_and_lifecycle_features_by_feature_as_of():
    session = _Session([[],])
    result = await form_pattern_discovery_dataset(session, as_of="2026-09-02T00:00:00Z", feature_horizon="15m")
    sql = session.calls[0][0]
    assert "s.observed_at <= l.observed_at + make_interval" in sql
    assert "s.ingested_at <= l.observed_at + make_interval" in sql
    assert result["bounded"]["query_count"] == 1


@pytest.mark.asyncio
async def test_unknown_labels_are_preserved_not_dropped_or_guessed():
    launch_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    feature_at = datetime(2026, 9, 1, 0, 5, tzinfo=timezone.utc)
    session = _Session([[{
        "launch_id": 1, "entity_id": "11111111-1111-1111-1111-111111111111", "mint": "M1", "deployer_wallet": "D1",
        "launch_observed_at": launch_at, "launch_ingested_at": launch_at, "feature_as_of": feature_at,
        "developer_evidence_hash": None, "developer_evidence": None, "developer_observed_at": None, "developer_ingested_at": None,
        "correlation_evidence_hash": None, "correlation_evidence": None, "correlation_observed_at": None, "correlation_ingested_at": None,
    }], [], []])
    result = await form_pattern_discovery_dataset(session, as_of="2026-09-02T00:00:00Z", min_rows=1)
    assert result["row_count"] == 1
    assert result["rows"][0]["label"]["outcome"] == "UNKNOWN"
    assert result["coverage"]["label_coverage"] == 0.0
    assert result["formation_status"] == "INSUFFICIENT_EVIDENCE"


@pytest.mark.asyncio
async def test_dataset_hash_and_row_hash_are_deterministic_for_same_evidence():
    launch_at = datetime(2026, 9, 1, tzinfo=timezone.utc); feature_at = datetime(2026, 9, 1, 0, 5, tzinfo=timezone.utc)
    candidate = {"launch_id": 1, "entity_id": "11111111-1111-1111-1111-111111111111", "mint": "M1", "deployer_wallet": "D1",
        "launch_observed_at": launch_at, "launch_ingested_at": launch_at, "feature_as_of": feature_at,
        "developer_evidence_hash": "d", "developer_evidence": {"history_state": "NEW-UNKNOWN"}, "developer_observed_at": feature_at, "developer_ingested_at": feature_at,
        "correlation_evidence_hash": "c", "correlation_evidence": {"status": "NEW-UNKNOWN"}, "correlation_observed_at": feature_at, "correlation_ingested_at": feature_at}
    label = {"mint": "M1", "event_id": "e", "event_type": "post_migration.tracking_completed", "occurred_at": feature_at,
             "ingested_at": feature_at, "signature": None, "producer": "tracker", "payload": {"outcome_status": "FADE"}}
    a = await form_pattern_discovery_dataset(_Session([[candidate], [], [label]]), as_of="2026-09-02T00:00:00Z", min_rows=1, min_feature_source_coverage=0)
    b = await form_pattern_discovery_dataset(_Session([[candidate], [], [label]]), as_of="2026-09-02T00:00:00Z", min_rows=1, min_feature_source_coverage=0)
    assert a["rows"][0]["row_hash"] == b["rows"][0]["row_hash"]
    assert a["dataset_hash"] == b["dataset_hash"]
