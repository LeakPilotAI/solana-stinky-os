from pathlib import Path
P=Path(__file__).parents[1]/"scripts"/"run_genesis_service.py"

def source():
    return P.read_text()

def test_maintain_runs_prospective_intelligence_in_order():
    s=source()
    shadow=s.index("run_intelligence_shadow_scorer.py")
    paper=s.index("run_intelligence_paper_decisions.py")
    assert shadow < paper
    assert "2026-10-05T12:46:27.418241+00:00" in s
    assert '"--limit", "500"' in s

def test_capture_remains_in_maintain_not_live_executor():
    s=source()
    maintain=s.index('elif name == "maintain":')
    capture=s.index("run_intelligence_shadow_scorer.py")
    assert capture > maintain
    assert "run_intelligence_paper_decisions.py" in s

def test_slow_maintenance_isolated_from_capture_loop():
    s=source()
    maintain=s[s.index('elif name == "maintain":'):]
    slow=maintain.index("def slow_maintenance_loop()")
    thread=maintain.index("slow_thread.start()")
    capture=maintain.index("run_intelligence_shadow_scorer.py")
    assert slow < thread < capture
    assert 'name="genesis-slow-maintenance"' in maintain
    assert "daemon=True" in maintain
    assert "time.sleep(21600)" in maintain
    assert "next_job" not in maintain

def test_capture_contract_stays_paper_only_and_one_minute():
    s=source()
    maintain=s[s.index('elif name == "maintain":'):]
    assert "PAPER/evidence-only" in maintain
    assert 'attempts=1' in maintain
    assert "time.sleep(60)" in maintain
    assert "run_intelligence_shadow_scorer.py" in maintain
    assert "run_intelligence_paper_decisions.py" in maintain
