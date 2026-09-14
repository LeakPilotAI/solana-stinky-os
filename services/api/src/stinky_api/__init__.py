"""Stinky OS Intelligence API."""

__version__ = "0.1.0"

# Register read-only extensions on the existing entity-graph router before main includes it.
from stinky_api import command_center_readiness as _command_center_readiness  # noqa: E402,F401
from stinky_api import dex_provenance_http as _dex_provenance_http  # noqa: E402,F401
from stinky_api import evm_provider_attestation_http as _evm_provider_attestation_http  # noqa: E402,F401
