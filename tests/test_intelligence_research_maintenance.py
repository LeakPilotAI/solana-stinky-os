from pathlib import Path
P=Path(__file__).parents[1]/"scripts"/"run_genesis_service.py"
def test_maintain_runs_prospective_intelligence_in_order():
 s=P.read_text()
 shadow=s.index("run_intelligence_shadow_scorer.py")
 paper=s.index("run_intelligence_paper_decisions.py")
 assert shadow < paper
 assert "2026-10-05T12:46:27.418241+00:00" in s
 assert '"--limit", "500"' in s
def test_capture_remains_in_maintain_not_live_executor():
 s=P.read_text()
 maintain=s.index('elif name == "maintain":')
 capture=s.index("run_intelligence_shadow_scorer.py")
 assert capture > maintain
 assert "run_intelligence_paper_decisions.py" in s
