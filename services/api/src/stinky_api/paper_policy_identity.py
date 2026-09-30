"""Validation shared by immutable paper evidence consumers."""
from copy import deepcopy
import json
import re
from typing import Any


def validated_policy_identity(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    version, sha, provenance = (value.get(k) for k in ("policy_version", "policy_sha256", "provenance"))
    if not isinstance(version, str) or not version.strip() or version != version.strip():
        return None
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{64}", sha) is None:
        return None
    if not isinstance(provenance, dict) or type(provenance.get("evidence_backed")) is not bool:
        return None
    expected = "EVIDENCE_BACKED_SCORE_CANDIDATE" if provenance["evidence_backed"] else "MANUAL_OPERATOR_SUPPLIED"
    if provenance.get("mode") != expected:
        return None
    try:
        json.dumps(provenance, allow_nan=False, sort_keys=True)
    except (ValueError, TypeError):
        return None
    return deepcopy({"policy_version": version, "policy_sha256": sha, "provenance": provenance})
