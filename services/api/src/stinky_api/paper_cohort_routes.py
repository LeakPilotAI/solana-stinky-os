"""Read-only cohort evidence; POST carries explicit selection and optional criteria."""
from fastapi import APIRouter, Depends
from stinky_api.db import get_session
from stinky_api.paper_cohort_report import report_paper_cohort

router = APIRouter()


@router.post("/v1/paper/cohort-report")
async def paper_cohort_report(body: dict, session=Depends(get_session)):
    return await report_paper_cohort(
        session, policy_sha256=body.get("policy_sha256"), policy_version=body.get("policy_version"),
        evidence_backed=body.get("evidence_backed"), as_of=body.get("as_of"),
        record_limit=body.get("record_limit", 500), release_criteria=body.get("release_criteria"),
    )
