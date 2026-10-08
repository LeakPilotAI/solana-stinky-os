from datetime import datetime, timezone

from stinky_api.intelligence_execution_v2 import (
    summarize_execution_v2,
)


def _row(
    *,
    mint: str,
    status: str | None,
    session: dict | None = None,
):
    return {
        "mint": mint,
        "policy_sha256": "frozen-sha",
        "prospective_boundary": datetime(
            2026,
            10,
            7,
            11,
            51,
            tzinfo=timezone.utc,
        ),
        "plan": {
            "runtime_session": session,
        },
        "result": (
            {"status": status}
            if status is not None
            else None
        ),
    }


def test_v2_operator_summary_reports_evidence_without_authority():
    session = {
        "service": "collector",
        "supervisor_pid": 123,
        "started_at": "2026-10-07T10:00:00Z",
        "identity_verified": True,
    }

    result = summarize_execution_v2(
        [
            _row(
                mint="mint-a",
                status="PAPER_PRICED",
                session=session,
            ),
            _row(
                mint="mint-b",
                status="REJECTED",
                session=session,
            ),
            _row(
                mint="mint-c",
                status="UNKNOWN",
                session=session,
            ),
        ]
    )

    assert result["status"] == "OBSERVED"
    assert result["counts"] == {
        "PAPER_PRICED": 1,
        "REJECTED": 1,
        "UNKNOWN": 1,
        "PENDING": 0,
    }

    assert result[
        "distinct_mint_mature_plans"
    ] == 3

    assert result[
        "verified_runtime_sessions"
    ] == 1

    assert result["priced_paths"] == 1

    assert result["unknown_fraction"] == 1 / 3
    assert result["evaluation_ready"] is False

    assert result["paper_only"] is True
    assert result["read_only"] is True
    assert result["performance_validation"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
    assert result["live_execution"] is False
    assert result["order_submitted"] is False
    assert result["transaction_signed"] is False
    assert result["wallet_mutated"] is False
    assert result["trading_authority"] is False


def test_v2_operator_summary_deduplicates_sessions_and_mints():
    session = {
        "service": "collector",
        "supervisor_pid": 123,
        "started_at": "2026-10-07T10:00:00Z",
        "identity_verified": True,
    }

    result = summarize_execution_v2(
        [
            _row(
                mint="same-mint",
                status="PAPER_PRICED",
                session=session,
            ),
            _row(
                mint="same-mint",
                status="PAPER_PRICED",
                session=session,
            ),
        ]
    )

    assert result[
        "distinct_mint_mature_plans"
    ] == 1

    assert result[
        "verified_runtime_sessions"
    ] == 1

    assert result["priced_paths"] == 2
    assert result["unknown_fraction"] == 0


def test_v2_operator_summary_rejects_unverified_session():
    session = {
        "service": "collector",
        "supervisor_pid": 123,
        "started_at": "2026-10-07T10:00:00Z",
        "identity_verified": False,
    }

    result = summarize_execution_v2(
        [
            _row(
                mint="mint-a",
                status="UNKNOWN",
                session=session,
            ),
        ]
    )

    assert result[
        "verified_runtime_sessions"
    ] == 0


def test_v2_operator_summary_keeps_pending_out_of_maturity():
    result = summarize_execution_v2(
        [
            _row(
                mint="mint-a",
                status=None,
            ),
        ]
    )

    assert result["counts"]["PENDING"] == 1

    assert result[
        "distinct_mint_mature_plans"
    ] == 0

    assert result["unknown_fraction"] is None
    assert result["evaluation_ready"] is False


def test_v2_operator_route_is_registered():
    from stinky_api.intelligence_execution_v2 import router

    matches = [
        route
        for route in router.routes
        if getattr(route, "path", None)
        == "/v1/intelligence/execution-v2"
    ]

    assert len(matches) == 1
    assert "GET" in (matches[0].methods or set())


def test_pending_session_accounting_matches_frozen_canonical_report(monkeypatch):
    """A pending plan cannot advance the canonical mature-session gate."""
    import importlib.util
    from datetime import timedelta
    from pathlib import Path
    from uuid import uuid4

    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "canonical_v2_operator_parity", root / "scripts/run_intelligence_execution_v2.py"
    )
    canonical = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(canonical)
    boundary = datetime(2026, 10, 7, 11, 51, tzinfo=timezone.utc)
    source = {
        "id": 1, "track_id": uuid4(), "mint": "pending-mint",
        "policy_version": canonical.policy()["source_policy"],
        "decision": "PAPER_WOULD_ENTER", "migration_at": boundary,
        "scored_at": boundary + timedelta(seconds=60),
        "decided_at": boundary + timedelta(seconds=61),
        "runtime_session": {
            "service": "collector", "supervisor_pid": 123,
            "started_at": boundary.isoformat(), "identity_verified": True,
        },
    }
    plan = canonical.make_plan(source, boundary, source["decided_at"])
    row = {
        "mint": plan["mint"], "plan": plan,
        "policy_sha256": plan["policy_sha256"], "prospective_boundary": boundary,
        "plan_sha256": canonical.policy_hash(plan), "result": None, "result_sha256": None,
    }
    expected = canonical.summarize([row])
    actual = summarize_execution_v2([row])
    assert expected["verified_runtime_sessions"] == 0
    assert actual["verified_runtime_sessions"] == expected["verified_runtime_sessions"]
    assert actual["distinct_mint_mature_plans"] == expected["distinct_mint_mature_plans"]


def test_pending_only_sessions_cannot_satisfy_adequacy():
    rows = [
        _row(mint=f"mature-{i}", status="PAPER_PRICED", session={
            "service": "collector", "supervisor_pid": 123,
            "started_at": "2026-10-07T10:00:00Z", "identity_verified": True,
        }) for i in range(100)
    ]
    rows.extend(_row(mint=f"pending-{i}", status=None, session={
        "service": "collector", "supervisor_pid": 200+i,
        "started_at": f"2026-10-07T1{i}:00:00Z", "identity_verified": True,
    }) for i in range(4))
    result = summarize_execution_v2(rows)
    assert result["verified_runtime_sessions"] == 1
    assert result["counts"]["PENDING"] == 4
    assert result["adequacy_gates"]["verified_runtime_sessions"]["passed"] is False
    assert result["evaluation_ready"] is False
