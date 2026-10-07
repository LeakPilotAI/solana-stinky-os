import importlib.util
from datetime import datetime,timedelta,timezone
from pathlib import Path
from uuid import uuid4
import pytest

@pytest.fixture
def m(monkeypatch):
    root=Path(__file__).parents[1]
    monkeypatch.syspath_prepend(str(root/"scripts"))
    spec=importlib.util.spec_from_file_location("v2_worker",root/"scripts/run_intelligence_execution_v2.py")
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod

@pytest.fixture
def source():
    t=datetime(2026,10,7,tzinfo=timezone.utc)
    return {"id":1,"track_id":uuid4(),"mint":"fixture","policy_version":"genesis-evidence-paper-v3",
            "decision":"PAPER_WOULD_ENTER","migration_at":t,"scored_at":t+timedelta(seconds=60),"decided_at":t+timedelta(seconds=61)}

def plan_for(m,source):
    return m.make_plan(source,source["migration_at"],source["decided_at"]+timedelta(seconds=1))

def snapshots(m,plan):
    return [{"snapshot_id":uuid4(),"mint":"fixture","captured_at":m.dt(plan[key]),"price_usd":price,"liquidity_usd":2000}
            for key,price in [("entry_target",10),("exit_target",12)]]

@pytest.mark.parametrize("field,value",[("decision","PAPER_PASS"),("policy_version","genesis-evidence-paper-v1")])
def test_wrong_source_is_not_admitted(m,source,field,value):
    source[field]=value
    assert plan_for(m,source) is None

@pytest.mark.parametrize("offset",[30,31,1000])
def test_late_plan_is_not_backfilled(m,source,offset):
    assert m.make_plan(source,source["migration_at"],source["decided_at"]+timedelta(seconds=offset)) is None

def test_preboundary_and_future_source_fail_closed(m,source):
    assert m.make_plan(source,source["migration_at"]+timedelta(microseconds=1),source["decided_at"]) is None
    assert m.make_plan(source,source["migration_at"],source["decided_at"]-timedelta(seconds=1)) is None

@pytest.mark.parametrize("offset,expected",[(29,"PENDING"),(30,"PAPER_PRICED")])
def test_window_maturity_and_costed_paper_result(m,source,offset,expected):
    p=plan_for(m,source);rows=snapshots(m,p)
    r=m.evaluate(p,rows,m.dt(p["exit_target"])+timedelta(seconds=offset))
    assert r["status"]==expected
    assert r["window_complete"] is (offset==30)
    if offset==29: assert "net_multiple" not in r
    else:
        assert r["net_multiple"]==pytest.approx(1.2*.99/1.01)
        assert r["paper_pnl_usd"]==pytest.approx(100*(1.2*.99/1.01-1))
        assert r["entry_delay_sec"]==r["exit_delay_sec"]==0
        assert r["plan_sha256"]==m.policy_hash(p)
    assert r["paper_only"] and not r["live_execution"] and not r["performance_validation"]

@pytest.mark.parametrize("case",["missing_entry","missing_exit","late_exit","wrong_mint","invalid_price","invalid_liquidity"])
def test_missing_or_invalid_market_evidence_is_unknown(m,source,case):
    p=plan_for(m,source);rows=snapshots(m,p)
    if case=="missing_entry": rows=rows[1:]
    elif case=="missing_exit": rows=rows[:1]
    elif case=="late_exit": rows[1]["captured_at"]+=timedelta(seconds=31)
    elif case=="wrong_mint": rows[0]["mint"]="other"
    elif case=="invalid_price": rows[0]["price_usd"]=float("nan")
    else: rows[0]["liquidity_usd"]=None
    r=m.evaluate(p,rows,m.dt(p["exit_target"])+timedelta(seconds=60))
    assert r["status"]=="UNKNOWN" and "net_multiple" not in r

def test_observed_low_liquidity_rejects_and_never_selects_later_better_entry(m,source):
    p=plan_for(m,source);rows=snapshots(m,p);rows[0]["liquidity_usd"]=999
    rows.append({**rows[0],"snapshot_id":uuid4(),"captured_at":rows[0]["captured_at"]+timedelta(seconds=1),"liquidity_usd":2000})
    r=m.evaluate(p,list(reversed(rows)),m.dt(p["exit_target"])+timedelta(seconds=30))
    assert r["status"]=="REJECTED" and "net_multiple" not in r

