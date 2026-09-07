"""Stinky OS Intelligence API."""

__version__ = "0.1.0"

# Register the operator readiness extension on the existing entity-graph router.
# Importing here ensures the route exists before main includes that router.
from stinky_api import command_center_readiness as _command_center_readiness  # noqa: E402,F401
