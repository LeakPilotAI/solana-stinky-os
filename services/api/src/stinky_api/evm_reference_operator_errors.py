"""Stable public operator failures without untrusted exception text or inputs."""
from __future__ import annotations

import argparse
from json import JSONDecodeError

from pydantic import ValidationError
from stinky_core.evm_rpc import EvmRpcError


class OperatorArgumentError(ValueError):
    """Invalid command syntax; raw argparse diagnostics may contain secrets."""


class OperatorArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise OperatorArgumentError("invalid operator arguments")


def serialize_operator_failure(exc: Exception, *, preflight: bool = False) -> dict:
    """Never expose exception messages, input values, contexts or local paths."""
    if isinstance(exc, OperatorArgumentError):
        error, detail = "ArgumentError", "Invalid operator arguments; use --help for supported options."
    elif isinstance(exc, ValidationError):
        error, detail = "ValidationError", "Operator payload validation failed; check required fields and types."
    elif isinstance(exc, JSONDecodeError):
        error, detail = "JSONDecodeError", "Operator input must contain valid JSON."
    elif isinstance(exc, OSError):
        error, detail = "OSError", "Operator I/O failed; check input access and service availability."
    elif isinstance(exc, EvmRpcError):
        error, detail = "EvmRpcError", "Provider evidence could not be validated; observation failed closed."
    elif isinstance(exc, ValueError):
        error, detail = "ValueError", "Operator evidence or request was rejected; verify its configuration and historical identity."
    else:
        error, detail = "RuntimeError", "Operator processing failed; no successful result is available."
    result = {"ok": False, "error": error, "detail": detail,
              "read_only": True, "execution_authorized": False}
    if preflight:
        result["validated_offline"] = False
    return result
