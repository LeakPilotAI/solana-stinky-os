from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

import stinky_core.evm_reference_dex_identity as identity_module
from stinky_core.evm_reference_deployment_identity import ReferenceDeploymentIdentityAssessment
from stinky_core.evm_reference_dex_authenticity import ReferenceDexAuthenticityAssessment
from stinky_core.evm_reference_dex_identity import (
    compose_reference_dex_identity,
    compose_reference_dex_identity_from_record,
)
from stinky_core.evm_reference_fingerprints import DexReferenceContractSource

FACTORY = "0x" + "11" * 20
POOL = "0x" + "22" * 20
ROUTER = "0x" + "33" * 20


def impl(verdict):
    return ReferenceDexAuthenticityAssessment("EXACT_IMPLEMENTATION_FINGERPRINT_MATCH", "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH", "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH", "FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL", "DEX_IMPLEMENTATION_FAMILY_CONSISTENT", verdict, "UNVERIFIED_REFERENCE_DEX_AUTHENTICITY_ASSESSMENT", ())


def dep(role, verdict, address):
    return ReferenceDeploymentIdentityAssessment("base", address, role, (), verdict, "UNVERIFIED_REFERENCE_DEPLOYMENT_IDENTITY_ASSESSMENT", ())


def source(role, address, locator):
    return DexReferenceContractSource(
        chain="base",
        address=address,
        contract_role=role,
        implementation_family="DEX_A",
        implementation_version="v1",
        source_repository="Example/dex",
        source_commit="1" * 40,
        source_path="addresses.py",
        source_locator=locator,
    )


def fake_record():
    return SimpleNamespace(
        envelope=SimpleNamespace(
            factory_fingerprint=SimpleNamespace(chain="base", address=FACTORY),
            pool_fingerprint=SimpleNamespace(chain="base", address=POOL),
            router_fingerprint=SimpleNamespace(chain="base", address=ROUTER),
        )
    )


def test_full_confirmation_requires_all_deployment_matches():
    result = compose_reference_dex_identity(
        impl("REFERENCE_DEX_COMPONENTS_MATCH"),
        dep("FACTORY", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH", FACTORY),
        dep("POOL", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH", POOL),
        dep("ROUTER", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH", ROUTER),
    )
    assert result.verdict == "REFERENCE_DEX_IDENTITY_CONFIRMED"


def test_unknown_pool_keeps_identity_unknown():
    result = compose_reference_dex_identity(
        impl("REFERENCE_DEX_COMPONENTS_MATCH"),
        dep("FACTORY", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH", FACTORY),
        dep("POOL", "UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY", POOL),
        dep("ROUTER", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH", ROUTER),
    )
    assert result.verdict == "UNKNOWN_REFERENCE_DEX_IDENTITY"


def test_known_conflict_outranks_unknown():
    result = compose_reference_dex_identity(
        impl("UNKNOWN_REFERENCE_DEX_AUTHENTICITY"),
        dep("FACTORY", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_CONFLICT", FACTORY),
        dep("POOL", "UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY", POOL),
        dep("ROUTER", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH", ROUTER),
    )
    assert result.verdict == "REFERENCE_DEX_IDENTITY_CONFLICT"


def test_role_order_fails_closed():
    try:
        compose_reference_dex_identity(
            impl("REFERENCE_DEX_COMPONENTS_MATCH"),
            dep("ROUTER", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH", ROUTER),
            dep("POOL", "UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY", POOL),
            dep("FACTORY", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH", FACTORY),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("role confusion must fail closed")


def test_record_backed_composition_uses_preserved_addresses(monkeypatch):
    monkeypatch.setattr(identity_module, "assess_reference_dex_authenticity", lambda record: impl("REFERENCE_DEX_COMPONENTS_MATCH"))
    sources = (
        source("FACTORY", FACTORY, "factory"),
        source("POOL", POOL, "pool"),
        source("ROUTER", ROUTER, "router"),
    )
    result = compose_reference_dex_identity_from_record(fake_record(), sources)
    assert result.verdict == "REFERENCE_DEX_IDENTITY_CONFIRMED"
    assert result.factory_deployment.address == FACTORY
    assert result.pool_deployment.address == POOL
    assert result.router_deployment.address == ROUTER


def test_record_backed_composition_preserves_unknown_pool(monkeypatch):
    monkeypatch.setattr(identity_module, "assess_reference_dex_authenticity", lambda record: impl("REFERENCE_DEX_COMPONENTS_MATCH"))
    sources = (
        source("FACTORY", FACTORY, "factory"),
        source("ROUTER", ROUTER, "router"),
    )
    result = compose_reference_dex_identity_from_record(fake_record(), sources)
    assert result.pool_deployment.verdict == "UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY"
    assert result.verdict == "UNKNOWN_REFERENCE_DEX_IDENTITY"
