"""Offline, fail-closed preflight for EVM reference operator payloads."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from stinky_api.evm_reference_operator_errors import (
    OperatorArgumentError, OperatorArgumentParser, serialize_operator_failure,
)

from stinky_api.evm_reference_operator_transport import (
    ReferenceDexOperatorPayload,
    validate_operator_payload,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = OperatorArgumentParser(
        prog="genesis-evm-reference-preflight",
        description=(
            "Validate an EVM reference operator payload completely offline. "
            "No RPC, database, observation, scheduling, or transaction execution."
        ),
    )
    parser.add_argument("--input", required=True, help="Path to the operator JSON payload")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
        payload = ReferenceDexOperatorPayload.model_validate(raw)
        output = validate_operator_payload(payload)
    except Exception as exc:
        print(json.dumps(serialize_operator_failure(exc, preflight=True), sort_keys=True))
        return 2 if isinstance(exc, OperatorArgumentError) else 1

    print(json.dumps({"ok": True, **output}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
