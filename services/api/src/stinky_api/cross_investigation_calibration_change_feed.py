"""Cross-investigation descriptive feed of calibration synthesis changes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.market_pattern_calibration_synthesis_audit import describe_synthesis_change


def _parse_as_of(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _change_kinds(change: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for item in change.get("changes", []) or []:
        if isinstance(item, dict):
            kind = str(item.get("kind") or "").strip()
            if kind and kind not in out:
                out.append(kind)
    return out


async def calibration_change_feed(
    session: AsyncSession,
    *,
    limit: int = 50,
    as_of: datetime | str | None = None,
    include_unchanged: bool = False,
) -> dict[str, Any]:
    """Return latest factual synthesis delta for each observed pattern."""
    limit = max(1, min(200, int(limit)))
    cutoff = _parse_as_of(as_of)
    if as_of is not None and cutoff is None:
        return {
            "status": "UNKNOWN",
            "items": [],
            "count": 0,
            "missing": ["valid_as_of"],
            "evidence_only": True,
            "predictive_authority": False,
            "trade_signal": False,
        }

    clause = "WHERE s.observed_at <= :as_of AND s.ingested_at <= :as_of" if cutoff is not None else ""
    params: dict[str, Any] = {"limit": limit}
    if cutoff is not None:
        params["as_of"] = cutoff

    try:
        rows = (
            await session.execute(
                text(
                    f"""
                    WITH ranked AS (
                        SELECT
                            s.pattern_hash,
                            s.synthesis,
                            s.observed_at,
                            s.ingested_at,
                            ROW_NUMBER() OVER (
                                PARTITION BY s.pattern_hash
                                ORDER BY s.observed_at DESC, s.id DESC
                            ) AS rn
                        FROM market_pattern_calibration_synthesis_snapshots s
                        {clause}
                    ), paired AS (
                        SELECT
                            a.pattern_hash,
                            a.synthesis AS current_synthesis,
                            a.observed_at AS current_observed_at,
                            a.ingested_at AS current_ingested_at,
                            b.synthesis AS previous_synthesis,
                            b.observed_at AS previous_observed_at
                        FROM ranked a
                        LEFT JOIN ranked b
                          ON b.pattern_hash = a.pattern_hash AND b.rn = 2
                        WHERE a.rn = 1
                    )
                    SELECT
                        p.*,
                        occ.mint,
                        occ.observed_at AS occurrence_observed_at
                    FROM paired p
                    LEFT JOIN LATERAL (
                        SELECT mint, observed_at
                        FROM market_path_pattern_occurrences
                        WHERE pattern_hash = p.pattern_hash
                        ORDER BY observed_at DESC, id DESC
                        LIMIT 1
                    ) occ ON TRUE
                    ORDER BY p.current_observed_at DESC, p.pattern_hash
                    LIMIT :limit
                    """
                ),
                params,
            )
        ).mappings().all()
    except Exception:
        return {
            "status": "UNKNOWN",
            "items": [],
            "count": 0,
            "missing": ["market_pattern_calibration_synthesis_snapshots"],
            "evidence_only": True,
            "predictive_authority": False,
            "trade_signal": False,
        }

    items: list[dict[str, Any]] = []
    for row in rows:
        current = dict(row.get("current_synthesis") or {})
        previous_raw = row.get("previous_synthesis")
        previous = dict(previous_raw or {}) if previous_raw is not None else None
        change = describe_synthesis_change(previous, current)
        if not include_unchanged and change.get("status") == "UNCHANGED":
            continue
        items.append(
            {
                "pattern_hash": row.get("pattern_hash"),
                "mint": row.get("mint"),
                "observed_at": row.get("current_observed_at").isoformat() if row.get("current_observed_at") else None,
                "previous_observed_at": row.get("previous_observed_at").isoformat() if row.get("previous_observed_at") else None,
                "change_status": change.get("status"),
                "change_kinds": _change_kinds(change),
                "changes": change.get("changes", []),
                "current_calibration_state": current.get("current_calibration_state"),
                "evidence_status": current.get("evidence_status"),
                "predictive_authority": False,
                "trade_signal": False,
                "shared_cause_inferred": False,
                "evidence_only": True,
            }
        )

    result: dict[str, Any] = {
        "status": "OBSERVED" if items else "UNKNOWN",
        "items": items,
        "count": len(items),
        "bounded": {"limit": limit},
        "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
        "predictive_authority": False,
        "trade_signal": False,
        "shared_cause_inferred": False,
        "evidence_only": True,
    }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result
