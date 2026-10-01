from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_accumulation_report_is_measurement_only():
 t=(ROOT/"scripts"/"report_prospective_evidence_accumulation.py").read_text()
 for token in ['"criteria_applied":False','"sufficiency_judgment":False','"threshold_proposal":None','"automatic_activation":False','"performance_validation":False',"MEASUREMENT_ONLY_NO_SUFFICIENCY_CRITERIA"]:
  assert token in t
 low=t.lower()
 for forbidden in ("provision_paper_policy","insert into paper_policy_registry","update paper_policy_active","send_transaction","sign_transaction","private_key","solana.rpc"):
  assert forbidden not in low
def test_accumulation_report_measures_closed_classes_and_market_samples():
 t=(ROOT/"scripts"/"report_prospective_evidence_accumulation.py").read_text()
 for token in ("canonical_outcome='RUNNER'","canonical_outcome='HELD'","canonical_outcome='FADE'","market_outcome_observations","represented_outcome_classes"):
  assert token in t
def test_accumulation_launcher_starts_only_postgres():
 t=(ROOT/"Run-Prospective-Evidence-Report.cmd").read_text()
 assert "docker compose -p project-genesis up -d postgres" in t
 assert "report_prospective_evidence_accumulation.py" in t
 assert "Start-Stinky-OS" not in t

def test_accumulation_launcher_retries_transient_report_failures_but_stays_fail_closed():
 t=(ROOT/"Run-Prospective-Evidence-Report.cmd").read_text()
 assert "for /L %%I in (1,1,3) do" in t
 assert "retrying in 3 seconds" in t
 assert "FAILED after 3 attempts" in t
 assert "goto :report_ok" in t
 assert "exit /b 1" in t
