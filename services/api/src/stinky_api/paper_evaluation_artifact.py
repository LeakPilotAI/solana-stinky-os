"""Content-addressed paper evaluation snapshots with offline replay verification.

Returned artifacts are not signatures or proof of database origin. Keep the full
artifact and its externally recorded digest to detect later substitution. Source
timestamps are historical evidence; no generation clock enters the identity.
"""
from copy import deepcopy
from datetime import datetime, timezone
from stinky_api.paper_evidence_json import canonical_bytes, content_sha256

from stinky_api.walk_forward_paper_validation import EVALUATOR_VERSION

SCHEMA_VERSION = "paper-evaluation-artifact-v1"
AUTHORITY = {
    "paper_only": True, "live_execution": False, "trading_authority": False,
    "automatic_activation": False, "transaction_signed": False,
    "order_submitted": False, "wallet_mutated": False,
    "trade_signal": False, "recommendation_authority": False,
}
SOURCE_FIELDS = (
    "intake_id", "mint", "intake_mint", "decided_at", "observed_at",
    "created_at", "intake_created_at", "policy_version", "policy_sha256",
    "policy_evidence_backed", "paper_status", "record", "payload", "payload_sha256",
)
TIME_FIELDS = ("decided_at", "observed_at", "created_at", "intake_created_at")


def build_evaluation_artifact(rows, report, criteria):
    if report.get("walk_forward_evaluated") is not True:
        raise ValueError("completed_evaluation_required")
    sources = []
    for row in rows:
        source = {key: deepcopy(row[key]) for key in SOURCE_FIELDS}
        for key in TIME_FIELDS:
            at = source[key]
            if not isinstance(at, datetime):
                at = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
            if at.tzinfo is None or at.utcoffset() is None:
                raise ValueError("timezone_aware_evidence_required")
            source[key] = at.astimezone(timezone.utc).isoformat()
        source["record_sha256"] = content_sha256(source["record"])
        if content_sha256(source["payload"]) != source["payload_sha256"]:
            raise ValueError("frozen_payload_hash_mismatch")
        sources.append(source)
    sources.sort(key=lambda row: (row["created_at"], row["intake_id"]))
    content = {
        "schema_version": SCHEMA_VERSION, "evaluator_version": EVALUATOR_VERSION,
        "policy_identity": deepcopy(report["selected_policy_identity"]),
        "as_of": report["as_of"], "release_criteria": deepcopy(criteria),
        "source_records": sources,
        "evaluated_intake_ids": [row["intake_id"] for row in report["walk_forward"]["evaluated_records"]],
        "evidence_window": deepcopy(report["evidence_window"]),
        "evaluation": deepcopy(report["walk_forward"]),
        "authority": dict(AUTHORITY),
    }
    return {"artifact_sha256": content_sha256(content), "content": content}


def verify_evaluation_artifact(artifact):
    """Verify digest AND replay the cohort checks/metrics with the supported version.

    Does not query a registry/database, infer missing evidence, activate a policy,
    or grant authority. Re-hashing fabricated content is not an authenticity proof.
    """
    result = {"status": "UNKNOWN", "valid": False, **AUTHORITY}
    try:
        if type(artifact) is not dict or set(artifact) != {"artifact_sha256", "content"}:
            raise ValueError("invalid_artifact_envelope")
        content = artifact["content"]
        if content_sha256(content) != artifact["artifact_sha256"]:
            raise ValueError("artifact_hash_mismatch")
        if (content["schema_version"] != SCHEMA_VERSION
                or content["evaluator_version"] != EVALUATOR_VERSION):
            raise ValueError("unsupported_artifact_version")
        if canonical_bytes(content["authority"]) != canonical_bytes(AUTHORITY):
            raise ValueError("invalid_artifact_authority")
        from stinky_api.paper_cohort_report import _selection_report, evaluate_cohort_rows
        from stinky_api.paper_policy_identity import validated_policy_identity
        identity = validated_policy_identity(content["policy_identity"])
        if identity is None:
            raise ValueError("invalid_policy_identity")
        sources = content["source_records"]
        if type(sources) is not list or not 1 <= len(sources) <= 2000:
            raise ValueError("invalid_source_records")
        for source in sources:
            if set(source) != set(SOURCE_FIELDS) | {"record_sha256"}:
                raise ValueError("incomplete_source_identity")
            if content_sha256(source["record"]) != source["record_sha256"]:
                raise ValueError("runtime_record_hash_mismatch")
        selection = _selection_report(
            identity["policy_sha256"], identity["policy_version"],
            identity["provenance"]["evidence_backed"], content["as_of"],
            len(sources), content["release_criteria"],
        )
        if "reasons" in selection:
            raise ValueError("invalid_evaluation_selection")
        replay = evaluate_cohort_rows(sources, selection=selection,
                                     release_criteria=content["release_criteria"], produce_artifact=False)
        rebuilt = build_evaluation_artifact(sources, replay, content["release_criteria"])
        if canonical_bytes(rebuilt) != canonical_bytes(artifact):
            raise ValueError("evaluation_replay_mismatch")
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        return {**result, "reason": "invalid_or_unreproducible_evaluation_artifact"}
    return {**result, "status": "VERIFIED", "valid": True,
            "artifact_sha256": artifact["artifact_sha256"]}
