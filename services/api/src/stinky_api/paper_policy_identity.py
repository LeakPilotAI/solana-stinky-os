"""Validation shared by immutable paper evidence consumers."""
from copy import deepcopy
import json
import hashlib
from datetime import datetime
import re
from typing import Any


def validated_provenance(provenance: Any) -> dict | None:
    if not isinstance(provenance, dict) or type(provenance.get("evidence_backed")) is not bool:
        return None
    expected = "EVIDENCE_BACKED_SCORE_CANDIDATE" if provenance["evidence_backed"] else "MANUAL_OPERATOR_SUPPLIED"
    if provenance.get("mode") != expected:
        return None
    try:
        from stinky_api.paper_evidence_json import canonical_bytes
        canonical_bytes(provenance)
        if provenance["evidence_backed"]:
            sha = provenance.get("candidate_evidence_sha256")
            comparison_sha = provenance.get("comparison_evidence_sha256")
            provenance_sha = provenance.get("provenance_sha256")
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
                return None
            if not isinstance(comparison_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", comparison_sha):
                return None
            if not isinstance(provenance_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", provenance_sha):
                return None
            if provenance.get("candidate_version") != f"score-paper-candidate-v1:{sha[:16]}":
                return None
            cutoff = datetime.fromisoformat(provenance["candidate_cutoff"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(provenance["comparison_as_of"].replace("Z", "+00:00"))
            if cutoff.tzinfo is None or end.tzinfo is None or end <= cutoff:
                return None
            checks, criteria = provenance.get("readiness_checks"), provenance.get("readiness_criteria")
            if not isinstance(checks, dict) or not checks or not all(v is True for v in checks.values()):
                return None
            if not isinstance(criteria, dict) or not criteria:
                return None
            body = {k: v for k, v in provenance.items() if k != "provenance_sha256"}
            if hashlib.sha256(canonical_bytes(body)).hexdigest() != provenance.get("provenance_sha256"):
                return None
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        return None
    return deepcopy(provenance)


def validated_policy_identity(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    version, sha, provenance = (value.get(k) for k in ("policy_version", "policy_sha256", "provenance"))
    if not isinstance(version, str) or not version.strip() or version != version.strip():
        return None
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{64}", sha) is None:
        return None
    if validated_provenance(provenance) is None:
        return None
    try:
        json.dumps(provenance, allow_nan=False, sort_keys=True)
    except (ValueError, TypeError):
        return None
    return deepcopy({"policy_version": version, "policy_sha256": sha, "provenance": provenance})


def frozen_policy_matches_identity(payload: Any) -> bool:
    """Bind frozen thresholds/costs/notional/provenance to the registry digest."""
    from stinky_api.paper_policy_provisioning import validate_paper_configuration
    from stinky_api.paper_evidence_json import content_sha256
    if not isinstance(payload, dict):
        return False
    policy, identity = payload.get("paper_policy"), payload.get("policy_identity")
    if not isinstance(policy, dict) or not isinstance(identity, dict):
        return False
    if validated_policy_identity({**identity, "policy_version": policy.get("policy_version")}) is None:
        return False
    try:
        checked = validate_paper_configuration(payload)
        if checked.get("status") != "VALIDATED":
            return False
        config = checked["configuration"]
        config["provenance"] = identity["provenance"]
        return content_sha256(config) == identity["policy_sha256"]
    except (TypeError, ValueError, OverflowError, RecursionError):
        return False