@pytest.mark.parametrize("field",["policy_sha256","planned_at","entry_target","exit_target"])
def test_changed_plan_schedule_or_policy_is_rejected(m,source,field):
    p=plan_for(m,source)
    p[field]="bad" if field=="policy_sha256" else (m.dt(p["exit_target"])+timedelta(seconds=900)).isoformat()
    with pytest.raises(ValueError):m.evaluate(p,[],m.dt(p["exit_target"])+timedelta(seconds=1000))


@pytest.mark.asyncio
async def test_postgres_terminal_results_replay_and_immutability(m):
    import os,json,asyncpg
    url=os.getenv("GENESIS_V2_TEST_DSN")
    if not url:pytest.skip("requires isolated GENESIS_V2_TEST_DSN")
    conn=await asyncpg.connect(url);schema="v2_evidence_"+uuid4().hex
    try:
        await conn.execute(f'CREATE SCHEMA "{schema}"')
        await conn.execute(f'SET search_path TO "{schema}"')
        await conn.execute("""CREATE TABLE intelligence_paper_decisions(id bigint PRIMARY KEY,track_id uuid,mint text,policy_version text,decision text,decided_at timestamptz,shadow_score_id bigint);
            CREATE TABLE intelligence_shadow_scores(id bigint,track_id uuid,mint text,scored_at timestamptz);
            CREATE TABLE migration_tracks(track_id uuid,mint text,migration_at timestamptz);
            CREATE TABLE market_snapshots(snapshot_id uuid,mint text,captured_at timestamptz,price_usd numeric,liquidity_usd numeric);""")
        await conn.execute((m.ROOT/"services/post-migration-collector/migrations/007_intelligence_execution_v2_registry.sql").read_text())
        now=await conn.fetchval("SELECT clock_timestamp()")
        boundary=now-timedelta(minutes=20)
        await conn.execute("INSERT INTO intelligence_execution_v2_registry VALUES($1,$2,$3::jsonb,$4)",m.VERSION,m.policy_hash(m.policy()),json.dumps(m.policy()),boundary)
        await conn.execute((m.ROOT/"services/post-migration-collector/migrations/008_intelligence_execution_v2_evidence.sql").read_text())
        source={"id":1,"track_id":uuid4(),"mint":"fixture","policy_version":m.policy()["source_policy"],"decision":"PAPER_WOULD_ENTER",
                "migration_at":boundary+timedelta(seconds=1),"scored_at":boundary+timedelta(seconds=61),"decided_at":boundary+timedelta(seconds=62)}
        await conn.execute("INSERT INTO intelligence_paper_decisions VALUES(1,$1,'fixture',$2,'PAPER_WOULD_ENTER',$3,1)",source["track_id"],source["policy_version"],source["decided_at"])
        plan=m.make_plan(source,boundary,source["decided_at"]+timedelta(seconds=1))
        await conn.execute("""INSERT INTO intelligence_execution_v2_plans(policy_version,policy_sha256,paper_decision_id,track_id,mint,planned_at,entry_target,exit_target,plan,plan_sha256)
            VALUES($1,$2,1,$3,'fixture',$4,$5,$6,$7::jsonb,$8)""",m.VERSION,plan["policy_sha256"],source["track_id"],m.dt(plan["planned_at"]),m.dt(plan["entry_target"]),m.dt(plan["exit_target"]),json.dumps(plan),m.policy_hash(plan))
        for row in snapshots(m,plan):
            await conn.execute("INSERT INTO market_snapshots VALUES($1,$2,$3,$4,$5)",row["snapshot_id"],row["mint"],row["captured_at"],row["price_usd"],row["liquidity_usd"])
        fresh_track=uuid4()
        fresh=await conn.fetchval("SELECT clock_timestamp()")
        await conn.execute("INSERT INTO migration_tracks VALUES($1,'fresh',$2)",fresh_track,fresh-timedelta(seconds=61))
        await conn.execute("INSERT INTO intelligence_shadow_scores VALUES(2,$1,'fresh',$2)",fresh_track,fresh-timedelta(seconds=1))
        await conn.execute("INSERT INTO intelligence_paper_decisions VALUES(2,$1,'fresh',$2,'PAPER_WOULD_ENTER',$3,2)",fresh_track,source["policy_version"],fresh)
        first=await m.run(conn);assert first["recorded"]==1 and first["admitted"]==1
        assert (await m.run(conn))["recorded"]==0
        r=await conn.fetchrow("SELECT * FROM intelligence_execution_v2_results")
        payload=json.loads(r["result"])
        assert payload["status"]=="PAPER_PRICED" and r["result_sha256"]==m.policy_hash(payload)
        for table in ["intelligence_execution_v2_plans","intelligence_execution_v2_results"]:
            for sql in [f"DELETE FROM {table}",f"TRUNCATE {table} CASCADE",f"UPDATE {table} SET "+("plan=plan" if table.endswith("plans") else "result=result")]:
                with pytest.raises(asyncpg.RaiseError,match="immutable"):await conn.execute(sql)
        assert await conn.fetchval("SELECT count(*) FROM intelligence_execution_v2_results")==1
    finally:
        await conn.execute(f'DROP SCHEMA "{schema}" CASCADE');await conn.close()


