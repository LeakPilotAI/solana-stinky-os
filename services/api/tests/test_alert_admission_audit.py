from pathlib import Path

from stinky_api.alert_admission_audit import summarize_inspection_rows

ROOT = Path(__file__).resolve().parents[3]


def test_summarize_inspection_rows_reports_intelligence_bottleneck_without_promotion():
    rows = [
        {
            "pipeline_status": "UNKNOWN",
            "synthetic_level": "MEDIUM",
            "rug_level": "UNKNOWN",
            "fee_status": "VERIFIED",
            "has_intelligence": False,
            "alert_ok": False,
            "alert_reason": "INTELLIGENCE_INSUFFICIENT",
            "missing_data": ["wallets", "creator", "rug"],
            "evidence": {
                "wallets": {"status": "UNKNOWN"},
                "creator": {"status": "UNKNOWN"},
            },
        },
        {
            "pipeline_status": "UNKNOWN",
            "synthetic_level": "LOW",
            "rug_level": "LOW",
            "fee_status": "UNKNOWN",
            "has_intelligence": False,
            "alert_ok": False,
            "alert_reason": "INTELLIGENCE_INSUFFICIENT",
            "missing_data": ["wallets", "creator"],
            "evidence": {
                "wallets": {"status": "UNKNOWN"},
                "creator": {"status": "UNKNOWN"},
            },
        },
    ]
    result = summarize_inspection_rows(rows)
    assert result["status"] == "OBSERVED"
    assert result["inspection_count"] == 2
    assert result["intelligence_insufficient_count"] == 2
    assert result["has_intelligence_count"] == 0
    assert result["alert_ok_count"] == 0
    assert result["missing_fields"]["wallets"] == 2
    assert result["missing_fields"]["creator"] == 2
    assert result["layer_unknown_counts"]["fees"] == 1
    assert result["interpretation"] == "INTELLIGENCE_ACQUISITION_OR_HISTORY_COVERAGE_BOTTLENECK"
    assert result["thresholds_changed"] is False
    assert result["unknown_promoted"] is False
    assert result["live_execution"] is False
    assert result["trading_authority"] is False


def test_empty_window_remains_unknown():
    result = summarize_inspection_rows([])
    assert result["status"] == "UNKNOWN"
    assert result["interpretation"] == "NO_INSPECTIONS_IN_WINDOW"
    assert result["unknown_promoted"] is False


def test_mixed_results_are_not_mislabeled_as_total_intelligence_failure():
    rows = [
        {
            "pipeline_status": "QUALIFIED",
            "synthetic_level": "LOW",
            "rug_level": "LOW",
            "fee_status": "UNKNOWN",
            "has_intelligence": True,
            "alert_ok": True,
            "alert_reason": None,
            "missing_data": [],
            "evidence": {
                "wallets": {"status": "KNOWN"},
                "creator": {"status": "OBSERVED"},
            },
        },
        {
            "pipeline_status": "UNKNOWN",
            "synthetic_level": "MEDIUM",
            "rug_level": "UNKNOWN",
            "fee_status": "VERIFIED",
            "has_intelligence": False,
            "alert_ok": False,
            "alert_reason": "INTELLIGENCE_INSUFFICIENT",
            "missing_data": ["creator"],
            "evidence": {
                "wallets": {"status": "OBSERVED"},
                "creator": {"status": "UNKNOWN"},
            },
        },
    ]
    result = summarize_inspection_rows(rows)
    assert result["interpretation"] == "MIXED_ADMISSION_RESULTS"
    assert result["alert_ok_count"] == 1
    assert result["has_intelligence_count"] == 1


def test_audit_source_is_read_only_and_cannot_weaken_admission():
    source = (ROOT / "services/api/src/stinky_api/alert_admission_audit.py").read_text(encoding="utf-8").lower()
    forbidden = (
        "update market_inspections",
        "insert into alert",
        "delete from",
        "truncate ",
        "min_score=",
        "min_volume",
        "provision_paper_policy",
        "paper_policy_active",
        "send_transaction",
        "sign_transaction",
        "private_key",
    )
    assert not any(token in source for token in forbidden)


def test_cli_requires_explicit_window():
    cli = (ROOT / "scripts/report_alert_admission.py").read_text(encoding="utf-8")
    line = next(line for line in cli.splitlines() if 'add_argument("--hours"' in line)
    assert "required=True" in line
