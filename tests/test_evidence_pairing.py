from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evidence_pairing import PairingEvidence, compare_labels


def test_pairing_model_preserves_labels():
    row = PairingEvidence("A", "B", "CONFLICT")
    assert row.left == "A"
    assert row.right == "B"
    assert row.verdict == "CONFLICT"


def test_equal_labels_are_consistent():
    row = compare_labels("REFERENCE_V2", "REFERENCE_V2")
    assert row.verdict == "CONSISTENT"


def test_different_labels_conflict():
    row = compare_labels("REFERENCE_V2", "OTHER_FAMILY")
    assert row.verdict == "CONFLICT"


def test_missing_label_stays_unknown():
    assert compare_labels(None, "REFERENCE_V2").verdict == "UNKNOWN"
    assert compare_labels("REFERENCE_V2", None).verdict == "UNKNOWN"
