from entity_resolver.chain_evidence import FundingScanResult
from entity_resolver.funding_diagnostics import funding_scan_log_fields


def test_funding_scan_log_fields_make_zero_result_explicit():
    fields = funding_scan_log_fields(
        "wallet-a",
        FundingScanResult([], 50, 12, 11, True),
    )
    assert fields == {
        "wallet": "wallet-a",
        "rpc_success": True,
        "signatures_requested": 50,
        "signatures_returned": 12,
        "signatures_examined": 11,
        "inbound_native_sol_transfers": 0,
        "zero_result": True,
    }
