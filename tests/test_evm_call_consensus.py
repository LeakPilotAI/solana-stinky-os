from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_call_consensus import classify_exact_results


def test_exact_result_quorum():
    out = classify_exact_results({"0x01": ["a", "b"]})
    assert out.agreed_result == "0x01"
    assert out.providers == ("a", "b")
    assert out.verdict == "EXACT_RESULT_QUORUM"


def test_result_disagreement_fails_closed():
    out = classify_exact_results({"0x01": ["a"], "0x02": ["b"]})
    assert out.agreed_result is None
    assert out.providers == ()
    assert out.verdict == "RESULT_DISAGREEMENT"


def test_insufficient_and_duplicate_evidence_fail_closed():
    out = classify_exact_results({"0x01": ["a", "a"]})
    assert out.verdict == "INSUFFICIENT_RESULT_EVIDENCE"
    with pytest.raises(ValueError, match="min_quorum"):
        classify_exact_results({"0x01": ["a"]}, min_quorum=1)
