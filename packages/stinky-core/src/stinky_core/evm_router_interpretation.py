"""Compose decoded calldata and return-data evidence without claiming execution."""
from __future__ import annotations

from dataclasses import dataclass

from .evm_router_output import RouterOutputSemantics, decode_uint256_array_output
from .evm_router_semantics import RouterCalldataSemantics, decode_router_calldata
from .evm_router_swap import RouterSwapCallEvidence


@dataclass(frozen=True, slots=True)
class RouterCallSemanticEvidence:
    chain: str
    router: str
    caller: str
    block_number: int
    call_verdict: str
    calldata: RouterCalldataSemantics
    output: RouterOutputSemantics
    verdict: str
    status: str
    limitations: tuple[str, ...]


def interpret_router_call(evidence: RouterSwapCallEvidence) -> RouterCallSemanticEvidence:
    if evidence.status != "UNVERIFIED_ROUTER_SWAP_CALL_EVIDENCE":
        raise ValueError("unsupported router-call evidence status")

    calldata = decode_router_calldata(
        chain=evidence.chain,
        calldata=evidence.calldata,
        value=evidence.value,
    )
    if calldata.status != "SUPPORTED_ROUTER_CALLDATA_SEMANTICS":
        output = RouterOutputSemantics(
            (), None, None, None,
            "OUTPUT_NOT_DECODED",
            ("CALLDATA_SEMANTICS_NOT_VERIFIED",),
        )
        verdict = "UNKNOWN_ROUTER_CALL_SEMANTICS"
    elif evidence.verdict != "ROUTER_SWAP_CALL_QUORUM_SUCCEEDED" or evidence.agreed_result is None:
        output = RouterOutputSemantics(
            (), None, None, None,
            "NO_QUORUM_OUTPUT",
            ("ROUTER_CALL_NOT_QUORUM_CONFIRMED",),
        )
        verdict = "UNKNOWN_ROUTER_CALL_OUTPUT"
    else:
        output = decode_uint256_array_output(
            evidence.agreed_result,
            expected_length=len(calldata.path),
            expected_input=calldata.amount_in,
            minimum_output=calldata.amount_out_min,
        )
        verdict = (
            "SUPPORTED_CALLDATA_AND_OUTPUT_DECODED"
            if output.status == "DECODED_UINT256_ARRAY_OUTPUT"
            else "UNKNOWN_ROUTER_CALL_OUTPUT"
        )

    return RouterCallSemanticEvidence(
        evidence.chain,
        evidence.router,
        evidence.caller,
        evidence.block_number,
        evidence.verdict,
        calldata,
        output,
        verdict,
        "UNVERIFIED_ROUTER_CALL_SEMANTIC_EVIDENCE",
        (
            "SELECTOR_MATCH_DOES_NOT_PROVE_ROUTER_IMPLEMENTATION_OR_AUTHENTICITY",
            "SEMANTIC_DECODE_DOES_NOT_PROVE_STATE_CHANGING_EXECUTION_SUCCESS",
            "DECODED_OUTPUT_IS_HISTORICAL_ETH_CALL_RETURN_DATA_ONLY",
            "DOES_NOT_PROVE_TOKEN_TAX_OR_TRANSFER_BEHAVIOR",
            "DOES_NOT_PROVE_REAL_SALE_SUCCESS",
        ),
    )
