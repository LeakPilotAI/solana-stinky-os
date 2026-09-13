from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_dex_provenance_interpretation import interpret_dex_provenance
from stinky_core.evm_dex_provenance_profile import DexProvenanceProfile


def profile(verdict):
    return DexProvenanceProfile(
        strict_lineage=SimpleNamespace(),
        pool_evidence_tier=SimpleNamespace(),
        profile=verdict,
        verdict=verdict,
        status="UNVERIFIED_DEX_PROVENANCE_PROFILE",
        limitations=("preserved",),
    )


def test_strict_pinned_category_preserves_profile():
    original = profile("STRICT_EXTERNALLY_PINNED_DEX_PROVENANCE_CONFIRMED")
    result = interpret_dex_provenance(original)
    assert result.provenance_profile is original
    assert result.category == "STRICT_PINNED_PROVENANCE"


def test_factory_attested_category_is_explicitly_not_strict():
    original = profile("FACTORY_ATTESTED_POOL_WITH_UNCONFIRMED_STRICT_DEX_PROVENANCE")
    result = interpret_dex_provenance(original)
    assert result.provenance_profile is original
    assert result.category == "FACTORY_ATTESTED_BUT_NOT_STRICTLY_PINNED"


def test_conflict_category_is_explicit():
    result = interpret_dex_provenance(profile("DEX_PROVENANCE_CONFLICT"))
    assert result.category == "CONFLICTED_PROVENANCE"


def test_unknown_category_remains_unknown():
    result = interpret_dex_provenance(profile("UNKNOWN_DEX_PROVENANCE_PROFILE"))
    assert result.category == "UNKNOWN_OR_INSUFFICIENT_PROVENANCE"


def test_unsupported_profile_fails_closed():
    try:
        interpret_dex_provenance(profile("UNRECOGNIZED_PROVENANCE"))
    except ValueError:
        pass
    else:
        raise AssertionError("unsupported provenance profile must fail closed")


def test_interpretation_is_descriptive_only():
    result = interpret_dex_provenance(profile("STRICT_EXTERNALLY_PINNED_DEX_PROVENANCE_CONFIRMED"))
    assert result.status == "DESCRIPTIVE_NON_EXECUTION_PROVENANCE_INTERPRETATION"
    assert "PROVENANCE_INTERPRETATION_DOES_NOT_MODIFY_UNDERLYING_VERDICTS" in result.limitations
    assert "PROVENANCE_INTERPRETATION_IS_NOT_A_TOKEN_OR_DEX_SAFETY_DECISION" in result.limitations
    assert "PROVENANCE_INTERPRETATION_IS_NOT_AN_ADMISSION_DECISION" in result.limitations
    assert "PROVENANCE_INTERPRETATION_IS_NOT_AN_OPPORTUNITY_SCORE" in result.limitations
    assert "PROVENANCE_INTERPRETATION_IS_NOT_AN_EXECUTION_AUTHORIZATION" in result.limitations
