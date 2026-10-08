from contextlib import asynccontextmanager
import pytest
from stinky_api.paper_status_contract import readiness, paper_status_contract

@pytest.mark.parametrize("value",["", "0", "-1", "1.5", "Infinity", "\\d", "9007199254740992"])
def test_invalid_criteria_never_acquire_defaults(value):
    result=readiness((value,"8","2"),0,0,0)
    assert result["status"]=="CRITERIA_NOT_SET" and result["deficits"] is None
    assert result["automatic_activation"] is False

def test_configured_criteria_preserve_missing_market_source():
    result=readiness(("12"," 8 ","2"),3,1,None)
    assert result["status"]=="CRITERIA_CONFIGURED"
    assert result["deficits"]=={"closed_outcomes_needed":9,"outcome_classes_needed":1,"market_cap_samples_needed":None}
    assert result["observed_market_cap_samples"] is None
    assert result["market_cap_samples_available"] is False
    assert result["policy_provisioned"] is result["automatic_activation"] is False

class Result:
    def __init__(self,value): self.value=value
    def mappings(self): return self
    def all(self): return self.value
    def scalar_one(self): return self.value
    def scalar_one_or_none(self): return self.value

class Session:
    def __init__(self, *, market_failure=False, active_failure=False, registry_failure=False):
        self.market_failure=market_failure;self.active_failure=active_failure;self.registry_failure=registry_failure
        self.statements=[];self.savepoints=0
        self.identity={"policy_version":"version|one\ncontinued","policy_sha256":"a"*64,
            "provenance":{"evidence_backed":True,"comparison_evidence_sha256":"c"*64}}
    @asynccontextmanager
    async def begin_nested(self):
        self.savepoints+=1
        yield
    async def execute(self,statement):
        sql=str(statement);self.statements.append(sql)
        if "LEFT JOIN" in sql:
            if self.registry_failure: raise RuntimeError("registry unavailable")
            return Result([{"payload":{"state":"ACTIVE" if i==0 else "PROVISIONED", "policy_identity":self.identity}}
                for i in range(51)])
        if "FROM paper_policy_active" in sql:
            if self.active_failure: raise RuntimeError("active unavailable")
            return Result({"status":"ACTIVE","policy_identity":self.identity})
        if self.market_failure: raise RuntimeError("market missing")
        return Result(0)

@pytest.mark.asyncio
async def test_registry_active_identity_and_truncation_are_read_only():
    session=Session()
    result=await paper_status_contract(session,closed=3,candidates=5,represented=1,first_at=None,latest_at=None)
    assert len(result["policy_registry"])==50 and result["policy_registry_truncated"] is True
    assert result["policy_registry"][0]["state"]=="ACTIVE"
    assert result["policy_registry"][1]["state"]=="PROVISIONED"
    assert result["policy"]["policy_identity"]==session.identity
    assert result["policy_registry"][0]["policy_identity"]["provenance"]["comparison_evidence_sha256"]=="c"*64
    assert result["prospective_evidence"]["pending_outcomes"]==2
    assert all(s.lstrip().startswith("SELECT") for s in session.statements)
    assert "LIMIT 51" in session.statements[0] and session.savepoints==2

@pytest.mark.asyncio
async def test_optional_source_failures_are_isolated_and_never_false_not_set():
    session=Session(market_failure=True,active_failure=True)
    result=await paper_status_contract(session,closed=0,candidates=0,represented=0,first_at=None,latest_at=None)
    assert result["policy"]["status"]=="UNKNOWN"
    assert result["prospective_evidence"]["readiness"]["observed_market_cap_samples"] is None
    assert result["prospective_evidence"]["readiness"]["market_cap_samples_available"] is False
    assert len(session.statements)==3 and session.savepoints==2

@pytest.mark.asyncio
async def test_mandatory_registry_failure_cannot_be_successful_empty_evidence():
    with pytest.raises(RuntimeError):
        await paper_status_contract(Session(registry_failure=True),closed=0,candidates=0,represented=0,first_at=None,latest_at=None)