def test_pending_report_has_no_pnl_and_no_adequacy(m,source):
    p=plan_for(m,source)
    row={"plan":p,"plan_sha256":m.policy_hash(p),"result":None,"result_sha256":None}
    r=m.summarize([row])
    assert r["counts"]=={"PENDING":1}
    assert r["paper_pnl_usd"] is None and r["net_multiple_mean"] is None
    assert not r["evaluation_ready"] and not r["performance_validation"]


@pytest.mark.parametrize("field,value",[("status","PENDING"),("window_complete",False),
    ("live_execution",True),("net_multiple",1000),("as_of","2026-10-07T00:01:00+00:00")])
def test_self_consistent_hash_does_not_authorize_invalid_result(m,source,field,value):
    p=plan_for(m,source)
    result=m.evaluate(p,snapshots(m,p),m.dt(p["exit_target"])+timedelta(seconds=30))
    result[field]=value
    row={"plan":p,"plan_sha256":m.policy_hash(p),"result":result,"result_sha256":m.policy_hash(result)}
    with pytest.raises(ValueError):m.summarize([row])


def test_adequacy_requires_predeclared_session_and_complete_path_gates(m,source):
    rows=[]
    for i in range(100):
        p=plan_for(m,{**source,"mint":str(i),"runtime_session":{"service":"collector","supervisor_pid":i%5,"started_at":str(i%5),"identity_verified":True}})
        snaps=[{**r,"mint":str(i)} for r in snapshots(m,p)]
        result=m.evaluate(p,snaps,m.dt(p["exit_target"])+timedelta(seconds=30))
        rows.append({"plan":p,"plan_sha256":m.policy_hash(p),"result":result,"result_sha256":m.policy_hash(result)})
    r=m.summarize(rows)
    assert r["evaluation_ready"] and r["verified_runtime_sessions"]==5
    assert not r["performance_validation"] and not r["live_execution"]
    assert not m.summarize(rows[:99])["evaluation_ready"]
    for row in rows:
        row["plan"]["runtime_session"]=None
        row["plan_sha256"]=m.policy_hash(row["plan"])
        row["result"]["plan_sha256"]=row["plan_sha256"]
        row["result_sha256"]=m.policy_hash(row["result"])
    assert not m.summarize(rows)["evaluation_ready"]
    rows[0]["result"]["net_multiple"]=1000
    with pytest.raises(ValueError,match="integrity"):m.summarize(rows)


def test_service_gives_v2_independent_sub_deadline_cadence():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    service = (
        root / "scripts" / "run_genesis_service.py"
    ).read_text(encoding="utf-8")

    assert "def intelligence_execution_v2_loop()" in service
    assert 'name="genesis-intelligence-execution-v2"' in service
    assert 'run_intelligence_execution_v2.py' in service

    loop_start = service.index("def intelligence_execution_v2_loop()")
    loop_end = service.index("v2_thread = threading.Thread", loop_start)
    v2_loop = service[loop_start:loop_end]

    assert "time.sleep(10)" in v2_loop
    assert "time.sleep(60)" not in v2_loop

    research_marker = (
        "# V2 prospective capture runs independently at a faster cadence above."
    )
    assert research_marker in service
